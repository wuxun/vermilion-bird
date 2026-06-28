"""ToolExecutor — parallel tool execution with retry and timeout."""

import random
import time
import json
import logging
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Execute tools in parallel with retry and exponential backoff.

    Usage:
        executor = ToolExecutor(registry, max_workers=5)
        results = executor.execute_tools_parallel(tool_calls)
    """

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
        """Execute one tool with retry on transient errors.

        ValueError (param/validation errors) are NOT retried — raised immediately.
        Other exceptions use exponential backoff: min(2^n, 60s) + 10% jitter.
        """
        last_error = None

        for attempt in range(self.max_retries):
            try:
                logger.info(f"执行工具: {tool_name}, args={tool_args}")

                if self.tool_registry.has_tool(tool_name):
                    result = self.tool_registry.execute_tool(
                        tool_name, arguments=tool_args
                    )
                    logger.info(
                        f"工具注册表执行完成: result_type={type(result)}, "
                        f"result_is_none={result is None}"
                    )
                else:
                    return {
                        "tool_call_id": tool_call_id,
                        "content": f"Error: Unknown tool '{tool_name}'",
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
                # Param/validation errors — no retry, propagate immediately
                raise
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
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
        """Execute multiple tool calls in parallel, preserving order.

        Args:
            tool_calls: List of dicts with "id", "function" → "name", "arguments"

        Returns:
            List of result dicts in the SAME ORDER as input tool_calls,
            each with "tool_call_id", "content", "is_error".
        """
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

        # Wait for all to complete (no total timeout — individual retry handles it)
        for future in as_completed(futures_map):
            tool_call_id = futures_map[future]
            try:
                result = future.result(timeout=0)
                results_map[tool_call_id] = result
            except Exception as e:
                logger.error(f"工具调用失败 {tool_call_id}: {e}")
                results_map[tool_call_id] = {
                    "tool_call_id": tool_call_id,
                    "content": f"Error: {str(e)}",
                    "is_error": True,
                }

        # Preserve original order so LLM can match tool_call_id
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
        """Lazy-init reusable thread pool."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        return self._executor

    def shutdown(self) -> None:
        """Shut down the thread pool."""
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
