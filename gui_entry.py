"""
Vermilion Bird GUI 入口 — 供 macOS .app 包使用
双击启动时自动进入 GUI 模式（PyQt6）。
"""
import sys

# 模拟命令行参数: vermilion-bird chat --gui
if "--gui" not in sys.argv and "chat" not in sys.argv:
    sys.argv = ["vermilion-bird", "chat", "--gui"]

from llm_chat.cli.main import cli

cli()
