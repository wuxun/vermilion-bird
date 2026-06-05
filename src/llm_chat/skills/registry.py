import logging
from typing import Dict, Type, List, Tuple

logger = logging.getLogger(__name__)

# 延迟注册表：存储 (module_path, class_name) 而非实际类
# 只有首次调用 get_builtin_skills() 时才真正导入
_SKILL_REGISTRY: Dict[str, Tuple[str, str]] = {
    "web_search":       ("llm_chat.skills.web_search.skill",      "WebSearchSkill"),
    "calculator":       ("llm_chat.skills.calculator.skill",       "CalculatorSkill"),
    "web_fetch":        ("llm_chat.skills.web_fetch.skill",        "WebFetchSkill"),
    "file_reader":      ("llm_chat.skills.file_reader.skill",      "FileReaderSkill"),
    "file_writer":      ("llm_chat.skills.file_writer.skill",      "FileWriterSkill"),
    "file_editor":      ("llm_chat.skills.file_editor.skill",      "FileEditorSkill"),
    "todo_manager":     ("llm_chat.skills.todo_manager.skill",     "TodoManagerSkill"),
    "task_delegator":   ("llm_chat.skills.task_delegator.skill",   "TaskDelegatorSkill"),
    "scheduler":        ("llm_chat.skills.scheduler.skill",        "SchedulerSkill"),
    "shell_exec":       ("llm_chat.skills.shell_exec.skill",       "ShellExecSkill"),
    "remember_fact":    ("llm_chat.skills.remember_fact.skill",    "RememberFactSkill"),
    "knowledge_base":   ("llm_chat.skills.knowledge_base.skill",   "KnowledgeBaseSkill"),
}

# 已导入的技能类缓存，首次调用 get_builtin_skills() 时填充
_BUILTIN_SKILLS: Dict[str, Type] = {}
_skills_loaded = False


def _load_all_skills():
    """一次性导入所有技能类（仅在首次调用时执行）。"""
    global _skills_loaded
    if _skills_loaded:
        return

    import importlib
    for name, (module_path, class_name) in _SKILL_REGISTRY.items():
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            _BUILTIN_SKILLS[name] = cls
        except Exception as e:
            logger.warning(f"技能 '{name}' 导入失败: {e}")

    _skills_loaded = True
    logger.debug(f"懒加载完成: {len(_BUILTIN_SKILLS)}/{len(_SKILL_REGISTRY)} 个技能")


def register_skill(name: str):
    """装饰器：注册技能类（用于自定义技能运行时注册）。"""
    def decorator(cls):
        _BUILTIN_SKILLS[name] = cls
        # 同步到 registry 映射（允许运行时覆盖）
        _SKILL_REGISTRY[name] = (cls.__module__, cls.__name__)
        return cls
    return decorator


def get_builtin_skills() -> Dict[str, Type]:
    """获取所有内置技能类。首次调用时触发懒加载。"""
    _load_all_skills()
    return _BUILTIN_SKILLS.copy()


def get_skill_class(name: str) -> Type:
    """按名称获取技能类。首次调用时触发懒加载。"""
    _load_all_skills()
    return _BUILTIN_SKILLS.get(name)


def list_builtin_skill_names() -> List[str]:
    """列出所有内置技能名称（不触发导入）。"""
    return list(_SKILL_REGISTRY.keys())
