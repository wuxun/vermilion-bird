"""CLI 命令组包。

子模块:
- main:      主 CLI 入口 (chat, feishu 命令)
- memory:    记忆管理命令组
- skills:    技能管理命令组
- schedule:  调度任务管理命令组
"""

from llm_chat.cli.memory import memory
from llm_chat.cli.skills import skills
from llm_chat.cli.schedule import schedule
from llm_chat.cli.main import main, cli

__all__ = ["main", "cli", "memory", "skills", "schedule"]
