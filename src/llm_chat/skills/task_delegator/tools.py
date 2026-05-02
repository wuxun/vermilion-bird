"""Task Delegator Tools - 子Agent任务分配工具 + 工作流编排工具"""

import os
import time
import uuid
import json
import logging
from typing import Dict, Any, Optional, List, TYPE_CHECKING

from llm_chat.tools.base import BaseTool
from llm_chat.utils.observability import observe

# Workflow tools (split to separate file for readability)
from llm_chat.skills.task_delegator.workflow_tools import (
    ExecuteWorkflowTool,
    GetWorkflowStatusTool,
)
from llm_chat.skills.task_delegator.context import AgentContext, make_agent_context
from llm_chat.skills.task_delegator.registry import SubAgentRegistry

if TYPE_CHECKING:
    from llm_chat.config import Config
    from llm_chat.client import LLMClient

logger = logging.getLogger(__name__)

__all__ = [
    "SpawnSubagentTool",
    "GetSubagentStatusTool",
    "CancelSubagentTool",
    "ListSubagentsTool",
    "ExecuteWorkflowTool",
    "GetWorkflowStatusTool",
]


def _truncate_args(args: dict, max_len: int = 200) -> str:
    """截断工具参数用于 GUI 展示。"""
    if not args:
        return "{}"
    s = json.dumps(args, ensure_ascii=False)
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."


class SpawnSubagentTool(BaseTool):
    """创建子agent并分配任务的工具"""

    @property
    def name(self) -> str:
        return "spawn_subagent"

    @property
    def description(self) -> str:
        return (
            "创建子agent并分配任务。子agent拥有独立的上下文和工具白名单，"
            "且不能再创建子agent以防止递归。可以为子agent指定不同的大模型配置。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "分配给子agent的任务描述"},
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "子agent可以使用的工具白名单",
                    "default": [],
                },
                "wait": {
                    "type": "boolean",
                    "description": (
                        "是否阻塞等待子agent完成后再返回。默认false（异步）。"
                        "true=直接返回执行结果，false=立即返回agent_id并后台执行。"
                    ),
                    "default": False,
                },
                "timeout": {
                    "type": "integer",
                    "description": "子agent超时时间（秒），默认60",
                    "default": 60,
                },
                "work_dir": {
                    "type": "string",
                    "description": "临时文件工作目录",
                },
                "model_config": {
                    "type": "object",
                    "description": "子agent使用的大模型配置（可选）",
                    "properties": {
                        "model": {"type": "string", "description": "模型名称"},
                        "base_url": {"type": "string", "description": "API基础URL"},
                        "api_key": {"type": "string", "description": "API密钥"},
                        "protocol": {
                            "type": "string",
                            "description": "协议类型",
                            "enum": ["openai", "anthropic", "gemini"],
                        },
                    },
                },
            },
            "required": ["task"],
        }

    def __init__(
        self,
        registry: Optional[SubAgentRegistry] = None,
        parent_context: Optional[AgentContext] = None,
        config: Optional["Config"] = None,
    ):
        self.registry = registry or SubAgentRegistry()
        self.parent_context = parent_context
        self.config = config

    def _get_work_dir(self, work_dir_arg: Optional[str] = None) -> str:
        if work_dir_arg:
            return work_dir_arg
        if self.config and hasattr(self.config, "tools") and self.config.tools:
            return self.config.tools.work_dir
        return ".vb/work"

    @observe("spawn_subagent")
    def execute(self, **kwargs) -> str:
        task = kwargs.get("task", "")
        allowed_tools = kwargs.get("allowed_tools", []) or []
        timeout = kwargs.get("timeout", 60)
        model_config = kwargs.get("model_config")
        work_dir_arg = kwargs.get("work_dir")

        if self.parent_context and self.parent_context.depth >= 1:
            error_msg = (
                f"Cannot spawn subagent: recursion not allowed. "
                f"Current depth: {self.parent_context.depth}"
            )
            logger.warning(error_msg)
            return json.dumps(
                {"error": error_msg, "status": "failed"},
                ensure_ascii=False,
                indent=2,
            )

        filtered_tools = [t for t in allowed_tools if t != "spawn_subagent"]
        work_dir = self._get_work_dir(work_dir_arg)
        os.makedirs(work_dir, exist_ok=True)

        agent_id = str(uuid.uuid4())

        context = make_agent_context(
            agent_id=agent_id,
            parent_id=self.parent_context.agent_id if self.parent_context else None,
            depth=(self.parent_context.depth + 1) if self.parent_context else 0,
            allowed_tools=set(filtered_tools),
            conversation_id=f"conv_{uuid.uuid4()}",
            task=task,
            work_dir=work_dir,
        )

        self.registry.spawn(agent_id, context)

        model_info = ""
        if model_config:
            model_info = f" (model: {model_config.get('model', 'default')})"
        logger.info(
            "Spawned subagent %s%s with task: %s",
            agent_id, model_info, task[:50]
        )

        future = self.registry.submit(
            agent_id,
            self._execute_async,
            agent_id, task, filtered_tools, timeout, context, model_config,
        )

        wait = kwargs.get("wait", False)
        if wait:
            try:
                result = future.result(timeout=timeout + 30)
                return json.dumps(
                    {"agent_id": agent_id, "status": "completed", "result": result},
                    ensure_ascii=False, indent=2,
                )
            except Exception as e:
                self.registry.cancel(agent_id)
                return json.dumps(
                    {"agent_id": agent_id, "status": "failed", "error": str(e)},
                    ensure_ascii=False, indent=2,
                )

        return json.dumps(
            {
                "agent_id": agent_id,
                "status": "spawned",
                "message": (
                    f"子agent已创建并在后台执行中。"
                    f"使用 get_subagent_status(\"{agent_id}\") 查询进度和结果。"
                    f"也可以使用 cancel_subagent(\"{agent_id}\") 取消任务。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    @observe("task_delegator._execute_async")
    def _execute_async(
        self,
        agent_id: str,
        task: str,
        allowed_tools: List[str],
        timeout: int,
        context: AgentContext,
        model_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """在后台线程中执行子agent任务（含重试 + 资源清理）。"""
        client = None
        try:
            from llm_chat.client import LLMClient

            if model_config:
                subagent_config = self._create_subagent_config(model_config)
                logger.info(
                    f"Subagent {agent_id} using custom model: "
                    f"model={subagent_config.llm.model}, "
                    f"protocol={subagent_config.llm.protocol}, "
                    f"base_url={subagent_config.llm.base_url}"
                )
            else:
                subagent_config = self.config
                logger.info(f"Subagent {agent_id} using default config")

            context.model = subagent_config.llm.model
            context.protocol = subagent_config.llm.protocol
            self.registry._notify_status_change(agent_id)

            def _on_tool_call(tool_name: str, args: dict, result: str):
                context.tool_calls_log.append({
                    "tool": tool_name,
                    "args": _truncate_args(args),
                    "result": result[:300] + "..." if len(result) > 300 else result,
                    "ts": time.time(),
                })
                self.registry._notify_status_change(agent_id)

            client = LLMClient(
                subagent_config, skip_skills_setup=True, tool_call_hook=_on_tool_call
            )

            if allowed_tools:
                all_tools = client.get_builtin_tools()
                all_names = {t.get("function", {}).get("name") for t in all_tools}
                _internal_tools = {
                    "spawn_subagent", "get_subagent_status", "cancel_subagent",
                    "list_subagents", "execute_workflow", "get_workflow_status",
                }
                merged_allowed = set(allowed_tools) | (all_names - _internal_tools)
                if merged_allowed != set(allowed_tools):
                    extra = merged_allowed - set(allowed_tools)
                    logger.info(
                        f"Subagent {agent_id} auto-included external tools: {extra}"
                    )

                filtered_tool_defs = [
                    t for t in all_tools
                    if t.get("function", {}).get("name") in merged_allowed
                ]
                result = self._call_llm_with_retry(
                    client, agent_id, task, filtered_tool_defs, context
                )
            else:
                logger.info(f"Subagent {agent_id} calling LLM without tools")
                result = self._call_llm_with_retry(
                    client, agent_id, task, None, context
                )

            if context._cancelled.is_set():
                logger.info(f"Subagent {agent_id} was cancelled during execution")
                return "Cancelled"

            context.status = "completed"
            context.result = result
            logger.info(f"Subagent {agent_id} completed successfully")
            return result

        except Exception as e:
            error_msg = f"Subagent {agent_id} failed: {str(e)}"
            logger.error(f"Subagent {agent_id} execution error: {e}", exc_info=True)
            if context._cancelled.is_set():
                return "Cancelled"
            context.status = "failed"
            context.result = error_msg
            return error_msg
        finally:
            if client is not None:
                client.close()

    def _call_llm_with_retry(
        self,
        client,
        agent_id: str,
        task: str,
        tool_defs: Optional[List[Dict[str, Any]]],
        context: "AgentContext",
    ) -> str:
        """带指数退避重试的 LLM 调用。仅对网络/超时错误重试。"""
        tools_cfg = getattr(self.config, 'tools', None)
        max_retries = tools_cfg.subagent_max_retries if tools_cfg else 2
        retry_delay = tools_cfg.subagent_retry_delay if tools_cfg else 2.0

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                if tool_defs:
                    logger.info(
                        f"Subagent {agent_id} calling LLM with {len(tool_defs)} tools "
                        f"(attempt {attempt + 1}/{max_retries + 1})"
                    )
                    return client.chat_with_tools(task, tool_defs)
                else:
                    logger.info(
                        f"Subagent {agent_id} calling LLM without tools "
                        f"(attempt {attempt + 1}/{max_retries + 1})"
                    )
                    return client.chat(task)
            except (ConnectionError, TimeoutError, OSError) as e:
                last_error = e
                if attempt >= max_retries:
                    raise
                delay = retry_delay * (2 ** attempt)
                logger.warning(
                    f"Subagent {agent_id} LLM call failed on attempt "
                    f"{attempt + 1}/{max_retries + 1}, "
                    f"retrying in {delay:.1f}s: {e}"
                )
                if context._cancelled.is_set():
                    raise RuntimeError("Cancelled during retry") from e
                try:
                    time.sleep(delay)
                except Exception:
                    pass

        raise last_error or RuntimeError(
            f"Subagent {agent_id}: unknown LLM call failure"
        )

    def _create_subagent_config(self, model_config: Dict[str, Any]) -> "Config":
        from llm_chat.config import Config, LLMConfig

        base_llm = self.config.llm

        llm_config = LLMConfig(
            model=model_config.get("model", base_llm.model),
            base_url=model_config.get("base_url", base_llm.base_url),
            api_key=model_config.get("api_key", base_llm.api_key),
            protocol=model_config.get("protocol", base_llm.protocol),
            timeout=base_llm.timeout,
            max_retries=base_llm.max_retries,
            http_proxy=base_llm.http_proxy,
            https_proxy=base_llm.https_proxy,
        )

        return Config(
            llm=llm_config,
            mcp=self.config.mcp,
            enable_tools=self.config.enable_tools,
            tools=self.config.tools,
            skills=self.config.skills,
            memory=self.config.memory,
            external_skill_dirs=self.config.external_skill_dirs,
        )


class GetSubagentStatusTool(BaseTool):
    """查询子agent状态的工具"""

    @property
    def name(self) -> str:
        return "get_subagent_status"

    @property
    def description(self) -> str:
        return (
            "查询子agent的状态和结果。支持阻塞等待（wait=true）或即时查询。"
            "返回status, result, created_at等信息。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "要查询的子agent ID"},
                "wait": {
                    "type": "boolean",
                    "description": "是否阻塞等待子agent完成。默认false",
                    "default": False,
                },
                "wait_timeout": {
                    "type": "integer",
                    "description": "wait=true时的等待超时秒数，默认60",
                    "default": 60,
                },
            },
            "required": ["agent_id"],
        }

    def __init__(self, registry: Optional[SubAgentRegistry] = None):
        self.registry = registry or SubAgentRegistry()

    @observe("get_subagent_status")
    def execute(self, **kwargs) -> str:
        agent_id = kwargs.get("agent_id", "")

        context = self.registry.get(agent_id)
        if context is None:
            error_msg = f"Subagent not found: {agent_id}"
            logger.warning(error_msg)
            return error_msg

        wait = kwargs.get("wait", False)
        if wait and context.status == "running":
            wait_timeout = kwargs.get("wait_timeout", 60)
            waited_result = self.registry.wait_for(agent_id, timeout=wait_timeout)
            if waited_result is not None:
                context.result = waited_result
                context.status = "completed"

        return json.dumps(
            {
                "agent_id": context.agent_id,
                "parent_id": context.parent_id,
                "depth": context.depth,
                "status": context.status,
                "created_at": context.created_at.isoformat(),
                "result": context.result,
                "work_dir": context.work_dir,
            },
            ensure_ascii=False,
            indent=2,
        )


class CancelSubagentTool(BaseTool):
    """取消子agent任务的工具"""

    @property
    def name(self) -> str:
        return "cancel_subagent"

    @property
    def description(self) -> str:
        return "取消正在运行的子agent任务。"

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "要取消的子agent ID"}
            },
            "required": ["agent_id"],
        }

    def __init__(self, registry: Optional[SubAgentRegistry] = None):
        self.registry = registry or SubAgentRegistry()

    def execute(self, **kwargs) -> str:
        agent_id = kwargs.get("agent_id", "")
        success = self.registry.cancel(agent_id)
        if success:
            result = {
                "cancelled": True,
                "agent_id": agent_id,
                "message": f"Subagent {agent_id} cancelled successfully",
            }
            logger.info(f"Cancelled subagent {agent_id}")
        else:
            result = {
                "cancelled": False,
                "agent_id": agent_id,
                "message": f"Subagent not found: {agent_id}",
            }
            logger.warning(f"Failed to cancel subagent {agent_id}: not found")
        return json.dumps(result, ensure_ascii=False, indent=2)


class ListSubagentsTool(BaseTool):
    """列出所有子agent的工具"""

    @property
    def name(self) -> str:
        return "list_subagents"

    @property
    def description(self) -> str:
        return (
            "列出所有子agent及其状态。用于在异步模式下查看多个并行子agent的进度。"
            "每个子agent提供 agent_id, status, result 等信息。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    def __init__(self, registry: Optional[SubAgentRegistry] = None):
        self.registry = registry or SubAgentRegistry()

    def execute(self, **kwargs) -> str:
        agents = self.registry.list_all()
        if not agents:
            return json.dumps(
                {"agents": [], "message": "No sub-agents found"},
                ensure_ascii=False, indent=2,
            )

        active_count = sum(1 for a in agents if a["status"] == "running")
        complete_count = sum(1 for a in agents if a["status"] == "completed")
        failed_count = sum(1 for a in agents if a["status"] == "failed")

        return json.dumps(
            {
                "agents": agents,
                "summary": {
                    "total": len(agents),
                    "active": active_count,
                    "completed": complete_count,
                    "failed": failed_count,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
