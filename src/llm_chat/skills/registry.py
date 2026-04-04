import logging
from typing import Dict, Type, List

logger = logging.getLogger(__name__)

_BUILTIN_SKILLS: Dict[str, Type] = {}


def register_skill(name: str):
    def decorator(cls):
        _BUILTIN_SKILLS[name] = cls
        return cls

    return decorator


def get_builtin_skills() -> Dict[str, Type]:
    return _BUILTIN_SKILLS.copy()


def get_skill_class(name: str):
    return _BUILTIN_SKILLS.get(name)


def list_builtin_skill_names() -> List[str]:
    return list(_BUILTIN_SKILLS.keys())


from llm_chat.skills.web_search.skill import WebSearchSkill
from llm_chat.skills.calculator.skill import CalculatorSkill
from llm_chat.skills.web_fetch.skill import WebFetchSkill
from llm_chat.skills.file_reader.skill import FileReaderSkill
from llm_chat.skills.file_writer.skill import FileWriterSkill
from llm_chat.skills.file_editor.skill import FileEditorSkill
from llm_chat.skills.todo_manager.skill import TodoManagerSkill
from llm_chat.skills.task_delegator.skill import TaskDelegatorSkill
from llm_chat.skills.scheduler.skill import SchedulerSkill
from llm_chat.skills.shell_exec.skill import ShellExecSkill

_BUILTIN_SKILLS["web_search"] = WebSearchSkill
_BUILTIN_SKILLS["calculator"] = CalculatorSkill
_BUILTIN_SKILLS["web_fetch"] = WebFetchSkill
_BUILTIN_SKILLS["file_reader"] = FileReaderSkill
_BUILTIN_SKILLS["file_writer"] = FileWriterSkill
_BUILTIN_SKILLS["file_editor"] = FileEditorSkill
_BUILTIN_SKILLS["todo_manager"] = TodoManagerSkill
_BUILTIN_SKILLS["task_delegator"] = TaskDelegatorSkill
_BUILTIN_SKILLS["scheduler"] = SchedulerSkill
_BUILTIN_SKILLS["shell_exec"] = ShellExecSkill
