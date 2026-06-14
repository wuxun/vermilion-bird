import sys
import threading
import time
import logging
from typing import Optional, List, Dict, Any, Callable
from llm_chat.frontends.base import (
    BaseFrontend,
    Message,
    ConversationContext,
    MessageType,
)
from llm_chat.frontends.subagent_panel import SubAgentPanel
from llm_chat.frontends.widgets import (
    InputTextEdit,
    CollapsibleToolCall,
    StreamSignals,
    ConversationListSignals,
    ProactiveMessageSignals,
)
from llm_chat.frontends.theme import (
    Colors,
    MARKDOWN_CSS,
    header_button_style,
    send_button_style,
    stop_button_style,
    secondary_button_style,
    sidebar_button_style,
    conversation_list_style,
    input_field_style,
    chat_scroll_style,
    message_browser_style,
    error_label_style,
    info_label_style,
    tool_header_style,
    params_container_style,
    search_input_style,
)

from llm_chat.decision.card_panel import DecisionCardWidget, CardSignals
from llm_chat.decision.schema import DecisionCard
from llm_chat.frontends.model_config import ModelConfigMixin

logger = logging.getLogger(__name__)


def _build_card_selection_message(card: "DecisionCard", selected) -> str:
    """构建用户选择卡片选项后的 LLM 输入消息。

    包含卡片背景和选项细节，确保 LLM 在后续对话中保留上下文。
    """
    parts = [f"我选择了「{selected.label}」"]
    if selected.description:
        parts.append(f"\n说明：{selected.description}")
    if selected.expected_effect:
        parts.append(f"\n预期效果：{selected.expected_effect}")
    if card.context and card.context not in selected.description:
        parts.append(f"\n\n背景：{card.context}")
    parts.append("\n\n请基于这个方向继续。")
    return "".join(parts)

try:
    import markdown

    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

try:
    from PyQt6.QtWidgets import (
        QApplication,
        QMainWindow,
        QWidget,
        QVBoxLayout,
        QHBoxLayout,
        QTextEdit,
        QTextBrowser,
        QPushButton,
        QLabel,
        QFrame,
        QMessageBox,
        QListWidget,
        QListWidgetItem,
        QSplitter,
        QLineEdit,
        QInputDialog,
        QAbstractItemView,
        QScrollArea,
        QSizePolicy,
        QSlider,
        QComboBox,
        QDialog,
    )
    from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal, QObject
    from PyQt6.QtGui import QFont, QTextCursor, QKeyEvent, QIcon, QPixmap

    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False
    QApplication = None
    QMainWindow = None
    QWidget = None
    QVBoxLayout = None
    QHBoxLayout = None
    QTextEdit = None
    QTextBrowser = None
    QPushButton = None
    QLabel = None
    QFrame = None
    QMessageBox = None
    QListWidget = None
    QListWidgetItem = None
    QSplitter = None
    QLineEdit = None
    QInputDialog = None
    QAbstractItemView = None
    QScrollArea = None
    QSizePolicy = None
    QSlider = None
    QComboBox = None
    QDialog = None
    Qt = None
    QTimer = None
    QSize = None
    QFont = None
    QTextCursor = None
    QKeyEvent = None
    QIcon = None
    QPixmap = None
    pyqtSignal = None
    QObject = None





class GUIFrontend(ModelConfigMixin, BaseFrontend):
    def __init__(self, conversation_id: str = "default", title: str = "Vermilion Bird"):
        BaseFrontend.__init__(self, "gui")
        self._conversation_id: str = conversation_id
        self._title: str = title
        self._app: Optional[QApplication] = None
        self._main_window: Optional[QMainWindow] = None
        self._chat_display: Optional[QTextBrowser] = None
        self._chat_scroll_area: Optional[QScrollArea] = None
        self._chat_container: Optional[QWidget] = None
        self._chat_layout: Optional[QVBoxLayout] = None
        self._input_field: Optional[InputTextEdit] = None
        self._send_button: Optional[QPushButton] = None
        self._clear_button: Optional[QPushButton] = None
        self._mcp_button: Optional[QPushButton] = None
        self._mcp_dialog = None
        self._scheduler_button: Optional[QPushButton] = None
        self._scheduler_dialog = None
        self._settings_button: Optional[QPushButton] = None
        self._app_instance: Optional[Any] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._stream_signals: Optional[StreamSignals] = None
        self._conv_list_signals: Optional[ConversationListSignals] = None
        self._proactive_signals: Optional[ProactiveMessageSignals] = None
        self._card_signals: Optional[CardSignals] = None
        self._current_stream_text: str = ""
        self._streaming_label: Optional[QLabel] = None
        self._streaming_browser: Optional[QTextBrowser] = None
        self._messages: list = []
        self._current_tool_calls: list = []
        self._current_tool_call_widgets: Dict[str, CollapsibleToolCall] = {}
        self._is_streaming: bool = False
        self._streaming_conversation_id: Optional[str] = None
        self._storage: Optional[Any] = None
        self._chat_core: Optional[Any] = None  # ChatCore 实例，由 App 注入

        self._conversation_list: Optional[QListWidget] = None
        self._new_conv_button: Optional[QPushButton] = None
        self._delete_conv_button: Optional[QPushButton] = None
        self._rename_conv_button: Optional[QPushButton] = None
        self._context_label: Optional[QLabel] = None
        self._cost_label: Optional[QLabel] = None
        self._current_model: str = "deepseek-chat"  # 稍后由 set_config 覆盖

        self._on_new_conversation: Optional[Callable] = None
        self._on_delete_conversation: Optional[Callable] = None
        self._on_rename_conversation: Optional[Callable] = None
        self._on_switch_conversation: Optional[Callable] = None
        self._on_list_conversation: Optional[Callable] = None
        self._config: Optional[Any] = None
        self._model_combo: Optional[QComboBox] = None
        self._scheduler_button: Optional[QPushButton] = None
        self._scheduler_dialog = None
        self._subagent_panel: Optional[SubAgentPanel] = None

    def set_storage(self, storage: Any):
        self._storage = storage

    def set_config(self, config: Any):
        self._config = config

    def set_app(self, app: Any):
        self._app_instance = app

    def set_chat_core(self, chat_core: Any):
        """注入 ChatCore — GUI 通过它进行流式对话，不再直接访问 client。"""
        self._chat_core = chat_core
        logger.info("GUIFrontend: ChatCore 已注入")

    def _init_subagent_panel(self):
        """尝试将 SubAgentPanel 连接到 task_delegator 的注册表。

        如果 skill 尚未加载（例如首次启动），面板保持隐藏，
        后续 skill 加载时可通过重新调用本方法完成连接。
        """
        if self._subagent_panel is None or self._app_instance is None:
            return

        try:
            skill_manager = self._app_instance.get_skill_manager()
            skill = skill_manager.get_skill("task_delegator")
            if skill is not None and hasattr(skill, "_registry"):
                self._subagent_panel.connect_registry(skill._registry)
                logger.info("SubAgentPanel connected to task_delegator registry")
            else:
                logger.warning("SubAgentPanel: task_delegator skill not loaded")
        except Exception as e:
            logger.warning("SubAgentPanel: failed to connect: %s", e)

    def _setup_shortcuts(self):
        """注册全局键盘快捷键。"""
        from PyQt6.QtGui import QShortcut, QKeySequence

        # Ctrl+N → 新建对话
        QShortcut(QKeySequence("Ctrl+N"), self._main_window, self._on_new_conv)
        # Ctrl+K → 聚焦搜索框
        QShortcut(QKeySequence("Ctrl+K"), self._main_window, self._focus_search)
        # Ctrl+L → 清空对话
        QShortcut(QKeySequence("Ctrl+L"), self._main_window, self._on_clear)
        # Escape → 停止生成（流式中）或聚焦输入框
        QShortcut(QKeySequence("Escape"), self._main_window, self._on_escape)
        # Ctrl+, → 打开设置菜单
        QShortcut(QKeySequence("Ctrl+,"), self._main_window, self._show_settings_menu)
        logger.info("键盘快捷键已注册")

    def _focus_search(self):
        """聚焦侧边栏搜索框。"""
        if self._search_input:
            self._search_input.setFocus()
            self._search_input.selectAll()

    def _on_escape(self):
        """Escape 键：流式中停止，否则聚焦输入框。"""
        if self._is_streaming:
            self._on_stop_generation()
        elif self._input_field:
            self._input_field.setFocus()

    def _show_settings_menu(self):
        """显示设置下拉菜单。"""
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self._main_window)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {Colors.CHAT_BG};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.CHAT_ACCENT};
                border-radius: 8px;
                padding: 6px;
                font-size: 13px;
            }}
            QMenu::item {{
                padding: 8px 28px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {Colors.PRIMARY};
                color: white;
            }}
            QMenu::separator {{
                height: 1px;
                background: {Colors.CHAT_ACCENT};
                margin: 4px 8px;
            }}
        """)

        menu.addAction("💬 新建对话", self._on_new_conv)
        menu.addAction("🗑 清空对话", self._on_clear)
        menu.addSeparator()
        menu.addAction("🔧 MCP Tools", self._on_mcp_config)
        menu.addAction("⚡ Skills", self._on_skills_config)
        menu.addAction("🤖 模型设置", self._on_models_config)
        menu.addAction("⏰ Scheduler", self._on_scheduler_config)
        menu.addAction("📊 Dashboard", self._on_dashboard)
        menu.addSeparator()
        menu.addAction("⌨️ 快捷键", self._show_shortcuts_help)

        pos = self._settings_button.mapToGlobal(self._settings_button.rect().bottomLeft())
        menu.exec(pos)

    def _show_shortcuts_help(self):
        """显示快捷键帮助弹窗。"""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self._main_window,
            "快捷键",
            "Ctrl+N  — 新建对话\n"
            "Ctrl+K  — 搜索历史对话\n"
            "Ctrl+L  — 清空当前对话\n"
            "Ctrl+,  — 打开设置菜单\n"
            "Escape  — 停止生成 / 聚焦输入框\n"
            "Enter   — 发送消息\n"
            "Shift+Enter — 换行",
        )

    def set_conversation_callbacks(
        self,
        on_new: Callable,
        on_delete: Callable,
        on_rename: Callable,
        on_switch: Callable,
        on_list: Callable,
    ):
        self._on_new_conversation = on_new
        self._on_delete_conversation = on_delete
        self._on_rename_conversation = on_rename
        self._on_switch_conversation = on_switch
        self._on_list_conversation = on_list

    def start(self, post_init: Optional[Callable] = None):
        self._app = QApplication(sys.argv)
        self._app.setStyle("Fusion")

        self._stream_signals = StreamSignals()
        self._stream_signals.text_received.connect(self._on_stream_text)
        self._stream_signals.stream_finished.connect(self._on_stream_finished)
        self._stream_signals.error_occurred.connect(self._on_stream_error)
        self._stream_signals.tool_call_started.connect(self._on_tool_call_started)
        self._stream_signals.tool_call_finished.connect(self._on_tool_call_finished)
        self._stream_signals.context_updated.connect(self._on_context_updated)

        self._conv_list_signals = ConversationListSignals()
        self._conv_list_signals.conversations_updated.connect(
            self._refresh_conversation_list
        )

        self._proactive_signals = ProactiveMessageSignals()
        self._proactive_signals.opener_ready.connect(
            self._on_proactive_opener
        )

        self._card_signals = CardSignals()
        self._card_signals.card_created.connect(self._on_card_received)
        self._card_signals.card_decided.connect(self._on_card_decided)
        self._card_signals.proactive_text.connect(self._on_proactive_text)

        self._main_window = QMainWindow()
        self._main_window.setWindowTitle(self._title)
        self._main_window.setMinimumSize(QSize(1000, 600))

        self._set_window_icon()

        central_widget = QWidget()
        self._main_window.setCentralWidget(central_widget)

        self._setup_ui(central_widget)
        self._apply_styles()

        self._init_model_combo()
        self._init_subagent_panel()
        self._setup_shortcuts()

        self._main_window.closeEvent = self._on_close_event

        self._refresh_conversation_list()

        self._main_window.show()

        # 窗口显示后异步执行后台初始化（MCP 连接 / Scheduler 启动等）
        if post_init is not None:
            QTimer.singleShot(0, post_init)

        # 空态：显示欢迎卡片
        if self.is_current_conversation_empty():
            self._show_welcome_state()
        sys.exit(self._app.exec())

    def _set_window_icon(self):
        import os

        icon_paths = [
            os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "vermilion_bird_small.png"
            ),
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "..",
                "..",
                "vermilion_bird_small.png",
            ),
        ]

        for icon_path in icon_paths:
            if os.path.exists(icon_path):
                pixmap = QPixmap(icon_path)
                if not pixmap.isNull():
                    icon = QIcon(pixmap)
                    self._main_window.setWindowIcon(icon)
                    if self._app:
                        self._app.setWindowIcon(icon)
                    logger.info(f"应用图标已设置: {icon_path}")
                    return

        logger.warning("未找到应用图标文件")

    def _setup_ui(self, parent: QWidget):
        main_layout = QHBoxLayout(parent)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._sidebar = self._create_sidebar()
        main_layout.addWidget(self._sidebar)

        chat_area = self._create_chat_area()
        main_layout.addWidget(chat_area, stretch=1)

    def _create_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setFixedWidth(220)
        sidebar.setObjectName("sidebar")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # 顶栏：标题 + 折叠按钮
        top_row = QHBoxLayout()
        title_label = QLabel("会话")
        title_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        top_row.addWidget(title_label)

        top_row.addStretch()

        self._collapse_button = QPushButton("◀")
        self._collapse_button.setFixedSize(24, 24)
        self._collapse_button.setToolTip("收起侧边栏")
        self._collapse_button.setStyleSheet(sidebar_button_style())
        self._collapse_button.clicked.connect(self._toggle_sidebar)
        top_row.addWidget(self._collapse_button)

        layout.addLayout(top_row)

        button_layout = QHBoxLayout()

        self._new_conv_button = QPushButton("+")
        self._new_conv_button.setFixedSize(30, 30)
        self._new_conv_button.setToolTip("New Conversation (Ctrl+N)")
        self._new_conv_button.clicked.connect(self._on_new_conv)
        button_layout.addWidget(self._new_conv_button)

        self._rename_conv_button = QPushButton("✎")
        self._rename_conv_button.setFixedSize(30, 30)
        self._rename_conv_button.setToolTip("Rename")
        self._rename_conv_button.clicked.connect(self._on_rename_conv)
        button_layout.addWidget(self._rename_conv_button)

        self._delete_conv_button = QPushButton("🗑")
        self._delete_conv_button.setFixedSize(30, 30)
        self._delete_conv_button.setToolTip("Delete")
        self._delete_conv_button.clicked.connect(self._on_delete_conv)
        button_layout.addWidget(self._delete_conv_button)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        # 搜索栏
        search_layout = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("🔍 搜索历史对话 (Ctrl+K)...")
        self._search_input.setStyleSheet(search_input_style())
        self._search_input.returnPressed.connect(self._on_search)
        search_layout.addWidget(self._search_input)
        self._search_clear_button = QPushButton("✕")
        self._search_clear_button.setFixedSize(24, 24)
        self._search_clear_button.clicked.connect(self._clear_search)
        self._search_clear_button.setVisible(False)
        search_layout.addWidget(self._search_clear_button)
        layout.addLayout(search_layout)

        self._conversation_list = QListWidget()
        self._conversation_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._conversation_list.itemClicked.connect(self._on_conversation_selected)
        layout.addWidget(self._conversation_list, stretch=1)

        return sidebar

    def _toggle_sidebar(self):
        """折叠/展开侧边栏。"""
        if self._sidebar.width() > 50:
            # 收起
            self._sidebar.setFixedWidth(40)
            self._collapse_button.setText("▶")
            self._collapse_button.setToolTip("展开侧边栏")
            for w in [
                self._new_conv_button, self._rename_conv_button, self._delete_conv_button,
                self._search_input, self._search_clear_button, self._conversation_list,
            ]:
                if w:
                    w.hide()
            # 隐藏标题（保留折叠按钮）
            for i in range(self._sidebar.layout().count()):
                item = self._sidebar.layout().itemAt(i)
                if item and item.layout():
                    for j in range(item.layout().count()):
                        w = item.layout().itemAt(j).widget()
                        if w and w != self._collapse_button:
                            w.hide()
        else:
            # 展开
            self._sidebar.setFixedWidth(220)
            self._collapse_button.setText("◀")
            self._collapse_button.setToolTip("收起侧边栏")
            for w in [
                self._new_conv_button, self._rename_conv_button, self._delete_conv_button,
                self._search_input, self._conversation_list,
            ]:
                if w:
                    w.show()
            for i in range(self._sidebar.layout().count()):
                item = self._sidebar.layout().itemAt(i)
                if item and item.layout():
                    for j in range(item.layout().count()):
                        w = item.layout().itemAt(j).widget()
                        if w:
                            w.show()

    def _create_chat_area(self) -> QWidget:
        chat_area = QFrame()
        chat_area.setObjectName("chatArea")

        layout = QVBoxLayout(chat_area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 极简顶栏 ──
        header = QFrame()
        header.setFixedHeight(44)
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.CHAT_BG};
                border-bottom: 1px solid {Colors.CHAT_BORDER};
            }}
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 0, 12, 0)
        header_layout.setSpacing(8)

        title_label = QLabel("Vermilion Bird")
        title_label.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # 模型选择器（紧凑）
        self._model_combo = QComboBox()
        self._model_combo.setFixedWidth(140)
        self._model_combo.setStyleSheet(f"""
            QComboBox {{
                background: transparent;
                border: 1px solid {Colors.CHAT_ACCENT};
                border-radius: 6px;
                padding: 2px 8px;
                color: {Colors.TEXT_PRIMARY};
                font-size: 11px;
            }}
            QComboBox::drop-down {{ border: none; }}
        """)
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        header_layout.addWidget(self._model_combo)

        self._settings_button = QPushButton("⚙️")
        self._settings_button.setFixedSize(32, 32)
        self._settings_button.setToolTip("设置 (Ctrl+,)")
        self._settings_button.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 6px;
                font-size: 16px;
            }
            QPushButton:hover { background-color: rgba(0,0,0,0.05); }
        """)
        self._settings_button.clicked.connect(self._show_settings_menu)
        header_layout.addWidget(self._settings_button)

        layout.addWidget(header)

        # ── 对话区域（居中 768px 列） ──
        self._chat_scroll_area = QScrollArea()
        self._chat_scroll_area.setWidgetResizable(True)
        self._chat_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._chat_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._chat_scroll_area.setStyleSheet(f"""
            QScrollArea {{ background-color: {Colors.CHAT_BG}; border: none; }}
        """)

        # 居中容器：外层 wrapper 用于水平居中
        scroll_content = QWidget()
        scroll_content.setStyleSheet(f"background-color: {Colors.CHAT_BG};")
        center_layout = QHBoxLayout(scroll_content)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        # 左侧弹簧
        center_layout.addStretch()

        # 对话列（固定最大宽度）
        self._chat_container = QWidget()
        self._chat_container.setMaximumWidth(768)
        self._chat_container.setStyleSheet(f"background-color: {Colors.CHAT_BG};")
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(24, 20, 24, 20)
        self._chat_layout.setSpacing(12)
        self._chat_layout.addStretch()

        center_layout.addWidget(self._chat_container)

        # 右侧弹簧
        center_layout.addStretch()

        self._chat_scroll_area.setWidget(scroll_content)
        layout.addWidget(self._chat_scroll_area, stretch=1)

        # Sub Agent 面板
        self._subagent_panel = SubAgentPanel()
        self._subagent_panel.hide()
        layout.addWidget(self._subagent_panel)

        # 死代码清理：不再需要 _chat_display
        self._chat_display = None

        # 参数栏已移入设置菜单，保留 widget 引用供 model_config.py 使用
        self._params_container = QWidget()
        self._params_container.hide()
        self._temperature_slider = QSlider(Qt.Orientation.Horizontal)
        self._temperature_slider.setMinimum(0)
        self._temperature_slider.setMaximum(20)
        self._temperature_slider.setValue(7)
        self._temperature_slider.valueChanged.connect(self._on_temperature_changed)
        self._temperature_value = QLabel("0.7")
        self._reasoning_combo = QComboBox()
        self._reasoning_combo.addItems(["关闭", "低", "中", "高"])
        self._reasoning_combo.setCurrentIndex(0)
        self._reasoning_combo.currentIndexChanged.connect(self._on_reasoning_changed)

        # ── 底部固定区域：输入框 + 状态栏 ──
        bottom_frame = QFrame()
        bottom_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.CHAT_BG};
                border-top: 1px solid {Colors.CHAT_BORDER};
            }}
        """)
        bottom_layout = QVBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(16, 8, 16, 8)
        bottom_layout.setSpacing(6)

        # 输入行
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self._input_field = InputTextEdit()
        self._input_field.setFont(QFont("Arial", 11))
        self._input_field.setPlaceholderText("输入消息... (Enter 发送, Shift+Enter 换行)")
        self._input_field.setStyleSheet(f"""
            QTextEdit {{
                border: 1px solid {Colors.CHAT_ACCENT};
                border-radius: 12px;
                padding: 10px 14px;
                background-color: {Colors.CHAT_BG_ALT};
                color: {Colors.TEXT_PRIMARY};
            }}
            QTextEdit:focus {{
                border: 1.5px solid {Colors.PRIMARY};
            }}
        """)
        self._input_field.send_requested.connect(self._on_send)
        input_row.addWidget(self._input_field, stretch=1)

        self._send_button = QPushButton("Send")
        self._send_button.setFixedSize(72, 36)
        self._send_button.clicked.connect(self._on_send)
        self._send_button.setDefault(True)
        self._send_button.setStyleSheet(send_button_style())
        input_row.addWidget(self._send_button)

        self._stop_button = QPushButton("⏹ Stop")
        self._stop_button.setFixedSize(72, 36)
        self._stop_button.clicked.connect(self._on_stop_generation)
        self._stop_button.setVisible(False)
        self._stop_button.setStyleSheet(stop_button_style())
        input_row.addWidget(self._stop_button)

        bottom_layout.addLayout(input_row)

        # 状态栏（输入框下方，极简）
        status_row = QHBoxLayout()
        status_row.setContentsMargins(4, 0, 4, 0)

        self._context_label = QLabel(self._format_context_text(0, self._get_current_context_limit()))
        self._context_label.setFont(QFont("Arial", 9))
        self._context_label.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        status_row.addWidget(self._context_label)

        status_row.addStretch()

        self._cost_label = QLabel("💲 —")
        self._cost_label.setFont(QFont("Arial", 9))
        self._cost_label.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        status_row.addWidget(self._cost_label)

        bottom_layout.addLayout(status_row)

        layout.addWidget(bottom_frame)

        return chat_area

    def _apply_styles(self):
        """应用全局样式 — 引用 theme.py 共享常量。"""
        self._main_window.setStyleSheet(f"""
            QFrame#sidebar {{
                background-color: {Colors.SIDEBAR_BG};
                border-right: 1px solid {Colors.SIDEBAR_BORDER};
            }}
            QFrame#sidebar QLabel {{ color: {Colors.SIDEBAR_TEXT}; }}
            QFrame#chatArea {{
                background-color: {Colors.CHAT_BG};
            }}
            QLabel {{ color: {Colors.TEXT_PRIMARY}; }}
        """)

        self._conversation_list.setStyleSheet(conversation_list_style())

        for btn in [self._new_conv_button, self._rename_conv_button, self._delete_conv_button]:
            if btn:
                btn.setStyleSheet(sidebar_button_style())

    def _on_new_conv(self):
        if self._is_streaming:
            self.display_info("请等待当前响应完成")
            return

        if self._on_new_conversation:
            self._on_new_conversation()

    def _on_delete_conv(self):
        if self._is_streaming:
            self.display_info("请等待当前响应完成")
            return

        if self._on_delete_conversation:
            self._on_delete_conversation(self.conversation_id)

    def _on_rename_conv(self):
        if self._on_rename_conversation:
            self._on_rename_conversation(self.conversation_id)

    def _on_search(self):
        """搜索历史对话 — 在侧边栏显示结果"""
        query = self._search_input.text().strip()
        if not query:
            return
        self._search_clear_button.setVisible(True)

        if not self._app_instance or not hasattr(self._app_instance, 'conversation_manager'):
            self.display_error("对话管理器不可用")
            return

        try:
            results = self._app_instance.conversation_manager.search_messages(
                query, limit=10
            )
            if not results:
                self._conversation_list.clear()
                self._conversation_list.addItem(f'未找到: "{query}"')
                return

            self._conversation_list.clear()
            conv_counts = {}
            for r in results:
                cid = r.get('conversation_id', '')
                conv_counts[cid] = conv_counts.get(cid, 0) + 1

            for cid, count in conv_counts.items():
                preview = next(
                    (r.get('content', '')[:80] for r in results if r.get('conversation_id') == cid),
                    ''
                )
                self._conversation_list.addItem(f'{cid[:12]}... ({count} 条匹配)\n  {preview}')
        except Exception as e:
            self.display_error(f"搜索失败: {e}")

    def _clear_search(self):
        """清除搜索，恢复对话列表"""
        self._search_input.clear()
        self._search_clear_button.setVisible(False)
        self._refresh_conversation_list()

    def _on_conversation_selected(self, item: QListWidgetItem):
        if self._is_streaming:
            self.display_info("请等待当前响应完成")
            for i in range(self._conversation_list.count()):
                list_item = self._conversation_list.item(i)
                if list_item.data(Qt.ItemDataRole.UserRole) == self.conversation_id:
                    list_item.setSelected(True)
                    break
            return

        conv_id = item.data(Qt.ItemDataRole.UserRole)
        if conv_id and conv_id != self.conversation_id:
            if self._on_switch_conversation:
                self._on_switch_conversation(conv_id)

    def update_conversation_list(self, conversations: List[Dict[str, Any]]):
        if self._conversation_list is None:
            return

        self._conversation_list.clear()

        for conv in conversations:
            item = QListWidgetItem()
            title = conv.get("title") or conv.get("id", "Untitled")
            item.setText(title)
            item.setData(Qt.ItemDataRole.UserRole, conv.get("id"))

            if conv.get("id") == self.conversation_id:
                item.setSelected(True)

            self._conversation_list.addItem(item)

        for i in range(self._conversation_list.count()):
            list_item = self._conversation_list.item(i)
            if list_item.data(Qt.ItemDataRole.UserRole) == self.conversation_id:
                list_item.setSelected(True)
                self._conversation_list.setCurrentItem(list_item)
                break

    def _refresh_conversation_list(self):
        if self._on_list_conversation:
            self._on_list_conversation()

    def request_conversation_list_refresh(self):
        if self._conv_list_signals:
            self._conv_list_signals.conversations_updated.emit()

    def set_current_conversation(
        self, conversation_id: str, messages: List[Dict[str, Any]]
    ):
        self._conversation_id = conversation_id
        self._messages = []

        for msg in messages:
            self._messages.append(
                {"role": msg.get("role"), "content": msg.get("content")}
            )

        self._update_context_status()
        self._refresh_chat_display()
        self._refresh_conversation_list()

    def is_current_conversation_empty(self) -> bool:
        return len(self._messages) == 0

    def _update_context_status(self):
        """更新上下文状态栏 (token 使用量 / 上下文上限)。"""
        if self._context_label is None:
            return  # UI 尚未初始化
        from llm_chat.utils.token_counter import count_tokens, get_context_limit

        # 对话历史 token 计数（跳过卡片消息，它们没有 content 字段）
        history = [{"role": m["role"], "content": m.get("content", "")} for m in self._messages if m.get("role") != "card"]
        history_text = "\n".join(h.get("content", "") for h in history)
        total_tokens = count_tokens(history_text, self._current_model)

        # 系统上下文 (记忆注入) — 通过 ChatCore 获取实际内容
        if self._chat_core and self._config and self._config.memory.enabled:
            try:
                system_ctx = self._chat_core.get_system_context(self.conversation_id)
                if system_ctx:
                    total_tokens += count_tokens(system_ctx, self._current_model) + 4
            except Exception as e:
                logger.warning(f"获取系统上下文失败: {e}")

        # 上下文上限
        limit = get_context_limit(self._current_model)
        usage_percent = (total_tokens / limit) * 100 if limit > 0 else 0

        self._context_label.setText(
            self._format_context_text(total_tokens, limit, usage_percent)
        )

        if usage_percent < 50:
            color = "#28a745"
        elif usage_percent < 80:
            color = "#ffc107"
        else:
            color = "#dc3545"

        self._context_label.setStyleSheet(
            f"color: {color}; padding: 2px; font-weight: bold;"
        )

        # 同时更新成本显示
        self._update_cost_status()

    def _update_cost_status(self):
        """更新成本标签（从 observability 获取累计消耗）。"""
        if self._cost_label is None:
            return
        try:
            from llm_chat.utils.observability import get_cost_summary
            summary = get_cost_summary()
            total_tokens = summary.get("tokens", {}).get("total", 0)
            total_cost = summary.get("cost", {}).get("total_usd", 0)
            if total_tokens > 0:
                self._cost_label.setText(
                    f"💲 {total_tokens:,} tokens · $" + f"{total_cost:.4f}"
                )
                self._cost_label.setStyleSheet("color: #666; padding: 2px; font-weight: bold;")
            else:
                self._cost_label.setText("💲 成本: —")
                self._cost_label.setStyleSheet("color: #888; padding: 2px;")
        except Exception:
            self._cost_label.setText("💲 成本: —")

    @staticmethod
    def _format_context_text(used: int, limit: int, percent: float = None) -> str:
        """格式化上下文状态文本。"""
        if percent is None:
            percent = (used / limit) * 100 if limit > 0 else 0
        return f"上下文: {used:,} / {limit:,} tokens ({percent:.1f}%)"

    def _get_current_context_limit(self) -> int:
        """获取当前模型上下文上限。"""
        from llm_chat.utils.token_counter import get_context_limit

        model = self._current_model or (
            self._config.llm.model if (self._config and hasattr(self._config, 'llm')) else "unknown"
        )
        return get_context_limit(model)

    def _get_model_params(self) -> Dict[str, Any]:
        """获取当前模型参数"""
        params = {}

        if self._temperature_slider:
            temp = self._temperature_slider.value() / 10.0
            if temp != 0.7:
                params["temperature"] = temp

        if self._reasoning_combo and self._reasoning_combo.currentIndex() > 0:
            reasoning_levels = ["off", "low", "medium", "high"]
            params["reasoning_effort"] = reasoning_levels[
                self._reasoning_combo.currentIndex()
            ]

        return params

    def _on_send(self):
        if self._input_field is None:
            return
        content = self._input_field.toPlainText().strip()
        if not content:
            return
        self._input_field.clear()
        self._start_streaming(content)

    def _start_streaming(self, message: str):
        """启动流式对话：显示用户消息、发起 worker 线程调用 LLM。"""
        # 清除欢迎态
        if not self._messages:
            self._clear_chat_widgets()

        self._messages.append({"role": "user", "content": message})
        self._update_context_status()
        self._display_user_message(message)

        self._set_input_state(False)
        self._current_stream_text = ""
        self._current_tool_calls = []
        self._is_streaming = True
        self._streaming_conversation_id = self.conversation_id

        # 思考动画：等待首个 token
        self._display_ai_prefix()
        self._ensure_streaming_browser()
        if self._streaming_browser:
            self._streaming_browser.setHtml(
                '<span style="color:#8B7355;">● ● ●</span>'
            )

        current_conv_id = self.conversation_id
        model_params = self._get_model_params()

        def stream_response():
            try:
                chat_core = self._chat_core
                if chat_core is None:
                    self._stream_signals.error_occurred.emit(current_conv_id, "ChatCore 未初始化")
                    return

                full_text = chat_core.send_message_stream(
                    conversation_id=current_conv_id,
                    message=message,
                    on_chunk=lambda text: self._stream_signals.text_received.emit(text),
                    on_tool_start=lambda name, args: self._stream_signals.tool_call_started.emit(name, args),
                    on_tool_end=lambda name, args, result: self._stream_signals.tool_call_finished.emit(name, args, result),
                    on_context_update=lambda used, limit: self._stream_signals.context_updated.emit(used, limit),
                    on_card=lambda card: self._card_signals.card_created.emit(card),
                    **model_params,
                )
                self._stream_signals.stream_finished.emit(current_conv_id, full_text)
            except Exception as e:
                self._stream_signals.error_occurred.emit(current_conv_id, str(e))

        self._worker_thread = threading.Thread(target=stream_response, daemon=True)
        self._worker_thread.start()

    def _display_user_message(self, content: str):
        if self._chat_layout is None:
            return

        from datetime import datetime
        ts = datetime.now().strftime("%H:%M")
        escaped = self._escape_html(content)

        # 用户气泡：右对齐，朱红色背景
        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        outer = QHBoxLayout(wrapper)
        outer.setContentsMargins(40, 4, 8, 4)
        outer.addStretch()

        bubble = QLabel(
            f"<div style='text-align:right; font-size:10px; color:#BFA89A; margin-bottom:2px;'>{ts}</div>"
            f"<div style='color:white;'>{escaped}</div>"
        )
        bubble.setTextFormat(Qt.TextFormat.RichText)
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble.setStyleSheet(f"""
            background-color: {Colors.PRIMARY};
            color: white;
            border-radius: 12px;
            padding: 8px 14px;
            font-size: 13px;
        """)
        bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        bubble.setMaximumWidth(520)
        outer.addWidget(bubble)

        self._add_widget_to_chat(wrapper)
        self._scroll_to_bottom(force_layout=True)

    def _adjust_browser_height(self, browser):
        """调整 QTextBrowser 高度以适应内容"""
        if browser is None:
            return
        doc_height = browser.document().size().height()
        margins = browser.contentsMargins()
        new_height = int(doc_height + margins.top() + margins.bottom() + 10)
        browser.setFixedHeight(max(30, new_height))

    def _display_ai_prefix(self):
        if self._chat_layout is None:
            return

        from datetime import datetime
        ts = datetime.now().strftime("%H:%M")

        # AI 头部：头像 + 名称 + 时间
        header = QLabel(
            f"<span style='font-size:15px;'>🐦</span> "
            f"<b style='color:{Colors.AI_NAME};'>Vermilion Bird</b> "
            f"<span style='color:{Colors.TEXT_MUTED}; font-size:10px;'>{ts}</span>"
        )
        header.setTextFormat(Qt.TextFormat.RichText)
        header.setStyleSheet("background: transparent; margin-left: 4px; margin-top: 8px;")
        self._add_widget_to_chat(header)

        self._streaming_browser = None
        self._scroll_to_bottom(force_layout=True)

    def _ensure_streaming_browser(self):
        if self._streaming_browser is not None:
            return

        self._streaming_browser = self._create_message_browser("")
        self._add_widget_to_chat(self._streaming_browser)

    def _on_stream_text(self, text: str):
        if not self._is_streaming:
            return

        self._ensure_streaming_browser()

        self._current_stream_text += text

        if self._streaming_browser:
            # 流式光标：末尾闪烁 █
            html_content = self._render_markdown(self._current_stream_text)
            html_content += '<span style="color:#C84B31; animation:blink 1s infinite;">▌</span>'
            self._streaming_browser.setHtml(html_content)

        self._scroll_to_bottom()

    def _on_stream_finished(self, conv_id: str, full_text: str):
        if conv_id != self.conversation_id:
            return

        self._is_streaming = False
        self._streaming_conversation_id = None

        # 更新本地消息列表（持久化已由 ChatCore 统一处理）
        tool_calls_data = self._current_tool_calls.copy()
        self._messages.append(
            {"role": "assistant", "content": full_text, "tool_calls": tool_calls_data}
        )

        self._current_tool_calls = []
        self._current_tool_call_widgets.clear()

        # 追加暂存的决策卡片（在 AI 文本之后）
        pending = getattr(self, "_pending_card", None)
        if pending is not None:
            self._messages.append({"role": "card", "card": pending})
            self._pending_card = None
            logger.info(f"卡片已追加到 assistant 之后: {pending.id}")
            # 有卡片时需要全量重建才能渲染卡片 widget
            self._update_context_status()
            self._refresh_chat_display()
        else:
            # 无卡片：流式浏览器已有内容，去掉末尾光标
            if self._streaming_browser:
                final_html = self._render_markdown(full_text)
                self._streaming_browser.setHtml(final_html)
            self._update_context_status()
            self._scroll_to_bottom(force_layout=True)

        self._set_input_state(True)
        self._refresh_conversation_list()

    def _on_stream_error(self, conv_id: str, error: str):
        if conv_id != self.conversation_id:
            return

        self._is_streaming = False
        self._streaming_conversation_id = None
        self.display_error(error)
        self._set_input_state(True)

    def _on_tool_call_started(self, tool_name: str, tool_args: str):
        if self._chat_layout is None:
            return

        import uuid

        tool_id = str(uuid.uuid4())[:8]

        import json

        try:
            args_dict = json.loads(tool_args)
            args_formatted = json.dumps(args_dict, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            args_formatted = tool_args

        tool_call_info = {
            "id": tool_id,
            "name": tool_name,
            "args": args_formatted,
            "result": None,
        }
        self._current_tool_calls.append(tool_call_info)

        tool_widget = CollapsibleToolCall(tool_id, tool_name, args_formatted)
        self._current_tool_call_widgets[tool_id] = tool_widget

        stretch_index = self._chat_layout.count() - 1
        if stretch_index >= 0:
            stretch_item = self._chat_layout.itemAt(stretch_index)
            if stretch_item and stretch_item.spacerItem():
                self._chat_layout.insertWidget(stretch_index, tool_widget)
            else:
                self._chat_layout.addWidget(tool_widget)
        else:
            self._chat_layout.addWidget(tool_widget)

        self._scroll_to_bottom(force_layout=True)
        logger.info(f"工具调用开始: {tool_name}, args={args_formatted[:100]}")

    def _on_tool_call_finished(self, tool_name: str, tool_args: str, result: str):
        logger.info(
            f"_on_tool_call_finished 被调用: tool_name={tool_name}, result_type={type(result)}, result_is_none={result is None}"
        )

        for tc in self._current_tool_calls:
            if tc["name"] == tool_name and tc["result"] is None:
                tc["result"] = result
                tool_id = tc["id"]

                if tool_id in self._current_tool_call_widgets:
                    widget = self._current_tool_call_widgets[tool_id]
                    logger.info(
                        f"调用 widget.set_result, result_len={len(result) if result else 0}"
                    )
                    widget.set_result(result)

                break

        self._scroll_to_bottom()
        result_len = len(result) if result else 0
        logger.info(f"工具调用完成: {tool_name}, result_length={result_len}")

    def _on_proactive_opener(self, opener: str):
        """处理主动消息（在主线程执行）。"""
        try:
            from datetime import datetime

            app = self._app_instance
            if not app:
                return

            today = datetime.now().strftime("%Y-%m-%d")
            conv = app.conversation_manager.create_conversation(
                title=f"\U0001f4a1 每日话题 {today}"
            )
            conv.add_assistant_message(opener)

            from llm_chat.storage import Storage
            storage = Storage()
            msgs = storage.get_messages(conv.conversation_id)
            formatted = [{"role": m["role"], "content": m["content"]} for m in msgs]

            self.set_current_conversation(conv.conversation_id, formatted)
            self.request_conversation_list_refresh()

            qapp = QApplication.instance()
            if qapp:
                qapp.alert(None, 0)

            logger.info(f"已创建主动对话: {conv.conversation_id}")
        except Exception as e:
            logger.error(f"创建主动对话失败: {e}")

    def _on_context_updated(self, used_tokens: int, limit: int):
        """ChatCore 回调 — 流式过程中实时更新上下文状态。"""
        if self._context_label is None:
            return
        if self._context_label:
            usage_percent = (used_tokens / limit) * 100 if limit > 0 else 0
            self._context_label.setText(
                self._format_context_text(used_tokens, limit, usage_percent)
            )
            if usage_percent < 50:
                color = "#28a745"
            elif usage_percent < 80:
                color = "#ffc107"
            else:
                color = "#dc3545"
            self._context_label.setStyleSheet(
                f"color: {color}; padding: 2px; font-weight: bold;"
            )
            self._update_cost_status()

    def _escape_html(self, text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    def _scroll_to_bottom(self, force_layout: bool = False):
        """滚动到底部。

        Args:
            force_layout: True 时先 processEvents 刷新布局再滚动（首次加入 widget 后）。
                         False 时用稍长延迟等布局自然就绪（流式过程中高频调用时）。"""
        if self._chat_scroll_area:
            from PyQt6.QtCore import QTimer
            if force_layout and self._app:
                # 强制布局刷新：widget 刚加入、需要立刻拿到正确 maximum 时
                self._app.processEvents()
                scrollbar = self._chat_scroll_area.verticalScrollBar()
                QTimer.singleShot(0, lambda: scrollbar.setValue(scrollbar.maximum()))
            else:
                # 流式高频场景：给布局 50ms 自然就绪，避免 processEvents 开销
                scrollbar = self._chat_scroll_area.verticalScrollBar()
                QTimer.singleShot(50, lambda: scrollbar.setValue(scrollbar.maximum()))

    def _clear_chat_widgets(self):
        if self._chat_layout is None:
            return

        while self._chat_layout.count() > 0:
            item = self._chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._chat_layout.addStretch()
        self._current_tool_call_widgets.clear()

    def _create_message_browser(self, html_content: str) -> QTextBrowser:
        """创建消息浏览器，支持选择复制和高度自适应"""
        browser = QTextBrowser()
        browser.setHtml(html_content)
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet(message_browser_style())
        browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        browser.setReadOnly(True)
        browser.document().documentLayout().documentSizeChanged.connect(
            lambda size, b=browser: self._adjust_browser_height(b)
        )
        return browser

    def _refresh_chat_display(self):
        if self._chat_layout is None:
            return

        self._clear_chat_widgets()

        for msg in self._messages:
            if msg["role"] == "user":
                self._display_user_message(msg["content"])
            elif msg["role"] == "card":
                self._render_card_widget(msg["card"])
            elif msg["role"] == "assistant":
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    tool_header = QLabel("🔧 工具调用记录")
                    tool_header.setStyleSheet(tool_header_style())
                    self._add_widget_to_chat(tool_header)

                    for tc in tool_calls:
                        tc_id = tc.get("id", "")
                        tc_name = tc.get("name", "unknown")
                        tc_args = tc.get("args", "{}")
                        tc_result = tc.get("result", "")

                        tool_widget = CollapsibleToolCall(tc_id, tc_name, tc_args)
                        tool_widget.set_result(tc_result)
                        self._add_widget_to_chat(tool_widget)

                # AI 头部
                from datetime import datetime
                ts = ""
                ai_header = QLabel(
                    f"<span style='font-size:15px;'>🐦</span> "
                    f"<b style='color:{Colors.AI_NAME};'>Vermilion Bird</b> "
                    f"<span style='color:{Colors.TEXT_MUTED}; font-size:10px;'>{ts}</span>"
                )
                ai_header.setTextFormat(Qt.TextFormat.RichText)
                ai_header.setStyleSheet("background: transparent; margin-left: 4px; margin-top: 8px;")
                self._add_widget_to_chat(ai_header)

                html_content = self._render_markdown(msg["content"])
                content_browser = self._create_message_browser(html_content)
                self._add_widget_to_chat(content_browser)

        self._scroll_to_bottom(force_layout=True)

    def _add_widget_to_chat(self, widget: QWidget):
        if self._chat_layout is None:
            return

        stretch_index = self._chat_layout.count() - 1
        if stretch_index >= 0:
            stretch_item = self._chat_layout.itemAt(stretch_index)
            if stretch_item and stretch_item.spacerItem():
                self._chat_layout.insertWidget(stretch_index, widget)
                return

        self._chat_layout.addWidget(widget)

    def _show_welcome_state(self):
        """空态：Logo + 快捷操作卡片网格。"""
        if self._chat_layout is None:
            return

        # Logo + 标题
        logo = QLabel("🐦")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("font-size: 48px; background: transparent; margin-top: 40px;")
        self._add_widget_to_chat(logo)

        title = QLabel("Vermilion Bird")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"""
            font-size: 22px; font-weight: bold;
            color: {Colors.TEXT_PRIMARY};
            background: transparent;
            margin-bottom: 6px;
        """)
        self._add_widget_to_chat(title)

        subtitle = QLabel("有什么可以帮你的？")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_MUTED};
            background: transparent;
            margin-bottom: 24px;
        """)
        self._add_widget_to_chat(subtitle)

        # 快捷操作卡片网格
        shortcuts = [
            ("💬", "日常对话", "你好，帮我写一段自我介绍"),
            ("💻", "代码助手", "帮我用 Python 写一个快速排序"),
            ("🔍", "搜索信息", "搜索最新的 AI 新闻"),
            ("📝", "文件操作", "读取当前目录的 README 文件"),
            ("⚡", "任务委托", "帮我分析这个项目的代码结构"),
            ("📊", "定时任务", "创建一个每天早上 9 点的提醒"),
        ]

        grid_widget = QWidget()
        grid_widget.setStyleSheet("background: transparent;")
        from PyQt6.QtWidgets import QGridLayout as GridLayout
        grid = GridLayout(grid_widget)
        grid.setSpacing(10)
        grid.setContentsMargins(40, 0, 40, 0)

        for i, (icon, label, prompt) in enumerate(shortcuts):
            card = QPushButton(f"{icon}  {label}")
            card.setFixedHeight(48)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Colors.CHAT_BG};
                    border: 1px solid {Colors.CHAT_ACCENT};
                    border-radius: 10px;
                    padding: 8px 16px;
                    font-size: 13px;
                    color: {Colors.TEXT_PRIMARY};
                    text-align: left;
                }}
                QPushButton:hover {{
                    background-color: {Colors.PARAMS_BG};
                    border-color: {Colors.PRIMARY};
                }}
            """)
            card.clicked.connect(lambda checked, p=prompt: self._fill_prompt(p))
            grid.addWidget(card, i // 3, i % 3)

        self._add_widget_to_chat(grid_widget)
        self._scroll_to_bottom(force_layout=True)

    def _fill_prompt(self, text: str):
        """快捷卡片点击：填入输入框并聚焦。"""
        if self._input_field:
            self._input_field.setPlainText(text)
            self._input_field.setFocus()
            # 移动光标到末尾
            cursor = self._input_field.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self._input_field.setTextCursor(cursor)

    def _on_clear(self):
        ctx = ConversationContext(conversation_id=self.conversation_id)
        self._handle_clear(ctx)

        self._messages = []
        self._current_tool_call_widgets.clear()

        if self._chat_layout:
            self._clear_chat_widgets()

        # 清空后显示欢迎态
        self._show_welcome_state()

    def _on_close(self):
        self._handle_exit()
        if self._app:
            self._app.quit()

    def _on_close_event(self, event):
        self._handle_exit()
        event.accept()

    def _set_input_state(self, enabled: bool):
        if self._send_button:
            self._send_button.setEnabled(enabled)
            self._send_button.setVisible(enabled)
        if self._stop_button:
            self._stop_button.setVisible(not enabled)
        if self._input_field:
            self._input_field.setEnabled(enabled)

    def _on_stop_generation(self):
        """用户点击 Stop 按钮：取消流式生成 + 取消运行中的子 agent。"""
        if self._chat_core:
            self._chat_core.cancel_generation()
        # 级联取消子 agent
        if self._subagent_panel and self._subagent_panel._registry:
            self._subagent_panel._registry.cancel_all_running()
        logger.info("User requested generation stop")

    def stop(self):
        # Cancel all running sub-agents before quitting
        if self._subagent_panel:
            self._subagent_panel.disconnect_registry()
        if self._app:
            self._app.quit()

    def _render_markdown(self, text: str) -> str:
        if MARKDOWN_AVAILABLE:
            try:
                md = markdown.Markdown(extensions=["tables", "fenced_code"])
                html = md.convert(text)
                return f"{MARKDOWN_CSS}{html}"
            except Exception:
                try:
                    md = markdown.Markdown(extensions=["tables"])
                    html = md.convert(text)
                    return f"{MARKDOWN_CSS}{html}"
                except Exception as e:
                    import logging

                    logging.getLogger(__name__).warning(
                        f"Markdown 渲染失败，使用纯文本: {e}"
                    )
        return text.replace("\n", "<br>")

    def display_message(self, message: Message):
        if self._chat_layout is None:
            return

        if message.role == "user":
            self._display_user_message(message.content)
        elif message.role == "assistant":
            self._display_ai_prefix()
            html_content = self._render_markdown(message.content)
            content_browser = self._create_message_browser(html_content)
            self._add_widget_to_chat(content_browser)

        self._scroll_to_bottom(force_layout=True)

    def display_error(self, error: str):
        if self._chat_layout is None:
            return

        error_label = QLabel(f"<span style='color: #8B0000;'>Error: {error}</span>")
        error_label.setWordWrap(True)
        error_label.setTextFormat(Qt.TextFormat.RichText)
        error_label.setStyleSheet(error_label_style())
        self._add_widget_to_chat(error_label)
        self._scroll_to_bottom(force_layout=True)

    def display_info(self, info: str):
        if self._chat_layout is None:
            return

        info_label = QLabel(
            f"<span style='color: #6B4423; font-style: italic;'>[{info}]</span>"
        )
        info_label.setWordWrap(True)
        info_label.setTextFormat(Qt.TextFormat.RichText)
        info_label.setStyleSheet(info_label_style())
        self._add_widget_to_chat(info_label)
        self._scroll_to_bottom(force_layout=True)

    def display_card(self, card: DecisionCard):
        """渲染决策卡片。

        流式对话中的卡片（有 AI 文本即将到来）：延迟追加，等 AI 文本后再渲染。
        ProactiveAgent 推送的卡片（无活跃流）：立即渲染。
        """
        if self._is_streaming and self._streaming_conversation_id == self.conversation_id:
            # 流式场景：暂存，等 _on_stream_finished 追加到 AI 文本之后
            self._pending_card = card
        else:
            # ProactiveAgent 等无流场景：直接追加并渲染
            self._pending_card = None
            self._messages.append({"role": "card", "card": card})
            self._refresh_chat_display()

    def _render_card_widget(self, card: DecisionCard):
        """创建并插入卡片 widget（内部方法，供 display_card 和 refresh 共用）。"""
        def on_decide(card_id: str, option_id: str):
            self._handle_card_decided(card, option_id)

        def on_dismiss(card_id: str):
            self._handle_card_dismissed(card_id)

        def on_more_info():
            # L2 对话：以卡片内容为上下文发起新对话
            lines = [f"我想了解更多关于「{card.title}」的细节。请详细对比以下选项：", ""]
            for opt in card.options:
                parts = [f"**{opt.id}. {opt.label}**"]
                if opt.description:
                    parts.append(f"  说明：{opt.description}")
                if opt.expected_effect:
                    parts.append(f"  预期效果：{opt.expected_effect}")
                if opt.risk:
                    parts.append(f"  风险：{opt.risk}")
                parts.append(f"  置信度：{int(opt.confidence * 100)}%")
                lines.append("\n".join(parts))
            self._start_streaming("\n".join(lines))

        card_widget = DecisionCardWidget(
            card=card,
            on_decide=on_decide,
            on_dismiss=on_dismiss,
            on_more_info=on_more_info,
        )
        self._add_widget_to_chat(card_widget)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(
            "background-color: #D4A574; max-height: 1px; margin: 10px 0;"
        )
        self._add_widget_to_chat(separator)

    def _on_card_received(self, card: DecisionCard):
        """跨线程信号：收到新卡片。"""
        self.display_card(card)
        logger.info(f"卡片已显示: {card.id} -> {card.title}")

    def _on_proactive_text(self, text: str):
        """跨线程信号：收到新闻精选文本（后台线程→主线程）。"""
        from llm_chat.frontends.base import Message, MessageType
        msg = Message(content=text, role="assistant", msg_type=MessageType.TEXT)
        self.display_message(msg)

    def _on_card_decided(self, card_id: str, option_id: str):
        """跨线程信号：卡片已决策。"""
        try:
            from llm_chat.decision.log import DecisionLogStore
            store = DecisionLogStore()
            store.record(card_id=card_id, card_type="decision", title=f"card:{card_id}", selected_option_id=option_id)
        except Exception as e:
            logger.warning(f"决策日志记录失败: {e}")

    def _handle_card_decided(self, card: DecisionCard, option_id: str):
        """卡片按钮回调：用户做了决策。

        将选择消息发送给 LLM，由 LLM 自主决定下一步（调用工具/追问/执行）。
        不做 hardcoded action 分发——LLM 应该自行判断需要做什么。
        """
        logger.info(f"卡片决策: {card.id} -> {option_id}")
        selected = next((o for o in card.options if o.id == option_id), None)
        if not selected:
            logger.warning(f"选项 {option_id} 不在卡片选项中")
            return

        # 通知 CardSignals
        if self._card_signals:
            self._card_signals.card_decided.emit(card.id, option_id)

        # 记录决策日志
        try:
            from llm_chat.decision.log import DecisionLogStore
            store = DecisionLogStore()
            store.record(
                card_id=card.id,
                card_type=card.card_type.value,
                title=card.title,
                selected_option_id=option_id,
                selected_option_label=selected.label,
                recommendation=card.recommendation,
                context_snapshot=card.context,
            )
        except Exception as e:
            logger.warning(f"决策日志记录失败: {e}")

        # ── 统一处理：将选择交给 LLM ──
        if getattr(card, "conversation_id", None):
            # 来自某个会话 → 在当前会话继续
            self._continue_chat_from_card(card, selected)
        else:
            # ProactiveAgent 推送 → 创建新会话
            self._create_conversation_from_card(card, selected)

    def _continue_chat_from_card(self, card: DecisionCard, selected):
        """从卡片选择继续对话：将选项作为用户消息发送给 LLM。"""
        follow_up = _build_card_selection_message(card, selected)
        self._start_streaming(follow_up)

    def _create_conversation_from_card(
        self, card: DecisionCard, selected
    ):
        """从卡片选项创建新对话并立即触发 LLM 响应。"""
        app = self._app_instance
        if not app:
            return

        option_text = f"{card.title} — {selected.label}"
        conv = app.conversation_manager.create_conversation(
            title=option_text[:80]
        )

        # 切换到新会话（消息由 _start_streaming 追加）
        self.set_current_conversation(conv.conversation_id, [])
        self.request_conversation_list_refresh()

        # 首条消息：卡片上下文 + 用户选择，触发 LLM 响应
        opener = _build_card_selection_message(card, selected)
        self._start_streaming(opener)

        logger.info(f"已从卡片创建对话并触发 LLM: {conv.conversation_id}")

    def _handle_card_dismissed(self, card_id: str):
        """卡片按钮回调：用户忽略了卡片。"""
        logger.info(f"卡片忽略: {card_id}")
        if self._card_signals:
            self._card_signals.card_dismissed.emit(card_id)

        info = QLabel(
            f"<span style='color: #8B7355; font-style: italic;'>"
            f"⏳ 卡片已暂缓</span>"
        )
        info.setStyleSheet(
            "padding: 4px 8px; margin: 2px 0;"
        )
        self._add_widget_to_chat(info)
        self._scroll_to_bottom(force_layout=True)

    @property
    def conversation_id(self) -> str:
        return self._conversation_id if hasattr(self, "_conversation_id") else "default"

    def request_rename_input(
        self, conversation_id: str, current_title: str
    ) -> Optional[str]:
        if not PYQT_AVAILABLE or self._main_window is None:
            return None

        new_title, ok = QInputDialog.getText(
            self._main_window,
            "Rename Conversation",
            "Enter new title:",
            text=current_title,
        )

        if ok and new_title:
            return new_title
        return None
