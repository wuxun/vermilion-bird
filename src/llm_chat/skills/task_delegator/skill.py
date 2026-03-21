"""Task Delegator Skill - 子Agent任务分配能力"""

import logging
from typing import Dict, Any, List

from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool
from llm_chat.skills.task_delegator.tools import (
    SpawnSubagentTool,
    GetSubagentStatusTool,
    CancelSubagentTool,
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
        self._registry = SubAgentRegistry()
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
        ]

    def on_load(self, config: Dict[str, Any]) -> None:
        from llm_chat.config import Config

        if config is not None:
            self._config = Config(**config) if isinstance(config, dict) else config
        else:
            self._config = Config()
        self.logger.info(f"TaskDelegatorSkill loaded with config: {config}")
