# -*- mode: python ; coding: utf-8 -*-
"""
Vermilion Bird - PyInstaller spec
Build:  pyinstaller vermilion-bird.spec
"""

import os

# 从当前目录推断项目根（pyinstaller 在工作目录执行此 spec）
PROJECT_ROOT = os.getcwd()
SRC_DIR = os.path.join(PROJECT_ROOT, "src")

block_cipher = None

a = Analysis(
    ["src/llm_chat/cli/main.py"],
    pathex=[SRC_DIR, PROJECT_ROOT],
    binaries=[],
    datas=[(os.path.join(PROJECT_ROOT, "config.example.yaml"), ".")],
    hiddenimports=[
        "llm_chat.protocols.openai",
        "llm_chat.protocols.anthropic",
        "llm_chat.protocols.gemini",
        "llm_chat.storage._core",
        "llm_chat.storage._conversation",
        "llm_chat.storage._task",
        "llm_chat.storage._feishu",
        "llm_chat.frontends.cli",
        "llm_chat.frontends.gui",
        "llm_chat.frontends.feishu",
        "llm_chat.frontends.feishu.server",
        "llm_chat.frontends.feishu.adapter",
        "llm_chat.frontends.feishu.mapper",
        "llm_chat.frontends.feishu.models",
        "llm_chat.frontends.feishu.push",
        "llm_chat.frontends.feishu.security",
        "llm_chat.frontends.feishu.error_handler",
        "llm_chat.memory",
        "llm_chat.memory.storage",
        "llm_chat.memory.manager",
        "llm_chat.memory.extractor",
        "llm_chat.memory.summarizer",
        "llm_chat.memory.templates",
        "llm_chat.context.manager",
        "llm_chat.context.compressor",
        "llm_chat.context.cache",
        "llm_chat.tools.registry",
        "llm_chat.tools.executor",
        "llm_chat.skills.calculator.skill",
        "llm_chat.skills.file_reader.skill",
        "llm_chat.skills.file_writer.skill",
        "llm_chat.skills.file_editor.skill",
        "llm_chat.skills.web_search.skill",
        "llm_chat.skills.web_fetch.skill",
        "llm_chat.skills.todo_manager.skill",
        "llm_chat.skills.shell_exec.skill",
        "llm_chat.skills.shell_exec.sandbox",
        "llm_chat.skills.scheduler.skill",
        "llm_chat.skills.remember_fact.skill",
        "llm_chat.skills.task_delegator.skill",
        "llm_chat.skills.task_delegator.tools",
        "llm_chat.skills.task_delegator.registry",
        "llm_chat.skills.task_delegator.context",
        "llm_chat.skills.task_delegator.workflow",
        "llm_chat.skills.prompt_skill",
        "llm_chat.scheduler.scheduler",
        "llm_chat.scheduler.task_executor",
        "llm_chat.scheduler.notification",
        "llm_chat.scheduler.webhook",
        "llm_chat.mcp.client",
        "llm_chat.mcp.manager",
        "llm_chat.intent.classifier",
        "llm_chat.client._base",
        "llm_chat.client._chat",
        "llm_chat.client._stream",
        "llm_chat.client._stream_tools",
        "llm_chat.client._tools",
        "llm_chat.client._generate",
        "llm_chat.client._logging",
        "llm_chat.utils.token_counter",
        "llm_chat.utils.secure_storage",
        "llm_chat.utils.observability",
        "llm_chat.utils.retry",
        "pkg_resources",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "scipy", "numpy", "pandas", "PIL",
        "tkinter", "cv2", "notebook", "jupyter",
    ],
    noarchive=False,
    module_collection_mode={
        "PyQt6": "pyz",
        "lark_oapi": "pyz",
    },
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── CLI 可执行文件（终端模式） ──
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="vermilion-bird",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # CLI 需要终端
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_ROOT, "icon.icns"),
)

# ── macOS .app 包（GUI 模式，可双击启动） ──
app = BUNDLE(
    exe,
    name="Vermilion Bird.app",
    icon=os.path.join(PROJECT_ROOT, "icon.icns"),
    bundle_identifier="com.vermilion-bird.app",
    info_plist={
        "CFBundleDisplayName": "Vermilion Bird",
        "CFBundleName": "Vermilion Bird",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
    },
)
