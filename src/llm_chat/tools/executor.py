import random
import time
import json
import logging
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class ToolExecutor:
    def __init__(
        self,
        tool_registry,
        max_workers: int = 5,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        timeout: int = 30,
    ):
        self.tool_registry = tool_registry
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        self._executor: Optional[ThreadPoolExecutor] = None

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
                else:
                    return {
                        "tool_call_id": tool_call_id,
                        "content": f"Error: Unknown tool '{tool_name}' - not in ToolRegistry",
                        "is_error": True,
                    }

                if result is None:
                    result = "工具执行返回空结果"
                    logger.warning(f"工具 {tool_name} 返回 None")
                else:
                    logger.info(f"工具 {tool_name} 执行成功, 结果长度: {len(result)}")

                return {
                    "tool_call_id": tool_call_id,
                    "content": result,
                    "is_error": False,
                }

            except ValueError:
                # 参数校验 / 业务逻辑错误 — 不重试，立即返回
                raise
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    # 指数退避 + 抖动: base=retry_delay, cap=60s
                    delay = min(self.retry_delay * (2 ** attempt), 60)
                    jitter = delay * 0.1 * random.random()
                    total_delay = delay + jitter
                    logger.warning(
                        f"工具 {tool_name} 执行失败，{total_delay:.1f}秒后重试 "
                        f"({attempt + 1}/{self.max_retries}): {e}"
                    )
                    time.sleep(total_delay)

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
        # 按 tool_call 原始顺序收集（非完成顺序）以便 LLM 正确匹配
        results_map: Dict[str, Dict] = {}

        executor = self._get_executor()
        futures_map: Dict[Any, str] = {}

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
            futures_map[future] = tool_call_id

        # 使用无总超时的 as_completed：每个工具的 execute_single_tool
        # 内部已有重试和超时控制，外层不应再加总超时限制。
        # 之前 timeout=self.timeout*len(tool_calls) 可能导致
        # spawn_subagent(wait=true) 等长时间阻塞工具被截断。
        # 注意：executor 在此不复用，由 _get_executor() 懒加载管理生命周期。
        for future in as_completed(futures_map):
            tool_call_id = futures_map[future]
            try:
                result = future.result(timeout=0)  # 0 = 不等待，已完成才取
                results_map[tool_call_id] = result
            except Exception as e:
                logger.error(f"工具调用失败 {tool_call_id}: {e}")
                results_map[tool_call_id] = {
                    "tool_call_id": tool_call_id,
                    "content": f"Error: {str(e)}",
                    "is_error": True,
                }

        # 按原始 tool_calls 顺序返回，确保 LLM 能正确匹配 tool_call_id
        for tool_call in tool_calls:
            tc_id = tool_call["id"]
            if tc_id in results_map:
                results.append(results_map[tc_id])
            else:
                results.append({
                    "tool_call_id": tc_id,
                    "content": "Error: Tool execution lost (unknown error)",
                    "is_error": True,
                })

        return results

    def _get_executor(self) -> ThreadPoolExecutor:
        """懒加载复用线程池，避免每次并行调用都创建/销毁线程。"""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        return self._executor

    def shutdown(self):
        """关闭线程池，释放资源。"""
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
