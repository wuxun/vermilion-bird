"""Task Delegator Skill - 子Agent任务分配能力"""

import logging
from typing import Dict, Any, List

from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool
from llm_chat.skills.task_delegator.tools import (
    SpawnSubagentTool,
    GetSubagentStatusTool,
    CancelSubagentTool,
    ListSubagentsTool,
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
            max_workers=8,  # default, overridable via config
        )
        self._parent_context = None
        self._config = None

    def get_tools(self) -> List[BaseTool]:
        if self._config is None:
            return []
        return [
            SpawnSubagentTool(
                registry=self._registry,
                parent_context=self._parent_context,
                config=self._config,
            ),
            GetSubagentStatusTool(registry=self._registry),
            CancelSubagentTool(registry=self._registry),
            ListSubagentsTool(registry=self._registry),
        ]

    def on_load(self, config: Dict[str, Any]) -> None:
        import llm_chat.config as config_module

        self._config = config_module.config

        if config and "work_dir" in config:
            self._config.tools.work_dir = config["work_dir"]

        self.logger.info(f"TaskDelegatorSkill loaded with config: {config}")
