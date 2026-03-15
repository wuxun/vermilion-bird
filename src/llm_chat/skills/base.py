import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from llm_chat.tools.base import BaseTool


class BaseSkill(ABC):
    _logger: logging.Logger = None
    
    @property
    def logger(self) -> logging.Logger:
        if self._logger is None:
            self._logger = logging.getLogger(f"skill.{self.name}")
        return self._logger
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        pass
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    @property
    def dependencies(self) -> List[str]:
        return []
    
    @abstractmethod
    def get_tools(self) -> List["BaseTool"]:
        pass
    
    def on_load(self, config: Dict[str, Any]) -> None:
        self.logger.info(f"Skill '{self.name}' loaded with config: {config}")
    
    def on_unload(self) -> None:
        self.logger.info(f"Skill '{self.name}' unloaded")
    
    def __repr__(self) -> str:
        return f"<Skill {self.name} v{self.version}>"
