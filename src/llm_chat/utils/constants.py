"""
项目级常量定义 — 消除硬编码路径和魔法值。

导入方式:
    from llm_chat.utils.constants import (
        PROJECT_DIR, DB_PATH, MEMORY_DIR, TRANSCRIPT_DIR, HISTORY_DIR,
    )
"""

import os


# -- 路径常量 ----------------------------------------------------------

# 项目根目录下的数据目录
PROJECT_DIR = os.path.join(os.getcwd() if os.getcwd().endswith("vermilion-bird") else ".", ".vb")

# SQLite 数据库
DB_PATH = os.path.join(".vb", "vermilion_bird.db")

# JSON 历史记录（旧格式）
HISTORY_DIR = os.path.join(".vb", "history")

# 记忆系统
MEMORY_DIR = "~/.vermilion-bird/memory"
MEMORY_SHORT_TERM = os.path.join(MEMORY_DIR, "short_term.md")
MEMORY_MID_TERM = os.path.join(MEMORY_DIR, "mid_term.md")
MEMORY_LONG_TERM = os.path.join(MEMORY_DIR, "long_term.md")
MEMORY_SOUL = os.path.join(MEMORY_DIR, "soul.md")

# 上下文转录本
TRANSCRIPT_DIR = "~/.vermilion-bird/transcripts"

# -- 默认参数 ----------------------------------------------------------

DEFAULT_EXTRACTION_INTERVAL = 10  # 对话轮次
DEFAULT_EXTRACTION_TIME_INTERVAL = 3600  # 秒
DEFAULT_SHORT_TERM_MAX_ENTRIES = 50
DEFAULT_MAX_MEMORY_TOKENS = 2000
DEFAULT_MID_TERM_MAX_DAYS = 30
DEFAULT_MID_TERM_COMPRESS_DAYS = 7
DEFAULT_LONG_TERM_EVOLVE_DAYS = 7

DEFAULT_SUBAGENT_TIMEOUT = 60
DEFAULT_SUBAGENT_MAX_WORKERS = 8
