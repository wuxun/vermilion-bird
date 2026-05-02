import time
import json
import logging
from typing import Dict, Any, List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

logger = logging.getLogger(__name__)


class ToolExecutor:
    def __init__(
        self,
        tool_registry,
        tool_executor: Optional[Callable] = None,
        max_workers: int = 5,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        timeout: int = 30,
    ):
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout

    def execute_single_tool(
        self, tool_name: str, tool_args: Dict[str, Any], tool_call_id: str
    ) -> Dict[str, Any]:
        last_error = None

        for attempt in range(self.max_retries):
            try:
                logger.info(f"执行工具: {tool_name}, args={tool_args}")

                if self.tool_registry.has_tool(tool_name):
                    result = self.tool_registry.execute_tool(
                        tool_name, arguments=tool_args
                    )
                    logger.info(
                        f"工具注册表执行完成: result_type={type(result)}, result_is_none={result is None}"
                    )
                elif self.tool_executor:
                    result = self.tool_executor(tool_name, tool_args)
                    logger.info(
                        f"外部执行器执行完成: result_type={type(result)}, result_is_none={result is None}"
                    )
                else:
                    return {
                        "tool_call_id": tool_call_id,
                        "content": f"Error: No tool executor for {tool_name}",
                        "is_error": True,
                    }

                if result is None:
                    result = "工具执行返回空结果"
                    logger.warning(f"工具 {tool_name} 返回 None")
                else:
                    logger.info(f"工具 {tool_name} 执行成功, 结果长度: {len(result)}")

                return_dict = {
                    "tool_call_id": tool_call_id,
                    "content": result,
                    "is_error": False,
                }
                logger.info(
                    f"返回结果字典: tool_call_id={tool_call_id}, content_type={type(result)}, content_len={len(result) if result else 0}"
                )
                return return_dict

            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    logger.warning(
                        f"工具 {tool_name} 执行失败，{self.retry_delay}秒后重试 "
                        f"({attempt + 1}/{self.max_retries}): {e}"
                    )
                    time.sleep(self.retry_delay)

        logger.error(f"工具 {tool_name} 执行失败，重试耗尽: {last_error}")
        return {
            "tool_call_id": tool_call_id,
            "content": f"Error: {str(last_error)}",
            "is_error": True,
        }

    def execute_tools_parallel(
        self, tool_calls: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if not tool_calls:
            return []

        if len(tool_calls) == 1:
            tool_call = tool_calls[0]
            tool_name = tool_call["function"]["name"]
            try:
                tool_args = json.loads(tool_call["function"]["arguments"])
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.error(f"Failed to parse tool call arguments for {tool_name}: {e}")
                return [{
                    "tool_call_id": tool_call.get("id", "unknown"),
                    "content": f"Error: invalid tool arguments - {e}",
                    "is_error": True,
                }]
            return [self.execute_single_tool(tool_name, tool_args, tool_call["id"])]

        logger.info(f"并行执行 {len(tool_calls)} 个工具调用")

        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}

            for tool_call in tool_calls:
                tool_name = tool_call["function"]["name"]
                try:
                    tool_args = json.loads(tool_call["function"]["arguments"])
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.error(f"Failed to parse tool call arguments for {tool_name}: {e}")
                    results.append({
                        "tool_call_id": tool_call.get("id", "unknown"),
                        "content": f"Error: invalid tool arguments - {e}",
                        "is_error": True,
                    })
                    continue
                tool_call_id = tool_call["id"]

                future = executor.submit(
                    self.execute_single_tool, tool_name, tool_args, tool_call_id
                )
                futures[future] = tool_call

            for future in as_completed(futures, timeout=self.timeout * len(tool_calls)):
                tool_call = futures[future]
                try:
                    result = future.result(timeout=self.timeout)
                    results.append(result)
                except TimeoutError:
                    logger.error(f"工具 {tool_call['function']['name']} 执行超时")
                    results.append(
                        {
                            "tool_call_id": tool_call["id"],
                            "content": f"Error: Tool execution timeout after {self.timeout}s",
                            "is_error": True,
                        }
                    )
                except Exception as e:
                    logger.error(f"工具调用失败: {e}")
                    results.append(
                        {
                            "tool_call_id": tool_call["id"],
                            "content": f"Error: {str(e)}",
                            "is_error": True,
                        }
                    )

        return results
