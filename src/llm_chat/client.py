import time
import json
import logging
from typing import List, Dict, Any, Optional, Callable, Generator
import requests
from llm_chat.config import Config
from llm_chat.protocols import get_protocol, ToolCall
from llm_chat.tools import get_tool_registry, ToolExecutor
from llm_chat.skills import SkillManager
from llm_chat.skills.web_search import WebSearchSkill
from llm_chat.skills.calculator import CalculatorSkill
from llm_chat.skills.web_fetch import WebFetchSkill

logger = logging.getLogger(__name__)


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
        
        logger.info(f"初始化 LLMClient: protocol={config.llm.protocol}, model={config.llm.model}, base_url={config.llm.base_url}")
        
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
        self._skill_manager = SkillManager(self._tool_registry)
        self._tool_executor_instance = ToolExecutor(
            tool_registry=self._tool_registry,
            max_workers=config.tools.max_workers,
            max_retries=config.tools.max_retries,
            retry_delay=config.tools.retry_delay,
            timeout=config.tools.timeout
        )
        self._setup_skills()
    
    def _setup_skills(self):
        self._skill_manager.register_skill_class(WebSearchSkill)
        self._skill_manager.register_skill_class(CalculatorSkill)
        self._skill_manager.register_skill_class(WebFetchSkill)
        
        if self.config.external_skill_dirs:
            self._skill_manager.discover_skills(self.config.external_skill_dirs)
        
        skill_configs = self.config.skills.get_all_skill_configs()
        
        if "web_search" in skill_configs:
            web_search_config = skill_configs["web_search"]
            if "http_proxy" not in web_search_config:
                web_search_config["http_proxy"] = self.config.llm.http_proxy
            if "https_proxy" not in web_search_config:
                web_search_config["https_proxy"] = self.config.llm.https_proxy
            if "timeout" not in web_search_config:
                web_search_config["timeout"] = self.config.llm.timeout
        
        if "web_fetch" in skill_configs:
            web_fetch_config = skill_configs["web_fetch"]
            if "http_proxy" not in web_fetch_config:
                web_fetch_config["http_proxy"] = self.config.llm.http_proxy
            if "https_proxy" not in web_fetch_config:
                web_fetch_config["https_proxy"] = self.config.llm.https_proxy
            if "timeout" not in web_fetch_config:
                web_fetch_config["timeout"] = self.config.llm.timeout
        
        self._skill_manager.load_from_config(skill_configs)
        
        logger.info(f"Skills setup complete. Loaded: {self._skill_manager.list_skill_names()}")
    
    def set_tool_executor(self, executor: Callable[[str, Dict[str, Any]], str]):
        self._tool_executor = executor
    
    def get_skill_manager(self) -> SkillManager:
        return self._skill_manager
    
    def get_builtin_tools(self) -> List[Dict[str, Any]]:
        return self._tool_registry.get_tools_for_openai()
    
    def has_builtin_tools(self) -> bool:
        return len(self._tool_registry.get_all_tools()) > 0
    
    def execute_builtin_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        return self._tool_registry.execute_tool(name, **arguments)
    
    def chat(self, message: str, history: Optional[List[Dict[str, str]]] = None, system_context: Optional[str] = None, **kwargs) -> str:
        if history is None:
            history = []
        
        messages = []
        
        if system_context:
            messages.append({"role": "system", "content": system_context})
            logger.debug(f"添加系统上下文: {len(system_context)} 字符")
        
        messages.extend(history)
        messages.append({"role": "user", "content": message})
        
        logger.info(f"发送聊天请求: message_length={len(message)}, history_count={len(history)}, has_system_context={system_context is not None}")
        
        return self._send_chat_request(messages, **kwargs)
    
    def chat_stream(
        self, 
        message: str, 
        history: Optional[List[Dict[str, str]]] = None, 
        system_context: Optional[str] = None,
        **kwargs
    ) -> Generator[str, None, None]:
        if history is None:
            history = []
        
        messages = []
        
        if system_context:
            messages.append({"role": "system", "content": system_context})
            logger.debug(f"添加系统上下文: {len(system_context)} 字符")
        
        messages.extend(history)
        messages.append({"role": "user", "content": message})
        
        logger.info(f"发送流式聊天请求: message_length={len(message)}, history_count={len(history)}, has_system_context={system_context is not None}")
        
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
            logger.warning("当前协议不支持工具调用，使用普通流式聊天")
            yield from self.chat_stream(message, history, **kwargs)
            return
        
        if history is None:
            history = []
        
        current_messages = history.copy()
        current_messages.append({"role": "user", "content": message})
        
        logger.info(f"开始带工具的流式聊天: tools={[t['function']['name'] for t in tools]}, max_iterations={max_iterations}")
        
        for iteration in range(max_iterations):
            url = self.protocol.get_chat_url()
            headers = self.protocol.get_headers()
            data = self.protocol.build_chat_request_with_tools(
                current_messages,
                tools,
                stream=True,
                **kwargs
            )
            
            logger.debug(f"迭代 {iteration + 1}: 发送请求到 {url}")
            
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
                
                logger.debug(f"响应状态码: {response.status_code}")
                
                for line in response.iter_lines():
                    if not line:
                        continue
                    
                    line_text = line.decode('utf-8')
                    
                    if line_text.startswith('data: '):
                        data_str = line_text[6:]
                        
                        if data_str == '[DONE]':
                            logger.debug("流式响应结束")
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
                logger.error(f"API 请求失败: {error_msg}")
                raise Exception(f"API 请求失败: {error_msg}")
            
            if not tool_calls_data:
                logger.info(f"流式聊天完成: response_length={len(full_text)}")
                return
            
            tool_calls = self._merge_tool_calls(tool_calls_data)
            
            logger.info(f"检测到 {len(tool_calls)} 个工具调用")
            
            assistant_message = {
                "role": "assistant",
                "content": full_text if full_text else None,
                "tool_calls": tool_calls
            }
            current_messages.append(assistant_message)
            
            self._tool_executor_instance.tool_executor = self._tool_executor
            tool_results = self._tool_executor_instance.execute_tools_parallel(tool_calls)
            
            for result in tool_results:
                tool_name = "unknown"
                tool_args = "{}"
                for tc in tool_calls:
                    if tc["id"] == result["tool_call_id"]:
                        tool_name = tc["function"]["name"]
                        tool_args = tc["function"].get("arguments", "{}")
                        break
                
                yield ("tool_call_start", tool_name, tool_args)
                
                tool_message = {
                    "role": "tool",
                    "tool_call_id": result["tool_call_id"],
                    "content": result["content"]
                }
                current_messages.append(tool_message)
                
                yield ("tool_call_end", tool_name, tool_args, result.get("content", "")[:500])
    
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
        
        logger.info(f"发送带工具的聊天请求: tools={[t['function']['name'] for t in tools]}")
        
        return self._send_chat_request_with_tools(messages, tools, **kwargs)
    
    def _send_chat_request(self, messages: List[Dict[str, str]], **kwargs) -> str:
        url = self.protocol.get_chat_url()
        headers = self.protocol.get_headers()
        data = self.protocol.build_chat_request(messages, **kwargs)
        
        logger.debug(f"发送请求: url={url}, model={data.get('model')}, messages_count={len(messages)}")
        
        for i in range(self.config.llm.max_retries):
            try:
                response = self.session.post(url, json=data, headers=headers)
                response.raise_for_status()
                result = response.json()
                
                response_text = self.protocol.parse_chat_response(result)
                logger.info(f"聊天响应: length={len(response_text)}")
                
                return response_text
            except requests.RequestException as e:
                if i == self.config.llm.max_retries - 1:
                    error_msg = str(e)
                    if hasattr(e, 'response') and e.response is not None:
                        try:
                            error_detail = e.response.json()
                            error_msg = f"{error_msg}\n详情: {error_detail}"
                        except:
                            error_msg = f"{error_msg}\n响应内容: {e.response.text}"
                    logger.error(f"API 请求失败(重试 {i+1}/{self.config.llm.max_retries}): {error_msg}")
                    raise Exception(f"API 请求失败: {error_msg}")
                logger.warning(f"请求失败，{i+1}秒后重试: {e}")
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
        
        logger.debug(f"发送流式请求: url={url}, model={data.get('model')}, messages_count={len(messages)}")
        
        try:
            response = self.session.post(
                url, 
                json=data, 
                headers=headers, 
                stream=True
            )
            response.raise_for_status()
            
            logger.debug(f"流式响应开始: status_code={response.status_code}")
            
            chunk_count = 0
            for line in response.iter_lines():
                if not line:
                    continue
                
                line_text = line.decode('utf-8')
                
                if line_text.startswith('data: '):
                    data_str = line_text[6:]
                    
                    if data_str == '[DONE]':
                        logger.info(f"流式响应完成: chunks={chunk_count}")
                        break
                    
                    try:
                        chunk = json.loads(data_str)
                        content = self.protocol.parse_stream_chunk(chunk)
                        if content:
                            chunk_count += 1
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
            logger.error(f"流式请求失败: {error_msg}")
            raise Exception(f"API 请求失败: {error_msg}")
    
    def _send_chat_request_with_tools(
        self, 
        messages: List[Dict[str, Any]], 
        tools: List[Dict[str, Any]],
        max_iterations: int = 10,
        **kwargs
    ) -> str:
        if not self.protocol.supports_tools():
            logger.warning("当前协议不支持工具调用，使用普通聊天")
            return self._send_chat_request(messages, **kwargs)
        
        url = self.protocol.get_chat_url()
        headers = self.protocol.get_headers()
        
        current_messages = messages.copy()
        
        logger.info(f"开始带工具的聊天迭代: max_iterations={max_iterations}")
        
        for iteration in range(max_iterations):
            data = self.protocol.build_chat_request_with_tools(
                current_messages, 
                tools, 
                **kwargs
            )
            
            logger.debug(f"迭代 {iteration + 1}: 发送请求")
            
            for i in range(self.config.llm.max_retries):
                try:
                    response = self.session.post(url, json=data, headers=headers)
                    response.raise_for_status()
                    result = response.json()
                    break
                except requests.RequestException as e:
                    if i == self.config.llm.max_retries - 1:
                        logger.error(f"请求失败(重试耗尽): {e}")
                        raise
                    logger.warning(f"请求失败，{i+1}秒后重试: {e}")
                    time.sleep(1)
            else:
                continue
            
            if not self.protocol.has_tool_calls(result):
                response_text = self.protocol.parse_chat_response(result)
                logger.info(f"聊天完成: iterations={iteration + 1}, response_length={len(response_text)}")
                return response_text
            
            assistant_message = self.protocol.get_assistant_message_from_response(result)
            current_messages.append(assistant_message)
            
            tool_calls = self.protocol.parse_tool_calls(result)
            
            logger.info(f"迭代 {iteration + 1}: 检测到 {len(tool_calls)} 个工具调用")
            
            for tool_call in tool_calls:
                logger.info(f"工具调用: {tool_call.name}, 参数: {json.dumps(tool_call.arguments, ensure_ascii=False)[:100]}...")
                
                if self._tool_registry.has_tool(tool_call.name):
                    try:
                        tool_result = self.execute_builtin_tool(tool_call.name, tool_call.arguments)
                        is_error = False
                        logger.info(f"工具 {tool_call.name} 执行成功, 结果长度: {len(tool_result)}")
                    except Exception as e:
                        tool_result = str(e)
                        is_error = True
                        logger.error(f"工具 {tool_call.name} 执行失败: {e}")
                elif self._tool_executor:
                    try:
                        tool_result = self._tool_executor(tool_call.name, tool_call.arguments)
                        is_error = False
                        logger.info(f"工具 {tool_call.name} 执行成功(外部执行器)")
                    except Exception as e:
                        tool_result = str(e)
                        is_error = True
                        logger.error(f"工具 {tool_call.name} 执行失败(外部执行器): {e}")
                else:
                    tool_result = f"Error: No tool executor configured for {tool_call.name}"
                    is_error = True
                    logger.error(f"没有找到工具 {tool_call.name} 的执行器")
                
                tool_message = self.protocol.build_tool_result_message(
                    tool_call, 
                    tool_result, 
                    is_error
                )
                current_messages.append(tool_message)
        
        logger.warning(f"达到最大迭代次数 {max_iterations}")
        return self.protocol.parse_chat_response(result)
    
    def generate(self, prompt: str, **kwargs) -> str:
        url = self.protocol.get_generate_url()
        headers = self.protocol.get_headers()
        data = self.protocol.build_generate_request(prompt, **kwargs)
        
        logger.info(f"发送生成请求: prompt_length={len(prompt)}")
        
        for i in range(self.config.llm.max_retries):
            try:
                response = self.session.post(url, json=data, headers=headers)
                response.raise_for_status()
                result = response.json()
                response_text = self.protocol.parse_generate_response(result)
                logger.info(f"生成响应: length={len(response_text)}")
                return response_text
            except requests.RequestException as e:
                if i == self.config.llm.max_retries - 1:
                    error_msg = str(e)
                    if hasattr(e, 'response') and e.response is not None:
                        try:
                            error_detail = e.response.json()
                            error_msg = f"{error_msg}\n详情: {error_detail}"
                        except:
                            error_msg = f"{error_msg}\n响应内容: {e.response.text}"
                    logger.error(f"生成请求失败: {error_msg}")
                    raise Exception(f"API 请求失败: {error_msg}")
                logger.warning(f"请求失败，{i+1}秒后重试: {e}")
                time.sleep(1)
        
        return ""
