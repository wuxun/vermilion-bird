# -*- mode: python ; coding: utf-8 -*-
"""
Vermilion Bird - PyInstaller spec
Build:  pyinstaller vermilion-bird.spec

产出:
  dist/vermilion-bird           CLI 可执行文件 (console=True)
  dist/Vermilion Bird.app       GUI .app 包 (console=False, 双击启动 PyQt6)
"""

import os

PROJECT_ROOT = os.getcwd()
SRC_DIR = os.path.join(PROJECT_ROOT, "src")

block_cipher = None

# ── 公共依赖分析 ──
common_hiddenimports = [
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
    "llm_chat.client._stream_tools",
    "llm_chat.client._tools",
    "llm_chat.client._generate",
    "llm_chat.client._logging",
    "llm_chat.utils.token_counter",
    "llm_chat.utils.secure_storage",
    "llm_chat.utils.observability",
    "llm_chat.utils.retry",
]
common_excludes = [
    "matplotlib", "scipy", "numpy", "pandas", "PIL",
    "tkinter", "cv2", "notebook", "jupyter",
]

# ── CLI 版本 (终端模式) ──
a_cli = Analysis(
    ["src/llm_chat/cli/main.py"],
    pathex=[SRC_DIR, PROJECT_ROOT],
    binaries=[],
    datas=[(os.path.join(PROJECT_ROOT, "config.example.yaml"), ".")],
    hiddenimports=common_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=common_excludes,
    noarchive=False,
    module_collection_mode={
        "PyQt6": "pyz",
        "lark_oapi": "pyz",
    },
)

pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz_cli,
    a_cli.scripts,
    a_cli.binaries,
    a_cli.zipfiles,
    a_cli.datas,
    [],
    name="vermilion-bird",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,           # CLI 需要终端
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_ROOT, "icon.icns"),
)

# ── GUI 版本 (.app 包, 双击启动, 无终端窗口) ──
a_gui = Analysis(
    ["gui_entry.py"],
    pathex=[SRC_DIR, PROJECT_ROOT],
    binaries=[],
    datas=[(os.path.join(PROJECT_ROOT, "config.example.yaml"), ".")],
    hiddenimports=common_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=common_excludes,
    noarchive=False,
    module_collection_mode={
        "PyQt6": "pyz",
        "lark_oapi": "pyz",
    },
)

pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data, cipher=block_cipher)

# ── GUI: onedir 模式（避免启动时自解压，-5s 启动时间） ──
exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    exclude_binaries=True,          # 不内嵌二进制，放到 COLLECT 中
    name="vermilion-bird-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,                  # GUI 不显示终端
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_ROOT, "icon.icns"),
)

coll_gui = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.zipfiles,
    a_gui.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="vermilion-bird-gui",
)

app = BUNDLE(
    coll_gui,
    name="Vermilion Bird.app",
    icon=os.path.join(PROJECT_ROOT, "icon.icns"),
    bundle_identifier="com.vermilion-bird.app",
    info_plist={
        "CFBundleDisplayName": "Vermilion Bird",
        "CFBundleName": "Vermilion Bird",
        "CFBundleVersion": "0.0.1",
        "CFBundleShortVersionString": "0.0.1",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
    },
)
