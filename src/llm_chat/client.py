import time
import json
from typing import List, Dict, Any, Optional, Callable, Generator
import requests
from llm_chat.config import Config
from llm_chat.protocols import get_protocol, ToolCall
from llm_chat.tools import get_tool_registry, WebSearchTool, CalculatorTool


class LLMClient:
    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()
        self.session.timeout = config.llm.timeout
        
        if config.llm.http_proxy or config.llm.https_proxy:
            proxies = {}
            if config.llm.http_proxy:
                proxies["http"] = config.llm.http_proxy
            if config.llm.https_proxy:
                proxies["https"] = config.llm.https_proxy
            self.session.proxies = proxies
        
        self.protocol = get_protocol(
            protocol=config.llm.protocol,
            base_url=config.llm.base_url,
            api_key=config.llm.api_key,
            model=config.llm.model,
            timeout=config.llm.timeout,
            max_retries=config.llm.max_retries
        )
        self._tool_executor: Optional[Callable[[str, Dict[str, Any]], str]] = None
        self._tool_registry = get_tool_registry()
        self._setup_builtin_tools()
    
    def _setup_builtin_tools(self):
        builtin_config = self.config.builtin_tools
        
        if builtin_config.web_search.enabled:
            search_tool = WebSearchTool(
                engine=builtin_config.web_search.engine,
                api_key=builtin_config.web_search.api_key,
                http_proxy=self.config.llm.http_proxy,
                https_proxy=self.config.llm.https_proxy
            )
            self._tool_registry.register(search_tool)
        
        if builtin_config.calculator.enabled:
            calc_tool = CalculatorTool()
            self._tool_registry.register(calc_tool)
    
    def set_tool_executor(self, executor: Callable[[str, Dict[str, Any]], str]):
        self._tool_executor = executor
    
    def get_builtin_tools(self) -> List[Dict[str, Any]]:
        return self._tool_registry.get_tools_for_openai()
    
    def has_builtin_tools(self) -> bool:
        return len(self._tool_registry.get_all_tools()) > 0
    
    def execute_builtin_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        return self._tool_registry.execute_tool(name, **arguments)
    
    def chat(self, message: str, history: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        if history is None:
            history = []
        
        messages = history.copy()
        messages.append({"role": "user", "content": message})
        
        return self._send_chat_request(messages, **kwargs)
    
    def chat_stream(
        self, 
        message: str, 
        history: Optional[List[Dict[str, str]]] = None, 
        **kwargs
    ) -> Generator[str, None, None]:
        if history is None:
            history = []
        
        messages = history.copy()
        messages.append({"role": "user", "content": message})
        
        yield from self._send_chat_request_stream(messages, **kwargs)
    
    def chat_stream_with_tools(
        self,
        message: str,
        tools: List[Dict[str, Any]],
        history: Optional[List[Dict[str, Any]]] = None,
        max_iterations: int = 10,
        **kwargs
    ) -> Generator[Any, None, None]:
        if not self.protocol.supports_tools():
            yield from self.chat_stream(message, history, **kwargs)
            return
        
        if history is None:
            history = []
        
        current_messages = history.copy()
        current_messages.append({"role": "user", "content": message})
        
        for iteration in range(max_iterations):
            url = self.protocol.get_chat_url()
            headers = self.protocol.get_headers()
            data = self.protocol.build_chat_request_with_tools(
                current_messages,
                tools,
                stream=True,
                **kwargs
            )
            
            full_text = ""
            tool_calls_data = []
            
            try:
                response = self.session.post(
                    url,
                    json=data,
                    headers=headers,
                    stream=True
                )
                response.raise_for_status()
                
                for line in response.iter_lines():
                    if not line:
                        continue
                    
                    line_text = line.decode('utf-8')
                    
                    if line_text.startswith('data: '):
                        data_str = line_text[6:]
                        
                        if data_str == '[DONE]':
                            break
                        
                        try:
                            chunk = json.loads(data_str)
                            content = self.protocol.parse_stream_chunk(chunk)
                            if content:
                                full_text += content
                                yield content
                            
                            chunk_tool_calls = self._parse_stream_tool_calls(chunk)
                            if chunk_tool_calls:
                                tool_calls_data.extend(chunk_tool_calls)
                                
                        except json.JSONDecodeError:
                            continue
                            
            except requests.RequestException as e:
                error_msg = str(e)
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_detail = e.response.json()
                        error_msg = f"{error_msg}\n详情: {error_detail}"
                    except:
                        error_msg = f"{error_msg}\n响应内容: {e.response.text}"
                raise Exception(f"API 请求失败: {error_msg}")
            
            if not tool_calls_data:
                return
            
            tool_calls = self._merge_tool_calls(tool_calls_data)
            
            assistant_message = {
                "role": "assistant",
                "content": full_text if full_text else None,
                "tool_calls": tool_calls
            }
            current_messages.append(assistant_message)
            
            for tool_call in tool_calls:
                tool_name = tool_call["function"]["name"]
                tool_args = tool_call["function"]["arguments"]
                
                yield ("tool_call", tool_name, tool_args)
                
                if self._tool_registry.has_tool(tool_name):
                    try:
                        args = json.loads(tool_args)
                        tool_result = self.execute_builtin_tool(tool_name, args)
                    except Exception as e:
                        tool_result = f"Error: {str(e)}"
                elif self._tool_executor:
                    try:
                        args = json.loads(tool_args)
                        tool_result = self._tool_executor(tool_name, args)
                    except Exception as e:
                        tool_result = f"Error: {str(e)}"
                else:
                    tool_result = f"Error: No tool executor for {tool_name}"
                
                tool_message = {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": tool_result
                }
                current_messages.append(tool_message)
    
    def _parse_stream_tool_calls(self, chunk: Dict[str, Any]) -> List[Dict[str, Any]]:
        choices = chunk.get("choices", [])
        if not choices:
            return []
        
        delta = choices[0].get("delta", {})
        tool_calls = delta.get("tool_calls", [])
        
        return tool_calls
    
    def _merge_tool_calls(self, tool_calls_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged = {}
        
        for tc in tool_calls_data:
            idx = tc.get("index", 0)
            if idx not in merged:
                merged[idx] = {
                    "id": tc.get("id", ""),
                    "type": tc.get("type", "function"),
                    "function": {
                        "name": "",
                        "arguments": ""
                    }
                }
            
            if tc.get("id"):
                merged[idx]["id"] = tc["id"]
            
            func = tc.get("function", {})
            if func.get("name"):
                merged[idx]["function"]["name"] = func["name"]
            if func.get("arguments"):
                merged[idx]["function"]["arguments"] += func["arguments"]
        
        return list(merged.values())
    
    def chat_with_tools(
        self, 
        message: str, 
        tools: List[Dict[str, Any]],
        history: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> str:
        if history is None:
            history = []
        
        messages = history.copy()
        messages.append({"role": "user", "content": message})
        
        return self._send_chat_request_with_tools(messages, tools, **kwargs)
    
    def _send_chat_request(self, messages: List[Dict[str, str]], **kwargs) -> str:
        url = self.protocol.get_chat_url()
        headers = self.protocol.get_headers()
        data = self.protocol.build_chat_request(messages, **kwargs)
        
        for i in range(self.config.llm.max_retries):
            try:
                response = self.session.post(url, json=data, headers=headers)
                response.raise_for_status()
                result = response.json()
                return self.protocol.parse_chat_response(result)
            except requests.RequestException as e:
                if i == self.config.llm.max_retries - 1:
                    error_msg = str(e)
                    if hasattr(e, 'response') and e.response is not None:
                        try:
                            error_detail = e.response.json()
                            error_msg = f"{error_msg}\n详情: {error_detail}"
                        except:
                            error_msg = f"{error_msg}\n响应内容: {e.response.text}"
                    raise Exception(f"API 请求失败: {error_msg}")
                print(f"请求失败，{i+1}秒后重试: {e}")
                time.sleep(1)
        
        return ""
    
    def _send_chat_request_stream(
        self, 
        messages: List[Dict[str, str]], 
        **kwargs
    ) -> Generator[str, None, None]:
        url = self.protocol.get_chat_url()
        headers = self.protocol.get_headers()
        data = self.protocol.build_chat_request(messages, stream=True, **kwargs)
        
        try:
            response = self.session.post(
                url, 
                json=data, 
                headers=headers, 
                stream=True
            )
            response.raise_for_status()
            
            for line in response.iter_lines():
                if not line:
                    continue
                
                line_text = line.decode('utf-8')
                
                if line_text.startswith('data: '):
                    data_str = line_text[6:]
                    
                    if data_str == '[DONE]':
                        break
                    
                    try:
                        chunk = json.loads(data_str)
                        content = self.protocol.parse_stream_chunk(chunk)
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue
                        
        except requests.RequestException as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = f"{error_msg}\n详情: {error_detail}"
                except:
                    error_msg = f"{error_msg}\n响应内容: {e.response.text}"
            raise Exception(f"API 请求失败: {error_msg}")
    
    def _send_chat_request_with_tools(
        self, 
        messages: List[Dict[str, Any]], 
        tools: List[Dict[str, Any]],
        max_iterations: int = 10,
        **kwargs
    ) -> str:
        if not self.protocol.supports_tools():
            return self._send_chat_request(messages, **kwargs)
        
        url = self.protocol.get_chat_url()
        headers = self.protocol.get_headers()
        
        current_messages = messages.copy()
        
        for iteration in range(max_iterations):
            data = self.protocol.build_chat_request_with_tools(
                current_messages, 
                tools, 
                **kwargs
            )
            
            for i in range(self.config.llm.max_retries):
                try:
                    response = self.session.post(url, json=data, headers=headers)
                    response.raise_for_status()
                    result = response.json()
                    break
                except requests.RequestException as e:
                    if i == self.config.llm.max_retries - 1:
                        raise
                    print(f"请求失败，{i+1}秒后重试: {e}")
                    time.sleep(1)
            else:
                continue
            
            if not self.protocol.has_tool_calls(result):
                return self.protocol.parse_chat_response(result)
            
            assistant_message = self.protocol.get_assistant_message_from_response(result)
            current_messages.append(assistant_message)
            
            tool_calls = self.protocol.parse_tool_calls(result)
            
            for tool_call in tool_calls:
                if self._tool_registry.has_tool(tool_call.name):
                    try:
                        tool_result = self.execute_builtin_tool(tool_call.name, tool_call.arguments)
                        is_error = False
                    except Exception as e:
                        tool_result = str(e)
                        is_error = True
                elif self._tool_executor:
                    try:
                        tool_result = self._tool_executor(tool_call.name, tool_call.arguments)
                        is_error = False
                    except Exception as e:
                        tool_result = str(e)
                        is_error = True
                else:
                    tool_result = f"Error: No tool executor configured for {tool_call.name}"
                    is_error = True
                
                tool_message = self.protocol.build_tool_result_message(
                    tool_call, 
                    tool_result, 
                    is_error
                )
                current_messages.append(tool_message)
        
        return self.protocol.parse_chat_response(result)
    
    def generate(self, prompt: str, **kwargs) -> str:
        url = self.protocol.get_generate_url()
        headers = self.protocol.get_headers()
        data = self.protocol.build_generate_request(prompt, **kwargs)
        
        for i in range(self.config.llm.max_retries):
            try:
                response = self.session.post(url, json=data, headers=headers)
                response.raise_for_status()
                result = response.json()
                return self.protocol.parse_generate_response(result)
            except requests.RequestException as e:
                if i == self.config.llm.max_retries - 1:
                    error_msg = str(e)
                    if hasattr(e, 'response') and e.response is not None:
                        try:
                            error_detail = e.response.json()
                            error_msg = f"{error_msg}\n详情: {error_detail}"
                        except:
                            error_msg = f"{error_msg}\n响应内容: {e.response.text}"
                    raise Exception(f"API 请求失败: {error_msg}")
                print(f"请求失败，{i+1}秒后重试: {e}")
                time.sleep(1)
        
        return ""
