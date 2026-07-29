"""共享主题模块 — Codex-like 中性深色设计系统。

主界面只使用一套背景层级、边框、文字和状态颜色。朱红不再大面积铺底，
只承担品牌识别和需要注意的状态，避免功能型桌面应用常见的视觉噪声。
"""


# ── 调色板 ──────────────────────────────────────────────────────────

class Colors:
    """Vermilion Bird 调色板 — 中性深色界面 + 克制的朱红品牌色。"""

    # 品牌和关键状态
    PRIMARY = "#E2553D"
    PRIMARY_HOVER = "#EE684F"
    PRIMARY_DARK = "#C74631"
    BRAND = PRIMARY

    # 主动作使用中性高对比，不让品牌色占满页面。
    ACTION_BG = "#F2F2F2"
    ACTION_HOVER = "#FFFFFF"
    ACTION_TEXT = "#171717"
    SECONDARY = "#303030"
    SECONDARY_HOVER = "#3A3A3A"

    # 基础表面层级
    BACKGROUND = "#171717"
    SURFACE = "#1E1E1E"
    SURFACE_RAISED = "#262626"
    SURFACE_HOVER = "#2D2D2D"
    SURFACE_SELECTED = "#333333"
    BORDER = "#343434"
    BORDER_STRONG = "#494949"

    # 侧边栏
    SIDEBAR_BG = "#202020"
    SIDEBAR_HOVER = SURFACE_HOVER
    SIDEBAR_ACTIVE = SURFACE_SELECTED
    SIDEBAR_BORDER = BORDER
    SIDEBAR_TEXT = "#ECECEC"
    SIDEBAR_TEXT_DIM = "#929292"

    # 聊天区
    CHAT_BG = BACKGROUND
    CHAT_BG_ALT = SURFACE
    CHAT_BORDER = BORDER
    CHAT_ACCENT = BORDER_STRONG

    # 文本
    TEXT_PRIMARY = "#F1F1F1"
    TEXT_SECONDARY = "#C7C7C7"
    TEXT_MUTED = "#8F8F8F"

    # 用户消息
    USER_NAME = TEXT_PRIMARY
    AI_NAME = TEXT_SECONDARY

    # 状态
    SUCCESS = "#28a745"
    WARNING = "#ffc107"
    DANGER = "#dc3545"
    INFO = "#7EA6D8"

    # 错误
    ERROR_BG = "#352326"
    ERROR_TEXT = "#FF9B9B"

    # 工具调用
    TOOL_BG = SURFACE
    TOOL_BORDER = BORDER_STRONG
    TOOL_HEADER = SURFACE_RAISED
    TOOL_HEADER_HOVER = SURFACE_HOVER
    TOOL_TEXT = TEXT_SECONDARY
    TOOL_RESULT_BG = "#1D2D24"
    TOOL_RESULT_TEXT = "#8DDAA9"
    TOOL_RESULT_BORDER = "#3D7A54"

    # 代码
    CODE_BG = "#2A2A2A"
    CODE_TEXT = "#E6E6E6"
    CODE_BLOCK_BG = "#111111"
    CODE_BLOCK_TEXT = "#E8E8E8"

    # 参数栏
    PARAMS_BG = SURFACE_RAISED
    PARAMS_BORDER = BORDER
    PARAMS_SLIDER = BORDER_STRONG
    PARAMS_SLIDER_HANDLE = TEXT_SECONDARY


# ── 通用 QSS 模板 ──────────────────────────────────────────────────

def header_button_style() -> str:
    """顶栏功能按钮通用样式（MCP/Skills/Models/Scheduler/Dashboard）。"""
    return f"""
        QPushButton {{
            background-color: {Colors.SURFACE_RAISED};
            color: {Colors.TEXT_PRIMARY};
            border: 1px solid {Colors.BORDER};
            border-radius: 8px;
            font-weight: 600;
            padding: 4px 12px;
        }}
        QPushButton:hover {{
            background-color: {Colors.SECONDARY_HOVER};
        }}
        QPushButton:disabled {{
            background-color: {Colors.CHAT_ACCENT};
            color: #ccc;
        }}
    """


def send_button_style() -> str:
    """发送按钮样式。"""
    return f"""
        QPushButton {{
            background-color: {Colors.ACTION_BG};
            color: {Colors.ACTION_TEXT};
            border: none;
            border-radius: 8px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {Colors.ACTION_HOVER};
        }}
        QPushButton:disabled {{
            background-color: {Colors.SURFACE_SELECTED};
            color: {Colors.TEXT_MUTED};
        }}
    """


def stop_button_style() -> str:
    """停止按钮样式。"""
    return f"""
        QPushButton {{
            background-color: {Colors.DANGER};
            color: white;
            border: none;
            border-radius: 18px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: #E74C3C;
        }}
    """


def secondary_button_style() -> str:
    """次级按钮样式（Clear 等）。"""
    return f"""
        QPushButton {{
            background-color: {Colors.SURFACE_RAISED};
            border: 1px solid {Colors.BORDER};
            border-radius: 8px;
            color: {Colors.TEXT_PRIMARY};
        }}
        QPushButton:hover {{
            background-color: {Colors.SURFACE_HOVER};
        }}
    """


def sidebar_button_style() -> str:
    """侧边栏操作按钮样式（+、✎、🗑）。"""
    return f"""
        QPushButton {{
            background-color: transparent;
            border: none;
            border-radius: 8px;
            font-size: 13px;
            color: {Colors.SIDEBAR_TEXT};
            text-align: left;
            padding: 6px 9px;
        }}
        QPushButton:hover {{
            background-color: {Colors.SIDEBAR_HOVER};
        }}
    """


def conversation_list_style() -> str:
    """会话列表样式。"""
    return f"""
        QListWidget {{
            border: none;
            border-radius: 8px;
            background-color: transparent;
            color: {Colors.SIDEBAR_TEXT};
            font-size: 13px;
            outline: none;
        }}
        QListWidget::item {{
            padding: 9px 10px;
            margin: 1px 0;
            border-radius: 8px;
            color: {Colors.SIDEBAR_TEXT};
        }}
        QListWidget::item:selected {{
            background-color: {Colors.SIDEBAR_ACTIVE};
            color: {Colors.TEXT_PRIMARY};
        }}
        QListWidget::item:hover:!selected {{
            background-color: {Colors.SIDEBAR_HOVER};
            color: {Colors.SIDEBAR_TEXT};
        }}
    """


def input_field_style() -> str:
    """输入框样式。"""
    return f"""
        QTextEdit {{
            border: 1px solid {Colors.BORDER};
            border-radius: 14px;
            padding: 8px;
            background-color: {Colors.SURFACE_RAISED};
            color: {Colors.TEXT_PRIMARY};
        }}
        QTextEdit:focus {{
            border: 1px solid {Colors.BORDER_STRONG};
        }}
    """


def chat_scroll_style() -> str:
    """聊天滚动区域样式。"""
    return f"""
        QScrollArea {{
            background-color: {Colors.CHAT_BG_ALT};
            border: 1px solid {Colors.CHAT_BORDER};
            border-radius: 8px;
        }}
        QWidget {{
            background-color: {Colors.CHAT_BG_ALT};
        }}
    """


def message_browser_style() -> str:
    """消息浏览器通用样式。"""
    return f"""
        QTextBrowser {{
            padding: 2px 0;
            background-color: transparent;
            border-radius: 0;
            border: none;
            color: {Colors.TEXT_PRIMARY};
        }}
        QMenu {{
            background-color: {Colors.CHAT_BG};
            color: {Colors.TEXT_PRIMARY};
            border: 1px solid {Colors.CHAT_ACCENT};
        }}
        QMenu::item:selected {{
            background-color: {Colors.SURFACE_SELECTED};
            color: {Colors.TEXT_PRIMARY};
        }}
    """


def error_label_style() -> str:
    """错误消息标签样式。"""
    return f"""
        padding: 5px;
        background-color: {Colors.ERROR_BG};
        border-radius: 4px;
        margin: 2px 0;
        color: {Colors.ERROR_TEXT};
    """


def info_label_style() -> str:
    """信息消息标签样式。"""
    return f"""
        padding: 5px;
        background-color: {Colors.SURFACE};
        border-radius: 4px;
        margin: 2px 0;
        color: {Colors.TEXT_SECONDARY};
    """


def tool_header_style() -> str:
    """工具调用标题栏样式。"""
    return f"""
        QLabel {{
            padding: 5px 10px;
            background-color: {Colors.TOOL_BG};
            border: 1px solid {Colors.TOOL_BORDER};
            border-radius: 8px;
            color: {Colors.TOOL_TEXT};
            font-weight: bold;
            margin: 5px 0;
        }}
    """


def params_container_style() -> str:
    """参数栏容器样式。"""
    return f"""
        QWidget {{
            background-color: {Colors.PARAMS_BG};
            border: 1px solid {Colors.PARAMS_BORDER};
            border-radius: 4px;
            padding: 2px;
        }}
        QLabel {{
            color: {Colors.SIDEBAR_BG};
            font-size: 11px;
        }}
        QSlider::groove:horizontal {{
            height: 4px;
            background: {Colors.PARAMS_SLIDER};
            border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            background: {Colors.PARAMS_SLIDER_HANDLE};
            width: 12px;
            margin: -4px 0;
            border-radius: 6px;
        }}
        QComboBox {{
            background-color: white;
            border: 1px solid {Colors.PARAMS_BORDER};
            border-radius: 3px;
            padding: 2px 5px;
            color: {Colors.SIDEBAR_BG};
        }}
        QComboBox::drop-down {{
            border: none;
        }}
    """


def search_input_style() -> str:
    """搜索输入框样式。"""
    return f"""
        QLineEdit {{
            border: 1px solid {Colors.BORDER};
            border-radius: 8px;
            padding: 7px 10px;
            background-color: {Colors.SURFACE_RAISED};
            color: {Colors.SIDEBAR_TEXT};
            font-size: 12px;
        }}
        QLineEdit:focus {{
            border: 1px solid {Colors.BORDER_STRONG};
        }}
    """


# ── Markdown CSS ───────────────────────────────────────────────────

MARKDOWN_CSS = f"""
<style>
    body {{ font-family: "Helvetica Neue", "Segoe UI", Arial, sans-serif; line-height: 1.62; color: {Colors.TEXT_PRIMARY}; font-size: 14px; }}
    h1 {{ color: {Colors.TEXT_PRIMARY}; border: none; padding-bottom: 4px; }}
    h2 {{ color: {Colors.TEXT_PRIMARY}; border: none; padding-bottom: 3px; }}
    h3 {{ color: {Colors.TEXT_SECONDARY}; }}
    code {{ background-color: {Colors.CODE_BG}; padding: 2px 6px; border-radius: 3px; font-family: Consolas, monospace; color: {Colors.CODE_TEXT}; }}
    pre {{ background-color: {Colors.CODE_BLOCK_BG}; padding: 10px; border-radius: 5px; overflow-x: auto; }}
    pre code {{ background-color: transparent; padding: 0; color: {Colors.CODE_BLOCK_TEXT}; }}
    blockquote {{ border-left: 2px solid {Colors.BORDER_STRONG}; margin-left: 0; padding-left: 14px; color: {Colors.TEXT_SECONDARY}; background-color: transparent; }}
    ul, ol {{ padding-left: 20px; }}
    li {{ margin: 5px 0; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
    th, td {{ border: 1px solid {Colors.CHAT_ACCENT}; padding: 8px; text-align: left; }}
    th {{ background-color: {Colors.PARAMS_BG}; color: {Colors.TEXT_SECONDARY}; }}
    a {{ color: #8AB4F8; text-decoration: none; }}
    a:hover {{ text-decoration: underline; color: #A9C8FA; }}
    .math-block {{ display: block; text-align: center; padding: 12px 0; font-family: 'Times New Roman', serif; font-style: italic; font-size: 1.15em; color: {Colors.TEXT_PRIMARY}; }}
    .math-inline {{ font-family: 'Times New Roman', serif; font-style: italic; color: {Colors.TEXT_PRIMARY}; }}
    .math-frac {{ display: inline-block; text-align: center; vertical-align: middle; line-height: 1.1; }}
    .math-frac sup {{ display: block; font-size: 0.85em; border-bottom: 1px solid {Colors.TEXT_SECONDARY}; padding-bottom: 2px; }}
    .math-frac span {{ font-size: 0.7em; }}
    .math-frac sub {{ display: block; font-size: 0.85em; padding-top: 2px; }}
</style>
"""


def application_style() -> str:
    """应用级 QSS，覆盖 Qt Fusion 默认的浅色控件。"""
    return f"""
        QMainWindow, QDialog, QWidget {{
            background-color: {Colors.BACKGROUND};
            color: {Colors.TEXT_PRIMARY};
            font-family: "Helvetica Neue", "Segoe UI", Arial, sans-serif;
            font-size: 13px;
        }}
        QToolTip {{
            color: {Colors.TEXT_PRIMARY};
            background: {Colors.SURFACE_RAISED};
            border: 1px solid {Colors.BORDER_STRONG};
            padding: 5px 7px;
        }}
        QLineEdit, QTextEdit, QTextBrowser, QComboBox, QSpinBox {{
            color: {Colors.TEXT_PRIMARY};
            background: {Colors.SURFACE_RAISED};
            border: 1px solid {Colors.BORDER};
            border-radius: 8px;
            padding: 6px 8px;
            selection-background-color: {Colors.BORDER_STRONG};
        }}
        QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
            border-color: {Colors.BORDER_STRONG};
        }}
        QComboBox::drop-down {{ border: none; }}
        QComboBox QAbstractItemView {{
            background: {Colors.SURFACE_RAISED};
            color: {Colors.TEXT_PRIMARY};
            border: 1px solid {Colors.BORDER};
            selection-background-color: {Colors.SURFACE_SELECTED};
        }}
        QPushButton, QToolButton {{
            color: {Colors.TEXT_PRIMARY};
            background: {Colors.SURFACE_RAISED};
            border: 1px solid {Colors.BORDER};
            border-radius: 8px;
            padding: 6px 10px;
        }}
        QPushButton:hover, QToolButton:hover {{
            background: {Colors.SURFACE_HOVER};
            border-color: {Colors.BORDER_STRONG};
        }}
        QPushButton:disabled, QToolButton:disabled {{
            color: {Colors.TEXT_MUTED};
            background: {Colors.SURFACE};
        }}
        QMenu {{
            color: {Colors.TEXT_PRIMARY};
            background: {Colors.SURFACE_RAISED};
            border: 1px solid {Colors.BORDER};
            border-radius: 9px;
            padding: 5px;
        }}
        QMenu::item {{ padding: 7px 28px 7px 10px; border-radius: 6px; }}
        QMenu::item:selected {{ background: {Colors.SURFACE_SELECTED}; }}
        QMenu::separator {{ height: 1px; background: {Colors.BORDER}; margin: 5px 8px; }}
        QTabWidget::pane {{ border: none; background: {Colors.BACKGROUND}; }}
        QTabBar::tab {{
            color: {Colors.TEXT_MUTED};
            background: transparent;
            border: none;
            padding: 8px 12px;
        }}
        QTabBar::tab:selected {{ color: {Colors.TEXT_PRIMARY}; border-bottom: 2px solid {Colors.TEXT_PRIMARY}; }}
        QHeaderView::section {{
            color: {Colors.TEXT_SECONDARY};
            background: {Colors.SURFACE};
            border: none;
            border-bottom: 1px solid {Colors.BORDER};
            padding: 7px;
        }}
        QTableWidget, QListWidget, QTreeWidget {{
            color: {Colors.TEXT_PRIMARY};
            background: {Colors.BACKGROUND};
            alternate-background-color: {Colors.SURFACE};
            border: 1px solid {Colors.BORDER};
            gridline-color: {Colors.BORDER};
            outline: none;
        }}
        QTableWidget::item:selected, QListWidget::item:selected, QTreeWidget::item:selected {{
            background: {Colors.SURFACE_SELECTED};
            color: {Colors.TEXT_PRIMARY};
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            background: {Colors.BORDER_STRONG};
            min-height: 28px;
            border-radius: 4px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{
            background: transparent;
            height: 8px;
            margin: 2px;
        }}
        QScrollBar::handle:horizontal {{
            background: {Colors.BORDER_STRONG};
            min-width: 28px;
            border-radius: 4px;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        QSplitter::handle {{ background: {Colors.BORDER}; }}
    """
