# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Vermilion Bird macOS .app bundle (onedir mode)."""

from PyInstaller.utils.hooks import collect_data_files

a = Analysis(
    ['src/llm_chat/cli/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        *collect_data_files('llm_chat'),
    ],
    hiddenimports=[
        # PyQt6
        'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets',
        # MCP
        'mcp', 'mcp.client.stdio', 'mcp.client.sse',
        # Playwright
        'playwright',
        # Keyring backends
        'keyring.backends.macOS',
        'keyring.backends.SecretService',
        # LLM clients
        'httpx', 'httpx_sse',
        # Other
        'jieba',
        'tiktoken', 'tiktoken_ext.openai_public', 'tiktoken_ext',
        'apscheduler', 'apscheduler.triggers', 'apscheduler.executors',
        'sqlalchemy',
        'trafilatura',
        'markdown',
        'bs4',
        'duckduckgo_search', 'ddgs',
        'feedparser',
        'lark_oapi',
        'pydantic', 'pydantic_settings',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'scipy',
        'pandas', 'PIL', 'cv2',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='vermilion-bird',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # .app without terminal window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='vermilion-bird',
)

app = BUNDLE(
    coll,
    name='Vermilion Bird.app',
    icon='icon.icns',
    bundle_identifier='com.vermilion-bird.app',
    info_plist={
        'NSHighResolutionCapable': 'True',
        'CFBundleShortVersionString': '0.2.1',
        'CFBundleVersion': '0.2.1',
        'NSHumanReadableCopyright': 'Vermilion Bird - LLM Chat Client',
    },
)
