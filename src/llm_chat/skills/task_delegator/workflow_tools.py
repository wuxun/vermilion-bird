"""工作流编排工具 — execute_workflow + get_workflow_status。

将工作流编排相关工具从 tools.py 拆出，降低单文件复杂度。
"""

import json
import time
import logging
from typing import Dict, Any, Optional, List, TYPE_CHECKING

from llm_chat.tools.base import BaseTool
from llm_chat.utils.observability import observe

if TYPE_CHECKING:
    from llm_chat.skills.task_delegator.registry import SubAgentRegistry
    from llm_chat.skills.task_delegator.tools import SpawnSubagentTool

logger = logging.getLogger(__name__)


class ExecuteWorkflowTool(BaseTool):
    """执行预定义的工作流模板。

    支持 simple / parallel / pipeline 三种模式。
    提交后立即返回 workflow_id，工作流在后台执行。
    结果通过 GetWorkflowStatusTool 获取。
    """

    # 防重入：跟踪活跃的工作流 ID
    _active_workflow_id: Optional[str] = None
    _active_workflow_at: float = 0.0

    def __init__(
        self,
        registry: Optional["SubAgentRegistry"] = None,
        spawn_tool: Optional["SpawnSubagentTool"] = None,
        executor_ref: Optional[Dict[str, Any]] = None,
    ):
        from llm_chat.skills.task_delegator.registry import SubAgentRegistry
        self.registry = registry or SubAgentRegistry()
        self._spawn_tool = spawn_tool
        self._executor_ref = executor_ref if executor_ref is not None else {}
        self.config = None  # set by skill

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
                            "complexity": {
                                "type": "string",
                                "enum": ["simple", "moderate", "complex"],
                                "description": "任务复杂度（自动选模型）",
                            },
                        },
                        "required": ["task"],
                    },
                    "description": "任务列表",
                },
            },
            "required": ["name", "mode", "tasks"],
        }

    @observe("execute_workflow")
    def execute(self, **kwargs) -> str:
        from llm_chat.skills.task_delegator.workflow import AgentWorkflow

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
        # 将 complexity 转为 model_config（如果配置了 subagent_models）
        models_map = getattr(
            getattr(self, 'config', None), 'tools', None
        )
        models_map = models_map.subagent_models if models_map else {}
        for t in tasks:
            if t.get("complexity") and not t.get("model_config") and models_map:
                mapped = models_map.get(t["complexity"])
                if mapped:
                    t["model_config"] = {"model": mapped}
                    logger.info(
                        f"Workflow task complexity={t['complexity']} → model={mapped}"
                    )

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
        _bg_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="wf-submit"
        )
        try:
            bg_future = _bg_pool.submit(executor.execute, workflow)
            workflow_id = workflow.workflow_id  # 预先生成的 ID

            # 标记活跃工作流（防重入）
            ExecuteWorkflowTool._active_workflow_id = workflow_id
            ExecuteWorkflowTool._active_workflow_at = time.time()

            # 轮询等待工作流完成（由 config.tools.workflow_poll_timeout 控制）
            poll_timeout = getattr(
                getattr(self, 'config', None), 'tools', None
            )
            poll_timeout = poll_timeout.workflow_poll_timeout if poll_timeout else 240
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
                    "description": "是否阻塞等待工作流完成后返回。默认 false",
                    "default": False,
                },
            },
            "required": ["workflow_id"],
        }

    @observe("get_workflow_status")
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
                time.sleep(poll_interval)
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
