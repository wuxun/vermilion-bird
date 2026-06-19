import importlib
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Type

from .base import BaseSkill
from .prompt_skill import PromptSkill
from llm_chat.tools.base import BaseTool
from llm_chat.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class SkillManager:
    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        self._tool_registry = tool_registry or ToolRegistry()
        self._skills: Dict[str, BaseSkill] = {}
        self._skill_configs: Dict[str, Dict[str, Any]] = {}
        self._skill_classes: Dict[str, Type[BaseSkill]] = {}
        self._loaded_order: List[str] = []

        # Prompt skills (Agent Skills 标准)
        self._prompt_skills: Dict[str, PromptSkill] = {}
        self._prompt_skill_dirs: List[str] = []
    
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
        # 使用路径 hash 作为模块名前缀，避免不同目录下同名 skill 冲突
        import hashlib
        path_hash = hashlib.md5(str(skill_path).encode()).hexdigest()[:8]
        module_name = f"skill_{path_hash}_{skill_path.name}"
        parent_dir = str(skill_path.parent)
        path_inserted = False

        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
            path_inserted = True

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
        finally:
            # 清理：还原 sys.path + sys.modules
            if path_inserted:
                try:
                    sys.path.remove(parent_dir)
                except ValueError:
                    pass
            sys.modules.pop(module_name, None)
    
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
            skill_instance.set_tool_registry(self._tool_registry)
            
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
    
    def get_all_skill_classes(self) -> Dict[str, Type[BaseSkill]]:
        """获取所有已注册的技能类"""
        return self._skill_classes.copy()
    
    def get_loaded_skills(self) -> Dict[str, BaseSkill]:
        """获取所有已加载的技能实例"""
        return self._skills.copy()
    
    def get_skill_class(self, name: str) -> Optional[Type[BaseSkill]]:
        """获取指定技能类"""
        return self._skill_classes.get(name)
    
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

    # --------------------------------------------------------------
    # Prompt Skill operations (Agent Skills 标准)
    # --------------------------------------------------------------

    def add_prompt_skill_dir(self, skill_dir: str) -> None:
        """添加 prompt skill 发现目录。"""
        if skill_dir not in self._prompt_skill_dirs:
            self._prompt_skill_dirs.append(skill_dir)

    def discover_prompt_skills(self, extra_dirs: Optional[List[str]] = None) -> List[PromptSkill]:
        """从所有已注册目录发现 prompt skills。"""
        all_dirs = list(self._prompt_skill_dirs)
        if extra_dirs:
            all_dirs.extend(extra_dirs)
        discovered = []
        for d in all_dirs:
            skills = PromptSkill.discover(Path(d).expanduser().resolve())
            for skill in skills:
                if skill.load():
                    self._prompt_skills[skill.name] = skill
                    discovered.append(skill)
        logger.info(
            f"Discovered {len(discovered)} prompt skills from {len(all_dirs)} dirs"
        )
        return discovered

    def get_prompt_skills(self) -> Dict[str, PromptSkill]:
        """获取所有已发现的 prompt skills。"""
        return self._prompt_skills.copy()

    def get_prompt_skills_summary(self) -> str:
        """返回所有 prompt skills 的一行摘要列表（向后兼容，含文件路径）。"""
        lines = []
        for skill in self._prompt_skills.values():
            summary = skill.get_summary()
            if summary:
                lines.append(summary)
        return "\n".join(lines)

    def get_prompt_skill(self, name: str) -> Optional[PromptSkill]:
        """按名称获取单个 prompt skill。"""
        return self._prompt_skills.get(name)

    def get_prompt_skills_for_context(self) -> str:
        """构建 prompt skills 的 system prompt 注入块。

        遵循 Agent Skills 标准 (agentskills.io) 的渐进式加载：

        - Tier 1 (Catalog): 所有 skill 以 XML 格式列出 name + description + location
        - Tier 2 (Instructions): LLM 自行用 read 工具加载 SKILL.md 全文
        - Tier 3 (Resources): scripts/references/assets 按需加载

        always 类型的 skill（vermilion-bird 扩展）同时注入全文，
        用于编码规范、品牌语调等每次对话都需要的技能。
        """
        # 分类
        always_skills = []
        catalog_skills = []
        for skill in self._prompt_skills.values():
            if skill.manifest and skill.manifest.type == "always":
                always_skills.append(skill)
            else:
                catalog_skills.append(skill)

        parts = []

        # always 类型：注入全文（vermilion-bird 非标准扩展）
        always_blocks = []
        for skill in always_skills:
            content = skill.get_content()
            if content:
                always_blocks.append(content)
        if always_blocks:
            parts.append("\n\n".join(always_blocks))

        # 构建 XML catalog（Agent Skills 标准格式）
        if catalog_skills or always_skills:
            xml_lines = []
            # 行为指令（Agent Skills 标准推荐措辞）
            xml_lines.append(
                "The following skills provide specialized instructions for specific tasks.\n"
                "When a task matches a skill's description, call the activate_skill tool\n"
                "with the skill's name to load its full instructions before proceeding."
            )
            xml_lines.append("<available_skills>")
            for skill in catalog_skills:
                xml_lines.append(f"  <skill>")
                xml_lines.append(f"    <name>{skill.name}</name>")
                xml_lines.append(f"    <description>{skill.description}</description>")
                xml_lines.append(f"    <location>{skill.location}</location>")
                xml_lines.append(f"  </skill>")
            # always 类型也列入 catalog（标记为 always）
            for skill in always_skills:
                xml_lines.append(f"  <skill>")
                xml_lines.append(f"    <name>{skill.name}</name>")
                xml_lines.append(f"    <description>{skill.description}</description>")
                xml_lines.append(f"    <location>{skill.location}</location>")
                xml_lines.append(f"    <note>Already injected above (always type)</note>")
                xml_lines.append(f"  </skill>")
            xml_lines.append("</available_skills>")
            parts.append("\n".join(xml_lines))

        return "\n\n".join(parts) if parts else ""

    def load_prompt_skill_by_name(self, name: str) -> Optional[str]:
        """按名称加载 prompt skill 全文。

        供 ShortcutStage 的 /skill:name 命令使用（用户显式激活路径）。
        模型自行激活时使用 activate_skill 工具。
        """
        skill = self._prompt_skills.get(name)
        if skill:
            return skill.get_content()
        return None

    def register_activate_skill_tool(self) -> None:
        """注册 activate_skill 工具，让 LLM 自行加载 prompt skill。

        在 disover_prompt_skills() 之后调用。
        仅在发现 prompt skill 时才注册此工具。

        工具名: activate_skill — 符合 Agent Skills 标准。
        工具接收 skill_name 参数，返回 SKILL.md 全文。
        """
        if not self._prompt_skills:
            return  # 无 prompt skill 时不注册

        # 检查是否已注册（避免重复）
        if self._tool_registry.has_tool("activate_skill"):
            return  # 已注册

        manager_ref = self  # 闭包引用

        class ActivateSkillTool(BaseTool):
            @property
            def name(self) -> str:
                return "activate_skill"

            @property
            def description(self) -> str:
                return (
                    "加载指定 Prompt Skill 的完整指令。"
                    "当任务匹配某个可用技能的描述时，调用此工具加载该技能的详细工作流。"
                )

            def get_parameters_schema(self) -> Dict[str, Any]:
                skill_names = sorted(manager_ref._prompt_skills.keys())
                return {
                    "type": "object",
                    "properties": {
                        "skill_name": {
                            "type": "string",
                            "description": "要加载的技能名称",
                            "enum": skill_names,
                        }
                    },
                    "required": ["skill_name"],
                }

            def execute(self, skill_name: str) -> str:
                content = manager_ref.load_prompt_skill_by_name(skill_name)
                if not content:
                    return f"错误: 技能 '{skill_name}' 未找到"
                skill = manager_ref._prompt_skills.get(skill_name)
                # 用结构化标签包裹，方便上下文管理
                location = skill.location if skill else ""
                lines = [
                    f'<skill_content name="{skill_name}">',
                    content,
                    "",
                    f"Skill directory: {location}",
                    "Relative paths in this skill are relative to the skill directory.",
                    "</skill_content>",
                ]
                return "\n".join(lines)

        tool = ActivateSkillTool()
        self._tool_registry.register(tool)
        logger.info(
            f"Registered activate_skill tool with "
            f"{len(self._prompt_skills)} skills"
        )
