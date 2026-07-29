"""CLI 命令组包。

子模块:
- main:      主 CLI 入口 (chat, feishu 命令)
- memory:    记忆管理命令组
- skills:    技能管理命令组
- schedule:  调度任务管理命令组
- task:      用户任务与交付物
- database:  数据库版本、完整性与备份
- eval:      核心产品场景评测
"""

from llm_chat.cli.memory import memory
from llm_chat.cli.skills import skills
from llm_chat.cli.schedule import schedule
from llm_chat.cli import task as task_module
from llm_chat.cli.database import database
from llm_chat.cli.eval import eval_group
from llm_chat.cli.workflow import workflow_group

task_group = task_module.task
from llm_chat.cli.main import main, cli

__all__ = [
    "main",
    "cli",
    "memory",
    "skills",
    "schedule",
    "task_group",
    "database",
    "eval_group",
    "workflow_group",
]
