"""共享主题模块 — 调色板 + 通用 QSS 片段。

所有前端文件应从这里导入颜色和样式常量，避免硬编码散布。
修改此文件即可全局切换主题。
"""


# ── 调色板 ──────────────────────────────────────────────────────────

class Colors:
    """Vermilion Bird 调色板 — 暖棕朱雀风格。"""

    # 主色调
    PRIMARY = "#C84B31"        # 朱红（按钮、强调）
    PRIMARY_HOVER = "#B8312F"  # 深朱红
    PRIMARY_DARK = "#A52A2A"   # 暗红

    # 次要色
    SECONDARY = "#D4652F"      # 橙褐（顶栏按钮）
    SECONDARY_HOVER = "#C84B31"

    # 侧边栏
    SIDEBAR_BG = "#4A2C2A"     # 深棕
    SIDEBAR_HOVER = "#6B4D4A"  # 中棕
    SIDEBAR_ACTIVE = "#5C3D3A" # 选中棕
    SIDEBAR_BORDER = "#3D2422"
    SIDEBAR_TEXT = "#F5E6D3"   # 暖白
    SIDEBAR_TEXT_DIM = "#BFA89A"

    # 聊天区
    CHAT_BG = "#FFFBF5"        # 暖白
    CHAT_BG_ALT = "#FFF8F0"   # 略暖
    CHAT_BORDER = "#E8D5C4"
    CHAT_ACCENT = "#D4A574"    # 沙色边框

    # 文本
    TEXT_PRIMARY = "#3D2C2E"   # 深棕文字
    TEXT_SECONDARY = "#6B4423" # 中棕文字
    TEXT_MUTED = "#8B7355"     # 淡棕文字

    # 用户消息
    USER_NAME = "#B8312F"      # 用户名
    AI_NAME = "#D4652F"        # AI 名

    # 状态
    SUCCESS = "#28a745"
    WARNING = "#ffc107"
    DANGER = "#dc3545"
    INFO = "#6B4423"

    # 错误
    ERROR_BG = "#FFEBEE"
    ERROR_TEXT = "#8B0000"

    # 工具调用
    TOOL_BG = "#F3E5F5"
    TOOL_BORDER = "#9C27B0"
    TOOL_HEADER = "#E1BEE7"
    TOOL_HEADER_HOVER = "#CE93D8"
    TOOL_TEXT = "#7B1FA2"
    TOOL_RESULT_BG = "#E8F5E9"
    TOOL_RESULT_TEXT = "#2E7D32"
    TOOL_RESULT_BORDER = "#4CAF50"

    # 代码
    CODE_BG = "#FFF3E6"
    CODE_TEXT = "#8B4513"
    CODE_BLOCK_BG = "#2D2D2D"
    CODE_BLOCK_TEXT = "#F5E6D3"

    # 参数栏
    PARAMS_BG = "#F5E6D3"
    PARAMS_BORDER = "#D4A574"
    PARAMS_SLIDER = "#D4A574"
    PARAMS_SLIDER_HANDLE = "#8B4513"


# ── 通用 QSS 模板 ──────────────────────────────────────────────────

def header_button_style() -> str:
    """顶栏功能按钮通用样式（MCP/Skills/Models/Scheduler/Dashboard）。"""
    return f"""
        QPushButton {{
            background-color: {Colors.SECONDARY};
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: bold;
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
            background-color: {Colors.PRIMARY};
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {Colors.PRIMARY_HOVER};
        }}
        QPushButton:disabled {{
            background-color: {Colors.CHAT_ACCENT};
        }}
    """


def stop_button_style() -> str:
    """停止按钮样式。"""
    return f"""
        QPushButton {{
            background-color: {Colors.DANGER};
            color: white;
            border: none;
            border-radius: 5px;
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
            background-color: #FFF3E6;
            border: 1px solid {Colors.CHAT_ACCENT};
            border-radius: 8px;
            color: {Colors.TEXT_SECONDARY};
        }}
        QPushButton:hover {{
            background-color: {Colors.PARAMS_BG};
        }}
    """


def sidebar_button_style() -> str:
    """侧边栏操作按钮样式（+、✎、🗑）。"""
    return f"""
        QPushButton {{
            background-color: {Colors.SIDEBAR_ACTIVE};
            border: 1px solid #7A5A56;
            border-radius: 5px;
            font-size: 14px;
            color: {Colors.SIDEBAR_TEXT};
        }}
        QPushButton:hover {{
            background-color: #7A5A56;
        }}
    """


def conversation_list_style() -> str:
    """会话列表样式。"""
    return f"""
        QListWidget {{
            border: none;
            border-radius: 8px;
            background-color: {Colors.SIDEBAR_ACTIVE};
            color: {Colors.SIDEBAR_TEXT};
            font-size: 12px;
            outline: none;
        }}
        QListWidget::item {{
            padding: 12px 8px;
            border-bottom: 1px solid {Colors.SIDEBAR_BG};
            color: {Colors.SIDEBAR_TEXT};
        }}
        QListWidget::item:selected {{
            background-color: {Colors.PRIMARY};
            color: white;
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
            border: 1px solid {Colors.CHAT_ACCENT};
            border-radius: 8px;
            padding: 8px;
            background-color: #FFFCF7;
            color: {Colors.TEXT_PRIMARY};
        }}
        QTextEdit:focus {{
            border: 2px solid {Colors.PRIMARY};
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
            padding: 5px;
            background-color: rgba(255,255,255,0.5);
            border-radius: 4px;
            border: none;
            color: {Colors.TEXT_PRIMARY};
        }}
        QMenu {{
            background-color: {Colors.CHAT_BG};
            color: {Colors.TEXT_PRIMARY};
            border: 1px solid {Colors.CHAT_ACCENT};
        }}
        QMenu::item:selected {{
            background-color: {Colors.CHAT_ACCENT};
            color: white;
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
        background-color: rgba(255,255,255,0.5);
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
            border-left: 3px solid {Colors.TOOL_BORDER};
            border-radius: 4px;
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
            border: 1px solid #7A5A56;
            border-radius: 5px;
            padding: 4px 8px;
            background-color: {Colors.SIDEBAR_ACTIVE};
            color: {Colors.SIDEBAR_TEXT};
            font-size: 11px;
        }}
        QLineEdit:focus {{
            border: 1px solid {Colors.PRIMARY};
        }}
    """


# ── Markdown CSS ───────────────────────────────────────────────────

MARKDOWN_CSS = f"""
<style>
    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: {Colors.TEXT_PRIMARY}; }}
    h1 {{ color: {Colors.PRIMARY_HOVER}; border-bottom: 2px solid {Colors.PRIMARY}; padding-bottom: 5px; }}
    h2 {{ color: {Colors.PRIMARY}; border-bottom: 1px solid {Colors.SECONDARY}; padding-bottom: 5px; }}
    h3 {{ color: {Colors.SECONDARY}; }}
    code {{ background-color: {Colors.CODE_BG}; padding: 2px 6px; border-radius: 3px; font-family: Consolas, monospace; color: {Colors.CODE_TEXT}; }}
    pre {{ background-color: {Colors.CODE_BLOCK_BG}; padding: 10px; border-radius: 5px; overflow-x: auto; }}
    pre code {{ background-color: transparent; padding: 0; color: {Colors.CODE_BLOCK_TEXT}; }}
    blockquote {{ border-left: 4px solid {Colors.PRIMARY}; margin-left: 0; padding-left: 15px; color: {Colors.TEXT_SECONDARY}; background-color: {Colors.CHAT_BG_ALT}; }}
    ul, ol {{ padding-left: 20px; }}
    li {{ margin: 5px 0; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
    th, td {{ border: 1px solid {Colors.CHAT_ACCENT}; padding: 8px; text-align: left; }}
    th {{ background-color: {Colors.PARAMS_BG}; color: {Colors.TEXT_SECONDARY}; }}
    a {{ color: {Colors.PRIMARY_HOVER}; text-decoration: none; }}
    a:hover {{ text-decoration: underline; color: {Colors.PRIMARY}; }}
    .math-block {{ display: block; text-align: center; padding: 12px 0; font-family: 'Times New Roman', serif; font-style: italic; font-size: 1.15em; color: {Colors.TEXT_PRIMARY}; }}
    .math-inline {{ font-family: 'Times New Roman', serif; font-style: italic; color: {Colors.TEXT_PRIMARY}; }}
    .math-frac {{ display: inline-block; text-align: center; vertical-align: middle; line-height: 1.1; }}
    .math-frac sup {{ display: block; font-size: 0.85em; border-bottom: 1px solid {Colors.TEXT_SECONDARY}; padding-bottom: 2px; }}
    .math-frac span {{ font-size: 0.7em; }}
    .math-frac sub {{ display: block; font-size: 0.85em; padding-top: 2px; }}
</style>
"""
