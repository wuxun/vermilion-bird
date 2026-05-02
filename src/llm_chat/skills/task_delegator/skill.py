"""Task Delegator Skill - 子Agent任务分配能力"""

import logging
from typing import Dict, Any, List, Optional

from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool
from llm_chat.skills.task_delegator.tools import (
    SpawnSubagentTool,
    GetSubagentStatusTool,
    CancelSubagentTool,
    ListSubagentsTool,
    ExecuteWorkflowTool,
    GetWorkflowStatusTool,
)
from llm_chat.skills.task_delegator.registry import SubAgentRegistry

logger = logging.getLogger(__name__)


class TaskDelegatorSkill(BaseSkill):
    """子agent任务分配能力"""

    @property
    def name(self) -> str:
        return "task_delegator"

    @property
    def description(self) -> str:
        return "子agent任务分配能力，支持创建子agent分配任务、查询状态、取消任务。子agent拥有独立的上下文和工具白名单，且不能再创建子agent以防止递归。"

    @property
    def version(self) -> str:
        return "1.0.0"

    def __init__(self):
        self._registry = SubAgentRegistry(
            max_workers=8,
        )
        self._parent_context = None
        self._config = None
        self._spawn_tool: Optional[SpawnSubagentTool] = None
        self._workflow_executor = None
        self._executor_ref: Dict[str, Any] = {}

    def _init_root_context(self):
        """创建根上下文，让直接 spawn 的 agent 有可追溯的 parent_id。"""
        from llm_chat.skills.task_delegator.context import make_agent_context

        self._parent_context = make_agent_context(
            agent_id="main",
            parent_id=None,
            depth=-1,  # 根节点，直接子 agent depth = 0
            allowed_tools=set(),
            conversation_id="main",
            task="主对话",
        )

    def get_tools(self) -> List[BaseTool]:
        if self._config is None:
            return []

        if self._parent_context is None:
            self._init_root_context()

        spawn = SpawnSubagentTool(
            registry=self._registry,
            parent_context=self._parent_context,
            config=self._config,
        )
        self._spawn_tool = spawn  # keep ref for workflow executor

        tools: List[BaseTool] = [
            spawn,
            GetSubagentStatusTool(registry=self._registry),
            CancelSubagentTool(registry=self._registry),
            ListSubagentsTool(registry=self._registry),
            ExecuteWorkflowTool(
                registry=self._registry,
                spawn_tool=spawn,
                executor_ref=self._executor_ref,
            ),
            GetWorkflowStatusTool(executor_ref=self._executor_ref),
        ]

        # Wire up workflow executor (shared between execute & status tools)
        from llm_chat.skills.task_delegator.workflow import WorkflowExecutor
        self._workflow_executor = WorkflowExecutor(self._registry, spawn)
        self._executor_ref["executor"] = self._workflow_executor

        return tools

    def on_load(self, config: Dict[str, Any]) -> None:
        import llm_chat.config as config_module

        self._config = config_module.config

        if config and "work_dir" in config:
            self._config.tools.work_dir = config["work_dir"]

        self.logger.info(f"TaskDelegatorSkill loaded with config: {config}")

    def on_unload(self) -> None:
        """卸载时清理线程池，防止资源泄露。"""
        if self._registry is not None:
            self._registry.shutdown(wait=False)
        self.logger.info("TaskDelegatorSkill unloaded")
