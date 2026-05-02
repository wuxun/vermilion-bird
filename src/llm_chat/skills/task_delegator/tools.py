"""Task Delegator Tools - 子Agent任务分配工具 + 工作流编排工具"""

import os
import time
import uuid
import json
import logging
from typing import Dict, Any, Optional, List, TYPE_CHECKING

from llm_chat.tools.base import BaseTool
from llm_chat.skills.task_delegator.context import AgentContext, make_agent_context
from llm_chat.skills.task_delegator.registry import SubAgentRegistry

if TYPE_CHECKING:
    from llm_chat.config import Config
    from llm_chat.client import LLMClient

logger = logging.getLogger(__name__)


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
        return "创建子agent并分配任务。子agent拥有独立的上下文和工具白名单，且不能再创建子agent以防止递归。可以为子agent指定不同的大模型配置。"

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
                    "description": "是否阻塞等待子agent完成后再返回。默认false（异步）。设为true时直接返回执行结果，适用于单个子agent任务；设为false时立即返回agent_id，适用于并行多agent场景。",
                    "default": False,
                },
                "timeout": {
                    "type": "integer",
                    "description": "子agent超时时间（秒），默认60",
                    "default": 60,
                },
                "work_dir": {
                    "type": "string",
                    "description": "临时文件工作目录，默认使用配置中的 tools.work_dir",
                },
                "model_config": {
                    "type": "object",
                    "description": "子agent使用的大模型配置（可选）。不指定则使用默认配置。",
                    "properties": {
                        "model": {
                            "type": "string",
                            "description": "模型名称，如 gpt-4, claude-3-opus, gemini-pro",
                        },
                        "base_url": {
                            "type": "string",
                            "description": "API 基础 URL（可选，用于切换不同提供商）",
                        },
                        "api_key": {
                            "type": "string",
                            "description": "API 密钥（可选，不指定则使用默认密钥）",
                        },
                        "protocol": {
                            "type": "string",
                            "description": "协议类型：openai, anthropic, gemini（可选）",
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
        """获取工作目录，优先使用参数，其次使用配置"""
        if work_dir_arg:
            return work_dir_arg
        if self.config and hasattr(self.config, "tools") and self.config.tools:
            return self.config.tools.work_dir
        return ".vb/work"

    def execute(self, **kwargs) -> str:
        task = kwargs.get("task", "")
        allowed_tools = kwargs.get("allowed_tools", []) or []
        timeout = kwargs.get("timeout", 60)
        model_config = kwargs.get("model_config")
        work_dir_arg = kwargs.get("work_dir")

        # 递归防护：如果父上下文深度 >= 1，禁止创建子agent
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

        # 过滤工具白名单，移除 spawn_subagent 防止递归
        filtered_tools = [t for t in allowed_tools if t != "spawn_subagent"]

        # 获取工作目录并创建
        work_dir = self._get_work_dir(work_dir_arg)
        os.makedirs(work_dir, exist_ok=True)

        agent_id = str(uuid.uuid4())

        # 创建子agent上下文
        context = make_agent_context(
            agent_id=agent_id,
            parent_id=self.parent_context.agent_id if self.parent_context else None,
            depth=(self.parent_context.depth + 1) if self.parent_context else 0,
            allowed_tools=set(filtered_tools),
            conversation_id=f"conv_{uuid.uuid4()}",
            task=task,
            work_dir=work_dir,
        )

        # 注册子agent
        self.registry.spawn(agent_id, context)

        model_info = ""
        if model_config:
            model_info = f" (model: {model_config.get('model', 'default')})"
        logger.info(
            "Spawned subagent %s%s with task: %s",
            agent_id, model_info, task[:50]
        )

        # 提交到线程池
        future = self.registry.submit(
            agent_id,
            self._execute_async,
            agent_id, task, filtered_tools, timeout, context, model_config,
        )

        wait = kwargs.get("wait", False)
        if wait:
            # 同步模式：阻塞等待子agent完成
            try:
                result = future.result(timeout=timeout + 30)
                return json.dumps(
                    {
                        "agent_id": agent_id,
                        "status": "completed",
                        "result": result,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            except Exception as e:
                self.registry.cancel(agent_id)
                return json.dumps(
                    {
                        "agent_id": agent_id,
                        "status": "failed",
                        "error": str(e),
                    },
                    ensure_ascii=False,
                    indent=2,
                )

        # 异步模式：立即返回 agent_id
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

    def _execute_async(
        self,
        agent_id: str,
        task: str,
        allowed_tools: List[str],
        timeout: int,
        context: AgentContext,
        model_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """在后台线程中执行子agent任务。

        返回完整结果文本。异常会被 Future 的 done_callback 捕获。
        """
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

            # 记录模型/协议到 context
            context.model = subagent_config.llm.model
            context.protocol = subagent_config.llm.protocol

            # 通知 registry 模型/协议已确定 → GUI 面板刷新
            self.registry._notify_status_change(agent_id)

            # 工具调用 hook：实时记录到 context.tool_calls_log 并通知 GUI
            def _on_tool_call(tool_name: str, args: dict, result: str):
                context.tool_calls_log.append({
                    "tool": tool_name,
                    "args": _truncate_args(args),
                    "result": result[:300] + "..." if len(result) > 300 else result,
                    "ts": time.time(),
                })
                # 通知 GUI 刷新工具调用时间线
                self.registry._notify_status_change(agent_id)

            client = LLMClient(subagent_config, skip_skills_setup=True, tool_call_hook=_on_tool_call)

            # 自动合并 MCP 等外部工具到 allowed_tools
            # 主 LLM 可能不知道 MCP 工具名，子 agent 应自动获得全部可用工具
            if allowed_tools:
                all_tools = client.get_builtin_tools()
                all_names = {t.get("function", {}).get("name") for t in all_tools}
                _internal_tools = {
                    "spawn_subagent", "get_subagent_status", "cancel_subagent",
                    "list_subagents", "execute_workflow", "get_workflow_status",
                }
                # 合并：LLM 指定的白名单 + 所有非内部工具 (MCP 等)
                merged_allowed = set(allowed_tools) | (all_names - _internal_tools)
                if merged_allowed != set(allowed_tools):
                    extra = merged_allowed - set(allowed_tools)
                    logger.info(
                        f"Subagent {agent_id} auto-included external tools: {extra}"
                    )

                filtered_tool_defs = [
                    t
                    for t in all_tools
                    if t.get("function", {}).get("name") in merged_allowed
                ]

                if filtered_tool_defs:
                    logger.info(
                        f"Subagent {agent_id} calling LLM with {len(filtered_tool_defs)} tools"
                    )
                    result = client.chat_with_tools(task, filtered_tool_defs)
                else:
                    logger.info(
                        f"Subagent {agent_id} calling LLM without tools (none matched)"
                    )
                    result = client.chat(task)
            else:
                logger.info(f"Subagent {agent_id} calling LLM without tools")
                result = client.chat(task)

            # 检查是否在 LLM 调用期间被取消
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

            # cancelled 优先于 failed
            if context._cancelled.is_set():
                return "Cancelled"

            context.status = "failed"
            context.result = error_msg

            return error_msg

    def _create_subagent_config(self, model_config: Dict[str, Any]) -> "Config":
        """根据模型配置创建子agent配置"""
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

        subagent_config = Config(
            llm=llm_config,
            mcp=self.config.mcp,
            enable_tools=self.config.enable_tools,
            tools=self.config.tools,
            skills=self.config.skills,
            memory=self.config.memory,
            external_skill_dirs=self.config.external_skill_dirs,
        )

        return subagent_config


class GetSubagentStatusTool(BaseTool):
    """查询子agent状态的工具"""

    @property
    def name(self) -> str:
        return "get_subagent_status"

    @property
    def description(self) -> str:
        return "查询子agent的状态和结果。支持阻塞等待（wait=true）或即时查询（默认）。返回status, result, created_at等信息。"

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "要查询的子agent ID"},
                "wait": {
                    "type": "boolean",
                    "description": "是否阻塞等待子agent完成后再返回。默认false（立即返回当前状态）。用于并行多agent场景中逐个等待完成。",
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

    def execute(self, **kwargs) -> str:
        agent_id = kwargs.get("agent_id", "")

        context = self.registry.get(agent_id)
        if context is None:
            error_msg = f"Subagent not found: {agent_id}"
            logger.warning(error_msg)
            return error_msg

        # 如果请求等待且子agent仍在运行，阻塞等待完成
        wait = kwargs.get("wait", False)
        if wait and context.status == "running":
            wait_timeout = kwargs.get("wait_timeout", 60)
            waited_result = self.registry.wait_for(agent_id, timeout=wait_timeout)
            if waited_result is not None:
                context.result = waited_result
                context.status = "completed"
            elif context.status == "running":
                # wait_for 超时或出错，保持 running 状态
                pass

        result = {
            "agent_id": context.agent_id,
            "parent_id": context.parent_id,
            "depth": context.depth,
            "status": context.status,
            "created_at": context.created_at.isoformat(),
            "result": context.result,
            "work_dir": context.work_dir,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)


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
        return {
            "type": "object",
            "properties": {},
        }

    def __init__(self, registry: Optional[SubAgentRegistry] = None):
        self.registry = registry or SubAgentRegistry()

    def execute(self, **kwargs) -> str:
        agents = self.registry.list_all()
        if not agents:
            return json.dumps(
                {"agents": [], "message": "No sub-agents found"},
                ensure_ascii=False,
                indent=2,
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


class ExecuteWorkflowTool(BaseTool):
    """执行预定义的工作流模板。

    支持 simple / parallel / pipeline 三种模式。
    提交后立即返回 workflow_id，工作流在后台执行。
    结果通过 get_workflow_status 获取。
    """

    # 防重入：跟踪活跃的工作流 ID
    _active_workflow_id: Optional[str] = None
    _active_workflow_at: float = 0.0

    def __init__(
        self,
        registry: Optional[SubAgentRegistry] = None,
        spawn_tool: Optional[SpawnSubagentTool] = None,
        executor_ref: Optional[Dict[str, Any]] = None,
    ):
        self.registry = registry or SubAgentRegistry()
        self._spawn_tool = spawn_tool
        self._executor_ref = executor_ref if executor_ref is not None else {}

    @property
    def name(self) -> str:
        return "execute_workflow"

    @property
    def description(self) -> str:
        return (
            "提交一个 agent 工作流到后台执行，立即返回 workflow_id。\n"
            "提交后工作流在后台运行，不阻塞当前对话。\n"
            "支持三种模式：\n"
            "1. 'simple': 单个子 agent 执行单一任务\n"
            "2. 'parallel': 并行执行多个子 agent 处理独立子任务\n"
            "3. 'pipeline': 串行执行多个子 agent，前一个的输出传给下一个\n\n"
            "⚠️ 重要：返回后必须调用 get_workflow_status(workflow_id, wait=true) 获取结果。\n"
            "不要重复调用 execute_workflow，否则会创建重复的工作流！\n"
            "一次提交 = 一次执行，等待结果用 get_workflow_status。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "工作流名称"},
                "mode": {
                    "type": "string",
                    "enum": ["simple", "parallel", "pipeline"],
                    "description": "工作流模式",
                },
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task": {
                                "type": "string",
                                "description": "子任务描述",
                            },
                            "tools": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "允许的工具白名单",
                            },
                        },
                        "required": ["task"],
                    },
                    "description": "任务列表",
                },
            },
            "required": ["name", "mode", "tasks"],
        }

    def execute(self, **kwargs) -> str:
        from llm_chat.skills.task_delegator.workflow import (
            AgentWorkflow,
        )

        name = kwargs.get("name", "unnamed")
        mode = kwargs.get("mode", "simple")
        tasks = kwargs.get("tasks", [])

        # 提前获取 executor（防重入检查也需要）
        executor = self._executor_ref.get("executor")

        # 防重入：如果上一个工作流仍在活跃（10s 内），返回已有 ID
        if (
            ExecuteWorkflowTool._active_workflow_id
            and (time.time() - ExecuteWorkflowTool._active_workflow_at) < 10
        ):
            existing = ExecuteWorkflowTool._active_workflow_id
            existing_result = executor.get_result(existing) if executor else None
            if existing_result and existing_result.status == "running":
                logger.warning(
                    "execute_workflow called again while workflow '%s' is still running",
                    existing,
                )
                return json.dumps(
                    {
                        "workflow_id": existing,
                        "name": name,
                        "mode": mode,
                        "status": "already_submitted",
                        "message": (
                            f"⚠️ 工作流已在执行中 (id={existing})。"
                            f"请用 get_workflow_status(\"{existing}\", wait=true) 获取结果，"
                            f"不要重复提交！"
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )

        if not tasks:
            return json.dumps(
                {"error": "tasks must not be empty", "status": "failed"},
                ensure_ascii=False,
            )

        # 构建工作流
        workflow = AgentWorkflow.from_json({
            "name": name,
            "mode": mode,
            "tasks": tasks,
        })

        # 创建 executor（如果尚未存在）
        if executor is None:
            if self._spawn_tool is None:
                return json.dumps(
                    {
                        "error": "Workflow executor not configured: no spawn_tool available",
                        "status": "failed",
                    },
                    ensure_ascii=False,
                )
            from llm_chat.skills.task_delegator.workflow import WorkflowExecutor
            executor = WorkflowExecutor(self.registry, self._spawn_tool)
            self._executor_ref["executor"] = executor

        # 异步提交工作流到后台线程，避免长时间阻塞导致工具超时
        # 然后内部轮询等待完成，超时前返回 workflow_id 让 LLM 自行轮询
        import concurrent.futures
        _bg_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="wf-submit")
        try:
            bg_future = _bg_pool.submit(executor.execute, workflow)
            workflow_id = workflow.workflow_id  # 预先生成的 ID

            # 标记活跃工作流（防重入）
            ExecuteWorkflowTool._active_workflow_id = workflow_id
            ExecuteWorkflowTool._active_workflow_at = time.time()

            # 轮询等待工作流完成（由 config.tools.workflow_poll_timeout 控制）
            poll_timeout = self.config.tools.workflow_poll_timeout
            poll_interval = 3
            waited = 0
            while waited < poll_timeout:
                wf_result = executor.get_result(workflow_id)
                if wf_result and wf_result.status in ("completed", "partial", "failed", "cancelled"):
                    break
                try:
                    bg_future.result(timeout=poll_interval)
                    break
                except concurrent.futures.TimeoutError:
                    waited += poll_interval

            wf_result = executor.get_result(workflow_id)
        finally:
            _bg_pool.shutdown(wait=False)

        if wf_result and wf_result.status == "running":
            # 工作流仍在后台执行，返回 submitted 状态
            # 使用 "submitted" 而非 "running" 防止 LLM 误解为失败而重试
            # 活跃标记保持，用于防重入
            return json.dumps(
                {
                    "workflow_id": workflow_id,
                    "name": name,
                    "mode": mode,
                    "tasks_count": len(tasks),
                    "status": "submitted",
                    "message": (
                        f"✅ 工作流已提交，正在后台执行 ({len(tasks)} 个任务)。\n"
                        f"⚠️ 切勿重复调用 execute_workflow！\n"
                        f"请调用 get_workflow_status(workflow_id=\"{workflow_id}\", wait=true) 等待结果。"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )

        # 工作流已完成，清除防重入标记
        ExecuteWorkflowTool._active_workflow_id = None
        return json.dumps(
            {
                "workflow_id": workflow_id,
                "name": name,
                "mode": mode,
                "tasks_count": len(tasks),
                "status": wf_result.status if wf_result else "completed",
                "duration_seconds": round(wf_result.duration_seconds, 2) if wf_result else 0,
                "node_results": wf_result.node_results if wf_result else {},
                "error": wf_result.error if wf_result else None,
            },
            ensure_ascii=False,
            indent=2,
        )


class GetWorkflowStatusTool(BaseTool):
    """查询工作流状态的工具。"""

    def __init__(
        self,
        executor_ref: Optional[Dict[str, Any]] = None,
    ):
        # executor_ref is a mutable dict so the skill can inject the executor
        self._executor_ref = executor_ref if executor_ref is not None else {}

    @property
    def name(self) -> str:
        return "get_workflow_status"

    @property
    def description(self) -> str:
        return (
            "获取工作流的执行结果。execute_workflow 提交后，必须用此工具获取结果。\n"
            "使用 wait=true 会阻塞等待直到工作流完成（推荐）。"
            "工作流 ID 从 execute_workflow 的返回值中获取。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "要查询的工作流 ID",
                },
                "wait": {
                    "type": "boolean",
                    "description": "是否阻塞等待工作流完成后返回。默认 false（立即返回当前状态）",
                    "default": False,
                },
            },
            "required": ["workflow_id"],
        }

    def execute(self, **kwargs) -> str:
        workflow_id = kwargs.get("workflow_id", "")

        executor = self._executor_ref.get("executor")
        if executor is None:
            return json.dumps(
                {"error": "No workflow executor available", "status": "failed"},
                ensure_ascii=False,
            )

        # 如果请求等待，轮询直到完成
        wait = kwargs.get("wait", False)
        if wait:
            poll_timeout = 300
            poll_interval = 2
            waited = 0
            while waited < poll_timeout:
                result = executor.get_result(workflow_id)
                if result and result.status in ("completed", "partial", "failed", "cancelled"):
                    break
                import time as _time
                _time.sleep(poll_interval)
                waited += poll_interval

        result = executor.get_result(workflow_id)
        if result is None:
            return json.dumps(
                {
                    "error": f"Workflow not found: {workflow_id}",
                    "status": "not_found",
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "workflow_id": result.workflow_id,
                "name": result.name,
                "status": result.status,
                "duration_seconds": round(result.duration_seconds, 2),
                "node_results": result.node_results,
                "error": result.error,
            },
            ensure_ascii=False,
            indent=2,
        )
