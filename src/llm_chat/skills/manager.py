import importlib
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Type

from .base import BaseSkill
from llm_chat.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class SkillManager:
    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        self._tool_registry = tool_registry or ToolRegistry()
        self._skills: Dict[str, BaseSkill] = {}
        self._skill_configs: Dict[str, Dict[str, Any]] = {}
        self._skill_classes: Dict[str, Type[BaseSkill]] = {}
        self._loaded_order: List[str] = []
    
    def register_skill_class(self, skill_class: Type[BaseSkill]) -> None:
        skill_name = skill_class().name
        self._skill_classes[skill_name] = skill_class
        logger.info(f"Registered skill class: {skill_name}")
    
    def discover_skills(self, skill_dirs: List[str]) -> List[Type[BaseSkill]]:
        discovered = []
        
        for skill_dir in skill_dirs:
            skill_path = Path(skill_dir).expanduser().resolve()
            if not skill_path.exists():
                logger.debug(f"Skill directory not found: {skill_path}")
                continue
            
            for item in skill_path.iterdir():
                if item.is_dir() and not item.name.startswith("_"):
                    skill_module_path = item / "skill.py"
                    if skill_module_path.exists():
                        try:
                            skill_class = self._load_skill_from_path(item)
                            if skill_class:
                                discovered.append(skill_class)
                                self.register_skill_class(skill_class)
                        except Exception as e:
                            logger.error(f"Failed to load skill from {item}: {e}")
        
        logger.info(f"Discovered {len(discovered)} skills")
        return discovered
    
    def _load_skill_from_path(self, skill_path: Path) -> Optional[Type[BaseSkill]]:
        module_name = f"skill_{skill_path.name}"
        
        if str(skill_path.parent) not in sys.path:
            sys.path.insert(0, str(skill_path.parent))
        
        try:
            if module_name in sys.modules:
                del sys.modules[module_name]
            
            spec = importlib.util.spec_from_file_location(module_name, skill_path / "skill.py")
            if spec is None or spec.loader is None:
                return None
            
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseSkill)
                    and attr is not BaseSkill
                ):
                    return attr
            
            return None
        except Exception as e:
            logger.error(f"Error loading skill from {skill_path}: {e}")
            return None
    
    def load_skill(
        self, 
        skill_name: str, 
        config: Optional[Dict[str, Any]] = None
    ) -> bool:
        if skill_name in self._skills:
            logger.warning(f"Skill '{skill_name}' is already loaded")
            return True
        
        skill_class = self._skill_classes.get(skill_name)
        if skill_class is None:
            logger.error(f"Skill class not found: {skill_name}")
            return False
        
        try:
            skill_instance = skill_class()
            
            for dep in skill_instance.dependencies:
                if dep not in self._skills:
                    logger.error(
                        f"Skill '{skill_name}' depends on '{dep}' which is not loaded"
                    )
                    return False
            
            skill_config = config or {}
            self._skill_configs[skill_name] = skill_config
            
            skill_instance.on_load(skill_config)
            
            tools = skill_instance.get_tools()
            for tool in tools:
                self._tool_registry.register(tool)
                logger.info(f"Registered tool '{tool.name}' from skill '{skill_name}'")
            
            self._skills[skill_name] = skill_instance
            self._loaded_order.append(skill_name)
            
            logger.info(f"Skill '{skill_name}' loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load skill '{skill_name}': {e}")
            return False
    
    def unload_skill(self, name: str) -> bool:
        if name not in self._skills:
            logger.warning(f"Skill '{name}' is not loaded")
            return False
        
        try:
            skill = self._skills[name]
            
            tools = skill.get_tools()
            for tool in tools:
                self._tool_registry.unregister(tool.name)
                logger.info(f"Unregistered tool '{tool.name}' from skill '{name}'")
            
            skill.on_unload()
            
            del self._skills[name]
            self._loaded_order.remove(name)
            if name in self._skill_configs:
                del self._skill_configs[name]
            
            logger.info(f"Skill '{name}' unloaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to unload skill '{name}': {e}")
            return False
    
    def reload_skill(self, name: str, config: Optional[Dict[str, Any]] = None) -> bool:
        self.unload_skill(name)
        return self.load_skill(name, config)
    
    def get_skill(self, name: str) -> Optional[BaseSkill]:
        return self._skills.get(name)
    
    def get_skill_config(self, name: str) -> Optional[Dict[str, Any]]:
        return self._skill_configs.get(name)
    
    def list_skills(self) -> List[BaseSkill]:
        return [self._skills[name] for name in self._loaded_order]
    
    def list_skill_names(self) -> List[str]:
        return list(self._loaded_order)
    
    def get_available_skill_classes(self) -> Dict[str, Type[BaseSkill]]:
        return self._skill_classes.copy()
    
    def load_from_config(self, skills_config: Dict[str, Dict[str, Any]]) -> None:
        for skill_name, skill_config in skills_config.items():
            if skill_config.get("enabled", True):
                config = {k: v for k, v in skill_config.items() if k != "enabled"}
                self.load_skill(skill_name, config)
    
    def unload_all(self) -> None:
        for name in reversed(self._loaded_order):
            self.unload_skill(name)
    
    def get_tool_registry(self) -> ToolRegistry:
        return self._tool_registry
