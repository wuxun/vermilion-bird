"""共享主题模块 — 暖白底、朱雀红强调的 Codex-like 设计系统。

界面保持低噪声和清晰层级，以暖白与暖灰承载大面积内容，以朱红承担品牌、
主动作、选中态和需要关注的状态。红色不大面积铺底，避免长时间使用时产生压迫感。
"""


# ── 调色板 ──────────────────────────────────────────────────────────

class Colors:
    """Vermilion Bird 调色板 — 暖色中性表面 + 克制的朱雀红。"""

    # 品牌和关键状态
    PRIMARY = "#C23B30"
    PRIMARY_HOVER = "#A92F27"
    PRIMARY_DARK = "#8F271F"
    PRIMARY_SOFT = "#F8E1DA"
    PRIMARY_SUBTLE = "#FDF0EB"
    BRAND = PRIMARY

    # 主要动作使用朱红；其余操作保持暖中性色。
    ACTION_BG = PRIMARY
    ACTION_HOVER = PRIMARY_HOVER
    ACTION_TEXT = "#FFFFFF"
    SECONDARY = "#6B514C"
    SECONDARY_HOVER = "#F3E4DE"

    # 基础表面层级
    BACKGROUND = "#FFF9F5"
    SURFACE = "#FCF2ED"
    SURFACE_RAISED = "#FFFFFF"
    SURFACE_HOVER = "#F8E9E3"
    SURFACE_SELECTED = PRIMARY_SOFT
    BORDER = "#EAD8D1"
    BORDER_STRONG = "#D5ADA4"

    # 侧边栏
    SIDEBAR_BG = "#F8EEE9"
    SIDEBAR_HOVER = SURFACE_HOVER
    SIDEBAR_ACTIVE = PRIMARY_SOFT
    SIDEBAR_BORDER = BORDER
    SIDEBAR_TEXT = "#3B2926"
    SIDEBAR_TEXT_DIM = "#917872"

    # 聊天区
    CHAT_BG = BACKGROUND
    CHAT_BG_ALT = SURFACE
    CHAT_BORDER = BORDER
    CHAT_ACCENT = BORDER_STRONG

    # 文本
    TEXT_PRIMARY = "#2F2220"
    TEXT_SECONDARY = "#67504B"
    TEXT_MUTED = "#907771"

    # 用户消息
    USER_NAME = TEXT_PRIMARY
    AI_NAME = TEXT_SECONDARY

    # 状态
    SUCCESS = "#347158"
    WARNING = "#9A651E"
    DANGER = "#B3261E"
    INFO = "#4D6F89"

    # 错误
    ERROR_BG = "#FCE8E5"
    ERROR_TEXT = "#9F2D24"

    # 工具调用
    TOOL_BG = PRIMARY_SUBTLE
    TOOL_BORDER = BORDER_STRONG
    TOOL_HEADER = PRIMARY_SUBTLE
    TOOL_HEADER_HOVER = SURFACE_HOVER
    TOOL_TEXT = TEXT_SECONDARY
    TOOL_RESULT_BG = "#EDF6F0"
    TOOL_RESULT_TEXT = "#285D46"
    TOOL_RESULT_BORDER = "#79A58D"

    # 代码
    CODE_BG = "#F3E7E2"
    CODE_TEXT = "#7E2D27"
    CODE_BLOCK_BG = "#2C2321"
    CODE_BLOCK_TEXT = "#FFF5F0"

    # 参数栏
    PARAMS_BG = SURFACE
    PARAMS_BORDER = BORDER
    PARAMS_SLIDER = BORDER_STRONG
    PARAMS_SLIDER_HANDLE = PRIMARY

    # 文本链接
    LINK = PRIMARY_DARK
    LINK_HOVER = PRIMARY


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
            background-color: {Colors.SURFACE};
            color: {Colors.TEXT_MUTED};
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
            background-color: {Colors.PRIMARY_DARK};
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
            color: {Colors.PRIMARY_DARK};
            font-weight: 600;
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
            border: 1px solid {Colors.PRIMARY};
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
            color: {Colors.PRIMARY_DARK};
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
            color: {Colors.TEXT_SECONDARY};
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
            background-color: {Colors.SURFACE_RAISED};
            border: 1px solid {Colors.PARAMS_BORDER};
            border-radius: 3px;
            padding: 2px 5px;
            color: {Colors.TEXT_PRIMARY};
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
            border: 1px solid {Colors.PRIMARY};
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
    a {{ color: {Colors.LINK}; text-decoration: none; }}
    a:hover {{ text-decoration: underline; color: {Colors.LINK_HOVER}; }}
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
            selection-background-color: {Colors.PRIMARY_SOFT};
            selection-color: {Colors.TEXT_PRIMARY};
        }}
        QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
            border-color: {Colors.PRIMARY};
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
        QMenu::item:selected {{
            background: {Colors.SURFACE_SELECTED};
            color: {Colors.PRIMARY_DARK};
        }}
        QMenu::separator {{ height: 1px; background: {Colors.BORDER}; margin: 5px 8px; }}
        QTabWidget::pane {{ border: none; background: {Colors.BACKGROUND}; }}
        QTabBar::tab {{
            color: {Colors.TEXT_MUTED};
            background: transparent;
            border: none;
            padding: 8px 12px;
        }}
        QTabBar::tab:selected {{
            color: {Colors.PRIMARY_DARK};
            border-bottom: 2px solid {Colors.PRIMARY};
        }}
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
            color: {Colors.PRIMARY_DARK};
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
