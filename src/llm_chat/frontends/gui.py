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
    application_style,
    stop_button_style,
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
        QStackedWidget,
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
    QStackedWidget = None
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
        self._execution_center_button: Optional[QPushButton] = None
        self._execution_center_dialog = None
        self._execution_center_timer = None
        self._task_center_button: Optional[QPushButton] = None
        self._task_center_dialog = None
        self._task_workspace = None
        self._workspace_stack: Optional[QStackedWidget] = None
        self._chat_workspace: Optional[QWidget] = None
        self._chat_nav_button: Optional[QPushButton] = None
        self._task_nav_button: Optional[QPushButton] = None
        self._workspace_navigation_sync: bool = False
        self._sidebar_expanded: bool = True
        self._brand_label: Optional[QLabel] = None
        self._recent_label: Optional[QLabel] = None
        self._chat_title_label: Optional[QLabel] = None
        self._goal_frame: Optional[QFrame] = None
        self._goal_title_label: Optional[QLabel] = None
        self._goal_status_label: Optional[QLabel] = None
        self._goal_open_button: Optional[QPushButton] = None
        self._goal_menu_action = None
        self._current_work_item = None
        self._composer_add_button: Optional[QPushButton] = None
        self._sidebar_search_button: Optional[QPushButton] = None
        self._shortcuts: Dict[str, Any] = {}
        self._conversation_menu_button: Optional[QPushButton] = None
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
        self._welcome_widgets: List[QWidget] = []
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

        def register(sequence: str, callback: Callable) -> None:
            shortcut = QShortcut(QKeySequence(sequence), self._main_window)
            shortcut.activated.connect(callback)
            self._shortcuts[sequence] = shortcut

        # Ctrl+N → 新建对话
        register("Ctrl+N", self._on_new_conv)
        # Ctrl+K → 聚焦搜索框
        register("Ctrl+K", self._focus_search)
        # Ctrl+L → 清空对话
        register("Ctrl+L", self._on_clear)
        # Escape → 停止生成（流式中）或聚焦输入框
        register("Escape", self._on_escape)
        # Ctrl+, → 打开设置菜单
        register("Ctrl+,", self._show_settings_menu)
        # Ctrl+Shift+R → 打开执行与审批中心
        register("Ctrl+Shift+R", self._on_execution_center)
        # Ctrl+Shift+T → 打开跨对话工作概览
        register("Ctrl+Shift+T", self._on_task_center)
        logger.info("键盘快捷键已注册")

    def _focus_search(self):
        """聚焦侧边栏搜索框。"""
        if not self._sidebar_expanded and getattr(self, "_sidebar", None) is not None:
            self._toggle_sidebar()
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
        menu.setStyleSheet(
            f"""
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
        """
        )

        menu.addAction("💬 新建对话", self._on_new_conv)
        menu.addAction("🗑 清空对话", self._on_clear)
        menu.addAction("🎯 设为目标 / 查看进展", self._on_goal_action)
        menu.addSeparator()
        menu.addAction("🔧 MCP Tools", self._on_mcp_config)
        menu.addAction("⚡ Skills", self._on_skills_config)
        menu.addAction("🤖 模型设置", self._on_models_config)
        menu.addAction("⏰ Scheduler", self._on_scheduler_config)
        menu.addAction("📊 Dashboard", self._on_dashboard)
        menu.addAction("🧭 高级执行中心", self._on_execution_center)
        menu.addSeparator()
        menu.addAction("⌨️ 快捷键", self._show_shortcuts_help)

        pos = self._settings_button.mapToGlobal(self._settings_button.rect().bottomLeft())
        menu.exec(pos)

    def _show_composer_context_menu(self):
        """展示当前输入可附加的上下文，避免把能力按钮常驻在主界面。"""
        from PyQt6.QtWidgets import QMenu

        if self._composer_add_button is None:
            return
        menu = QMenu(self._main_window)
        menu.addAction("添加文件上下文…", lambda: self._fill_prompt("/file "))
        menu.addAction("搜索历史对话", self._focus_search)
        menu.addSeparator()
        menu.addAction("选择技能…", self._on_skills_config)
        menu.addAction("配置 MCP 工具…", self._on_mcp_config)
        pos = self._composer_add_button.mapToGlobal(
            self._composer_add_button.rect().topLeft()
        )
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
            "Ctrl+Shift+T — 工作概览\n"
            "Ctrl+Shift+R — 执行与审批中心\n"
            "Escape  — 停止生成 / 聚焦输入框\n"
            "Enter   — 发送消息\n"
            "Shift+Enter — 换行",
        )

    def _on_execution_center(self):
        """打开跨会话运行历史与动作审批中心。"""

        if self._app_instance is None:
            QMessageBox.warning(self._main_window, "暂不可用", "应用服务尚未初始化。")
            return
        if self._execution_center_dialog is not None and self._execution_center_dialog.isVisible():
            self._execution_center_dialog.raise_()
            self._execution_center_dialog.activateWindow()
            return

        from llm_chat.frontends.execution_center import ExecutionCenterDialog

        dialog = ExecutionCenterDialog(self._app_instance, self._main_window)
        dialog.destroyed.connect(self._on_execution_center_destroyed)
        self._execution_center_dialog = dialog
        dialog.show()

    def _on_execution_center_destroyed(self):
        self._execution_center_dialog = None

    def _on_task_center(self):
        """打开跨对话目标、审批和交付物的工作概览。"""

        if self._app_instance is None:
            QMessageBox.warning(self._main_window, "暂不可用", "应用服务尚未初始化。")
            return
        if self._workspace_stack is not None and self._task_workspace is not None:
            self._task_workspace.refresh()
            self._workspace_stack.setCurrentWidget(self._task_workspace)
            self._update_workspace_navigation()
            return
        if self._task_center_dialog is not None and self._task_center_dialog.isVisible():
            self._task_center_dialog.raise_()
            self._task_center_dialog.activateWindow()
            return

        from llm_chat.frontends.tasks import TaskCenterDialog

        dialog = TaskCenterDialog(self._app_instance, self._main_window)
        dialog.destroyed.connect(self._on_task_center_destroyed)
        self._task_center_dialog = dialog
        dialog.show()

    def _on_task_center_destroyed(self):
        self._task_center_dialog = None

    def _on_chat_workspace(self):
        """返回当前工作线程。"""

        if self._workspace_stack is None or self._chat_workspace is None:
            return
        self._workspace_stack.setCurrentWidget(self._chat_workspace)
        self._update_workspace_navigation()
        if self._input_field is not None:
            self._input_field.setFocus()

    def _on_task_navigation_toggled(self, checked: bool):
        """工作概览是跨线程聚合入口，不是另一种内容类型。"""

        if checked and not self._workspace_navigation_sync:
            self._on_task_center()

    def _update_workspace_navigation(self):
        current = self._workspace_stack.currentWidget() if self._workspace_stack else None
        self._workspace_navigation_sync = True
        try:
            if self._task_nav_button is not None:
                self._task_nav_button.setChecked(current is self._task_workspace)
        finally:
            self._workspace_navigation_sync = False

    def _update_execution_center_indicator(self):
        """在工作概览入口展示需要用户处理的数量。"""

        if self._task_nav_button is None or self._app_instance is None:
            return
        try:
            if hasattr(self._app_instance, "list_task_workspace_views"):
                from llm_chat.work import TaskWorkspaceScope

                attention_count = len(
                    self._app_instance.list_task_workspace_views(
                        scope=TaskWorkspaceScope.ATTENTION,
                        limit=100,
                    )
                )
            else:
                from llm_chat.runtime import ActionStatus

                attention_count = len(
                    self._app_instance.action_proposals.list(
                        status=ActionStatus.PENDING,
                        limit=100,
                    )
                )
        except Exception:
            logger.debug("Failed to refresh task attention indicator", exc_info=True)
            return
        if self._sidebar_expanded:
            self._task_nav_button.setText(
                f"◎  工作概览    {attention_count}" if attention_count else "◎  工作概览"
            )
        else:
            self._task_nav_button.setText("◎")
        self._task_nav_button.setToolTip(
            (
                f"工作概览：{attention_count} 项待处理"
                if attention_count
                else "工作概览 (Ctrl+Shift+T)"
            )
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
        self._app.setStyleSheet(application_style())

        self._stream_signals = StreamSignals()
        self._stream_signals.text_received.connect(self._on_stream_text)
        self._stream_signals.stream_finished.connect(self._on_stream_finished)
        self._stream_signals.error_occurred.connect(self._on_stream_error)
        self._stream_signals.tool_call_started.connect(self._on_tool_call_started)
        self._stream_signals.tool_call_finished.connect(self._on_tool_call_finished)
        self._stream_signals.context_updated.connect(self._on_context_updated)

        self._conv_list_signals = ConversationListSignals()
        self._conv_list_signals.conversations_updated.connect(self._refresh_conversation_list)

        self._proactive_signals = ProactiveMessageSignals()
        self._proactive_signals.opener_ready.connect(self._on_proactive_opener)

        self._card_signals = CardSignals()
        self._card_signals.card_created.connect(self._on_card_received)
        self._card_signals.card_decided.connect(self._on_card_decided)
        self._card_signals.proactive_text.connect(self._on_proactive_text)

        self._main_window = QMainWindow()
        self._main_window.setWindowTitle(self._title)
        self._main_window.setMinimumSize(QSize(1080, 660))
        self._main_window.resize(QSize(1320, 820))

        self._set_window_icon()

        central_widget = QWidget()
        self._main_window.setCentralWidget(central_widget)

        self._setup_ui(central_widget)
        self._apply_styles()

        self._init_model_combo()
        self._init_subagent_panel()
        self._setup_shortcuts()
        self._execution_center_timer = QTimer(self._main_window)
        self._execution_center_timer.timeout.connect(self._update_execution_center_indicator)
        self._execution_center_timer.timeout.connect(self._refresh_goal_state)
        self._execution_center_timer.start(2500)
        self._update_execution_center_indicator()
        self._refresh_goal_state()

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
            os.path.join(getattr(sys, "_MEIPASS", ""), "vermilion_bird_small.png"),
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "vermilion_bird_small.png"),
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

        self._workspace_stack = QStackedWidget()
        self._chat_workspace = QWidget()
        chat_layout = QHBoxLayout(self._chat_workspace)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)
        chat_area = self._create_chat_area()
        chat_layout.addWidget(chat_area, stretch=1)
        self._workspace_stack.addWidget(self._chat_workspace)

        if self._app_instance is not None:
            from llm_chat.frontends.tasks import TaskCenterDialog

            self._task_workspace = TaskCenterDialog(
                self._app_instance,
                self._workspace_stack,
                embedded=True,
            )
            self._workspace_stack.addWidget(self._task_workspace)

        self._workspace_stack.setCurrentWidget(self._chat_workspace)
        main_layout.addWidget(self._workspace_stack, stretch=1)
        self._update_workspace_navigation()

    def _create_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setFixedWidth(260)
        sidebar.setObjectName("sidebar")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(5)

        # 产品头部保持克制，只提供搜索和折叠两个全局动作。
        top_row = QHBoxLayout()
        top_row.setSpacing(4)
        self._brand_label = QLabel("Vermilion")
        self._brand_label.setFont(QFont("", 14, QFont.Weight.DemiBold))
        self._brand_label.setStyleSheet(
            f"color:{Colors.TEXT_PRIMARY}; padding:3px 5px; background:transparent;"
        )
        top_row.addWidget(self._brand_label)
        top_row.addStretch()

        self._sidebar_search_button = QPushButton("⌕")
        self._sidebar_search_button.setObjectName("sidebarIconButton")
        self._sidebar_search_button.setFixedSize(30, 30)
        self._sidebar_search_button.setToolTip("搜索 (Ctrl+K)")
        self._sidebar_search_button.clicked.connect(self._focus_search)
        top_row.addWidget(self._sidebar_search_button)

        self._collapse_button = QPushButton("◧")
        self._collapse_button.setObjectName("sidebarIconButton")
        self._collapse_button.setFixedSize(30, 30)
        self._collapse_button.setToolTip("收起侧边栏")
        self._collapse_button.clicked.connect(self._toggle_sidebar)
        top_row.addWidget(self._collapse_button)
        layout.addLayout(top_row)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(4)

        self._new_conv_button = QPushButton("✎  新建对话")
        self._new_conv_button.setObjectName("sidebarPrimaryAction")
        self._new_conv_button.setFixedHeight(38)
        self._new_conv_button.setToolTip("新建对话 (Ctrl+N)")
        self._new_conv_button.clicked.connect(self._on_new_conv)
        button_layout.addWidget(self._new_conv_button, 1)

        from PyQt6.QtWidgets import QMenu

        self._conversation_menu_button = QPushButton("···")
        self._conversation_menu_button.setObjectName("sidebarIconButton")
        self._conversation_menu_button.setFixedSize(38, 38)
        self._conversation_menu_button.setToolTip("当前会话操作")
        conversation_menu = QMenu(self._conversation_menu_button)
        conversation_menu.addAction("重命名", self._on_rename_conv)
        conversation_menu.addAction("删除", self._on_delete_conv)
        self._conversation_menu_button.setMenu(conversation_menu)
        button_layout.addWidget(self._conversation_menu_button)
        layout.addLayout(button_layout)

        nav_style = f"""
            QPushButton {{
                border: none;
                border-radius: 8px;
                padding: 8px 10px;
                color: {Colors.TEXT_SECONDARY};
                background: transparent;
                font-size: 13px;
                text-align: left;
            }}
            QPushButton:hover {{ background: {Colors.SIDEBAR_HOVER}; color: {Colors.TEXT_PRIMARY}; }}
            QPushButton:checked {{
                background: {Colors.SIDEBAR_ACTIVE};
                color: {Colors.TEXT_PRIMARY};
                font-weight: 600;
            }}
        """
        self._task_nav_button = QPushButton("◎  工作概览")
        self._task_nav_button.setCheckable(True)
        self._task_nav_button.setFixedHeight(36)
        self._task_nav_button.setStyleSheet(nav_style)
        self._task_nav_button.setToolTip("工作概览 (Ctrl+Shift+T)")
        self._task_nav_button.toggled.connect(self._on_task_navigation_toggled)
        layout.addWidget(self._task_nav_button)

        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(0, 5, 0, 2)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索历史")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setStyleSheet(search_input_style())
        self._search_input.returnPressed.connect(self._on_search)
        search_layout.addWidget(self._search_input)
        self._search_clear_button = QPushButton("✕")
        self._search_clear_button.setFixedSize(24, 24)
        self._search_clear_button.clicked.connect(self._clear_search)
        self._search_clear_button.setVisible(False)
        layout.addLayout(search_layout)

        self._recent_label = QLabel("最近")
        self._recent_label.setStyleSheet(
            f"color:{Colors.TEXT_MUTED}; font-size:11px; padding:8px 8px 3px 8px;"
            "background:transparent;"
        )
        layout.addWidget(self._recent_label)

        self._conversation_list = QListWidget()
        self._conversation_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._conversation_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._conversation_list.itemClicked.connect(self._on_conversation_selected)
        layout.addWidget(self._conversation_list, stretch=1)

        self._settings_button = QPushButton("⚙  设置")
        self._settings_button.setObjectName("sidebarSettingsButton")
        self._settings_button.setFixedHeight(38)
        self._settings_button.setToolTip("设置 (Ctrl+,)")
        self._settings_button.clicked.connect(self._show_settings_menu)
        layout.addWidget(self._settings_button)

        return sidebar

    def _toggle_sidebar(self):
        """折叠/展开侧边栏。"""
        self._sidebar_expanded = not self._sidebar_expanded
        if not self._sidebar_expanded:
            self._sidebar.setFixedWidth(54)
            self._collapse_button.setText("◨")
            self._collapse_button.setToolTip("展开侧边栏")
            for widget in [
                self._brand_label,
                self._sidebar_search_button,
                self._conversation_menu_button,
                self._search_input,
                self._search_clear_button,
                self._conversation_list,
                self._recent_label,
            ]:
                if widget is not None:
                    widget.hide()
            self._new_conv_button.setText("✎")
            self._task_nav_button.setText("◎")
            self._settings_button.setText("⚙")
        else:
            self._sidebar.setFixedWidth(260)
            self._collapse_button.setText("◧")
            self._collapse_button.setToolTip("收起侧边栏")
            for widget in [
                self._brand_label,
                self._sidebar_search_button,
                self._conversation_menu_button,
                self._search_input,
                self._conversation_list,
                self._recent_label,
            ]:
                if widget is not None:
                    widget.show()
            self._new_conv_button.setText("✎  新建对话")
            self._update_execution_center_indicator()
            self._settings_button.setText("⚙  设置")

    def _create_chat_area(self) -> QWidget:
        chat_area = QFrame()
        chat_area.setObjectName("chatArea")

        layout = QVBoxLayout(chat_area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶栏只显示当前上下文，低频操作放进省略菜单。
        header = QFrame()
        header.setObjectName("chatHeader")
        header.setFixedHeight(56)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 0, 16, 0)
        self._chat_title_label = QLabel("新对话")
        self._chat_title_label.setObjectName("chatTitle")
        self._chat_title_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        header_layout.addWidget(self._chat_title_label, 1)
        header_menu_button = QPushButton("···")
        header_menu_button.setObjectName("headerMenuButton")
        header_menu_button.setFixedSize(34, 34)
        header_menu_button.setToolTip("当前对话操作")
        from PyQt6.QtWidgets import QMenu

        header_menu = QMenu(header_menu_button)
        header_menu.addAction("重命名", self._on_rename_conv)
        header_menu.addAction("清空内容", self._on_clear)
        self._goal_menu_action = header_menu.addAction("设为目标…", self._on_goal_action)
        header_menu.addSeparator()
        header_menu.addAction("删除对话", self._on_delete_conv)
        header_menu_button.setMenu(header_menu)
        header_layout.addWidget(header_menu_button)
        layout.addWidget(header)

        # 对话正文限制最大行宽，在大屏上仍保持可读。
        self._chat_scroll_area = QScrollArea()
        self._chat_scroll_area.setWidgetResizable(True)
        self._chat_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._chat_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._chat_scroll_area.setStyleSheet(
            f"""
            QScrollArea {{ background-color: {Colors.CHAT_BG}; border: none; }}
        """
        )

        # 居中容器：外层 wrapper 用于水平居中
        scroll_content = QWidget()
        scroll_content.setStyleSheet(f"background-color: {Colors.CHAT_BG};")
        center_layout = QHBoxLayout(scroll_content)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self._chat_container = QWidget()
        self._chat_container.setMaximumWidth(920)
        self._chat_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._chat_container.setStyleSheet(f"background-color: {Colors.CHAT_BG};")
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(28, 30, 28, 30)
        self._chat_layout.setSpacing(16)
        self._chat_layout.addStretch()

        center_layout.addStretch(1)
        center_layout.addWidget(self._chat_container, stretch=8)
        center_layout.addStretch(1)

        self._chat_scroll_area.setWidget(scroll_content)
        layout.addWidget(self._chat_scroll_area, stretch=1)

        # 子 Agent 仅在有实际运行时出现。
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

        # 目标是对话的渐进能力，而不是另一套输入界面。
        self._goal_frame = QFrame()
        self._goal_frame.setObjectName("goalProgress")
        self._goal_frame.setMaximumWidth(920)
        goal_layout = QHBoxLayout(self._goal_frame)
        goal_layout.setContentsMargins(13, 8, 10, 8)
        goal_layout.setSpacing(8)
        goal_mark = QLabel("◎")
        goal_mark.setObjectName("goalMark")
        goal_layout.addWidget(goal_mark)
        goal_text = QVBoxLayout()
        goal_text.setSpacing(1)
        self._goal_title_label = QLabel()
        self._goal_title_label.setObjectName("goalTitle")
        goal_text.addWidget(self._goal_title_label)
        self._goal_status_label = QLabel()
        self._goal_status_label.setObjectName("goalStatus")
        goal_text.addWidget(self._goal_status_label)
        goal_layout.addLayout(goal_text, 1)
        self._goal_open_button = QPushButton("查看进展")
        self._goal_open_button.setObjectName("goalOpenButton")
        self._goal_open_button.clicked.connect(self._open_current_goal)
        goal_layout.addWidget(self._goal_open_button)
        self._goal_frame.hide()

        goal_row = QHBoxLayout()
        goal_row.setContentsMargins(24, 8, 24, 0)
        goal_row.addStretch(1)
        goal_row.addWidget(self._goal_frame, 8)
        goal_row.addStretch(1)
        layout.addLayout(goal_row)

        # ── Codex-like 底部 composer：输入与上下文动作属于同一张卡片 ──
        bottom_frame = QFrame()
        bottom_frame.setObjectName("composerShell")
        bottom_frame.setMaximumWidth(920)
        bottom_layout = QVBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(12, 10, 10, 9)
        bottom_layout.setSpacing(6)

        self._input_field = InputTextEdit()
        self._input_field.setFont(QFont("", 12))
        self._input_field.setPlaceholderText("输入消息，或描述想完成的工作")
        self._input_field.setMinimumHeight(58)
        self._input_field.setMaximumHeight(132)
        self._input_field.setStyleSheet(
            f"""
            QTextEdit {{
                border: none;
                border-radius: 0;
                padding: 4px 6px;
                background-color: transparent;
                color: {Colors.TEXT_PRIMARY};
            }}
            QTextEdit:focus {{ border: none; }}
        """
        )
        self._input_field.send_requested.connect(self._on_send)
        bottom_layout.addWidget(self._input_field)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self._composer_add_button = QPushButton("＋")
        self._composer_add_button.setObjectName("composerIconButton")
        self._composer_add_button.setFixedSize(32, 32)
        self._composer_add_button.setToolTip("添加上下文或文件")
        self._composer_add_button.clicked.connect(self._show_composer_context_menu)
        toolbar.addWidget(self._composer_add_button)

        self._model_combo = QComboBox()
        self._model_combo.setMinimumWidth(132)
        self._model_combo.setMaximumWidth(210)
        self._model_combo.setObjectName("composerModelCombo")
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        toolbar.addWidget(self._model_combo)
        toolbar.addStretch()

        self._send_button = QPushButton("↑")
        self._send_button.setObjectName("composerSendButton")
        self._send_button.setFixedSize(36, 36)
        self._send_button.setToolTip("发送 (Enter)")
        self._send_button.clicked.connect(self._on_send)
        self._send_button.setDefault(True)
        toolbar.addWidget(self._send_button)

        self._stop_button = QPushButton("■")
        self._stop_button.setFixedSize(36, 36)
        self._stop_button.setToolTip("停止生成")
        self._stop_button.clicked.connect(self._on_stop_generation)
        self._stop_button.setVisible(False)
        self._stop_button.setStyleSheet(stop_button_style())
        toolbar.addWidget(self._stop_button)
        bottom_layout.addLayout(toolbar)

        # 诊断状态默认隐藏，只通过 tooltip 和设置面板按需查看。
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)

        self._context_label = QLabel(
            self._format_context_text(0, self._get_current_context_limit())
        )
        self._context_label.setFont(QFont("Arial", 9))
        self._context_label.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        self._context_label.hide()

        status_row.addStretch()

        self._cost_label = QLabel("💲 —")
        self._cost_label.setFont(QFont("Arial", 9))
        self._cost_label.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        self._cost_label.hide()

        composer_row = QHBoxLayout()
        composer_row.setContentsMargins(24, 10, 24, 18)
        composer_row.addStretch(1)
        composer_row.addWidget(bottom_frame, 8)
        composer_row.addStretch(1)
        layout.addLayout(composer_row)

        return chat_area

    def _apply_styles(self):
        """应用 Codex-like 壳层样式。"""
        self._main_window.setStyleSheet(
            application_style()
            + f"""
            QFrame#sidebar {{
                background-color: {Colors.SIDEBAR_BG};
                border-right: 1px solid {Colors.SIDEBAR_BORDER};
            }}
            QFrame#sidebar QLabel {{ color: {Colors.SIDEBAR_TEXT}; }}
            QPushButton#sidebarIconButton, QPushButton#headerMenuButton {{
                background: transparent;
                border: none;
                border-radius: 8px;
                padding: 0;
                color: {Colors.TEXT_MUTED};
                text-align: center;
            }}
            QPushButton#sidebarIconButton:hover, QPushButton#headerMenuButton:hover {{
                background: {Colors.SURFACE_HOVER};
                color: {Colors.TEXT_PRIMARY};
            }}
            QPushButton#sidebarPrimaryAction {{
                background: transparent;
                border: none;
                border-radius: 8px;
                color: {Colors.TEXT_PRIMARY};
                text-align: left;
                padding: 8px 10px;
                font-weight: 600;
            }}
            QPushButton#sidebarPrimaryAction:hover,
            QPushButton#sidebarSettingsButton:hover {{
                background: {Colors.SURFACE_HOVER};
            }}
            QPushButton#sidebarSettingsButton {{
                background: transparent;
                border: none;
                color: {Colors.TEXT_SECONDARY};
                text-align: left;
                padding: 8px 10px;
            }}
            QFrame#chatArea {{
                background-color: {Colors.CHAT_BG};
            }}
            QFrame#chatHeader {{
                background: {Colors.CHAT_BG};
                border-bottom: 1px solid {Colors.BORDER};
            }}
            QLabel#chatTitle {{
                color: {Colors.TEXT_PRIMARY};
                font-size: 14px;
                font-weight: 600;
            }}
            QFrame#goalProgress {{
                background: {Colors.SURFACE_RAISED};
                border: 1px solid {Colors.BORDER};
                border-radius: 10px;
            }}
            QLabel#goalMark {{
                color: {Colors.PRIMARY};
                border: none;
                background: transparent;
                font-size: 17px;
                font-weight: 700;
            }}
            QLabel#goalTitle {{
                color: {Colors.TEXT_PRIMARY};
                border: none;
                background: transparent;
                font-size: 13px;
                font-weight: 600;
            }}
            QLabel#goalStatus {{
                color: {Colors.TEXT_MUTED};
                border: none;
                background: transparent;
                font-size: 11px;
            }}
            QPushButton#goalOpenButton {{
                background: transparent;
                color: {Colors.TEXT_SECONDARY};
                border: none;
                border-radius: 6px;
                padding: 5px 8px;
            }}
            QPushButton#goalOpenButton:hover {{
                background: {Colors.SURFACE_HOVER};
                color: {Colors.TEXT_PRIMARY};
            }}
            QFrame#composerShell {{
                background: {Colors.SURFACE_RAISED};
                border: 1px solid {Colors.BORDER_STRONG};
                border-radius: 18px;
            }}
            QPushButton#composerIconButton {{
                background: transparent;
                border: none;
                color: {Colors.TEXT_SECONDARY};
                font-size: 18px;
                padding: 0;
            }}
            QPushButton#composerIconButton:hover {{ background: {Colors.SURFACE_HOVER}; }}
            QComboBox#composerModelCombo {{
                background: transparent;
                border: none;
                color: {Colors.TEXT_SECONDARY};
                padding: 4px 6px;
                font-size: 12px;
            }}
            QPushButton#composerSendButton {{
                background: {Colors.ACTION_BG};
                color: {Colors.ACTION_TEXT};
                border: none;
                border-radius: 18px;
                font-size: 18px;
                font-weight: 700;
                padding: 0;
            }}
            QPushButton#composerSendButton:hover {{ background: {Colors.ACTION_HOVER}; }}
            QPushButton#composerSendButton:disabled {{
                background: {Colors.SURFACE_SELECTED};
                color: {Colors.TEXT_MUTED};
            }}
            QLabel {{ color: {Colors.TEXT_PRIMARY}; }}
        """
        )

        self._conversation_list.setStyleSheet(conversation_list_style())

    def _on_new_conv(self):
        if self._is_streaming:
            self.display_info("请等待当前响应完成")
            return

        if self._on_new_conversation:
            self._on_new_conversation()

    def _conversation_goal(self):
        if self._app_instance is None or not hasattr(
            self._app_instance,
            "get_conversation_work_item",
        ):
            return None
        return self._app_instance.get_conversation_work_item(self.conversation_id)

    def _refresh_goal_state(self) -> None:
        """把持久目标渐进呈现在当前对话，而不是建立第二套输入界面。"""

        try:
            item = self._conversation_goal()
        except Exception:
            logger.debug("Failed to refresh conversation goal", exc_info=True)
            return
        self._current_work_item = item
        if self._goal_menu_action is not None:
            self._goal_menu_action.setText("查看目标进展" if item else "设为目标…")
        if self._goal_frame is None:
            return
        self._goal_frame.setVisible(item is not None)
        if item is None:
            return

        status_value = getattr(item.status, "value", str(item.status))
        status_label = {
            "draft": "草稿",
            "ready": "待执行",
            "running": "执行中",
            "cancelling": "正在取消",
            "pausing": "正在暂停",
            "waiting_approval": "等待你的审批",
            "paused": "已暂停",
            "completed": "已完成",
            "failed": "执行失败",
            "cancelled": "已取消",
        }.get(status_value, status_value)
        self._goal_title_label.setText(item.title)
        self._goal_status_label.setText(f"目标 · {status_label}")
        self._goal_frame.setToolTip(item.objective)

    def _on_goal_action(self) -> None:
        if self._is_streaming:
            self.display_info("请等待当前响应完成后再设置目标")
            return
        self._refresh_goal_state()
        if self._current_work_item is not None:
            self._open_current_goal()
            return
        if self._app_instance is None or not hasattr(
            self._app_instance,
            "promote_conversation_to_work_item",
        ):
            QMessageBox.warning(self._main_window, "暂不可用", "目标服务尚未初始化。")
            return

        from llm_chat.frontends.tasks.task_center import NewTaskDialog

        initial_objective = next(
            (
                str(message.get("content", "")).strip()
                for message in reversed(self._messages)
                if message.get("role") == "user" and message.get("content")
            ),
            "",
        )
        current_title = (
            self._chat_title_label.text().strip()
            if self._chat_title_label is not None
            else ""
        )
        if current_title == "新对话":
            current_title = ""
        dialog = NewTaskDialog(
            self._main_window,
            initial_objective=initial_objective,
            initial_title=current_title,
            conversation_goal=True,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            item = self._app_instance.promote_conversation_to_work_item(
                self.conversation_id,
                dialog.objective,
                title=dialog.title or None,
                workspace=dialog.workspace or None,
                expected_deliverable=dialog.expected_deliverable or None,
            )
        except Exception as exc:
            QMessageBox.critical(self._main_window, "设置目标失败", str(exc))
            return

        self._current_work_item = item
        self._refresh_goal_state()
        self._update_execution_center_indicator()
        if dialog.start_immediately.isChecked():
            self._start_streaming(dialog.objective)

    def _open_current_goal(self) -> None:
        self._refresh_goal_state()
        item = self._current_work_item
        if item is None:
            return
        self._on_task_center()
        if self._task_workspace is not None and hasattr(
            self._task_workspace,
            "focus_work_item",
        ):
            self._task_workspace.focus_work_item(item.id)

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

        if not self._app_instance or not hasattr(self._app_instance, "conversation_manager"):
            self.display_error("对话管理器不可用")
            return

        try:
            results = self._app_instance.conversation_manager.search_messages(query, limit=10)
            if not results:
                self._conversation_list.clear()
                self._conversation_list.addItem(f'未找到: "{query}"')
                return

            self._conversation_list.clear()
            conv_counts = {}
            for r in results:
                cid = r.get("conversation_id", "")
                conv_counts[cid] = conv_counts.get(cid, 0) + 1

            for cid, count in conv_counts.items():
                preview = next(
                    (r.get("content", "")[:80] for r in results if r.get("conversation_id") == cid),
                    "",
                )
                self._conversation_list.addItem(f"{cid[:12]}... ({count} 条匹配)\n  {preview}")
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
        if not conv_id:
            return
        self._on_chat_workspace()
        if conv_id != self.conversation_id and self._on_switch_conversation:
            self._on_switch_conversation(conv_id)
        else:
            self._refresh_goal_state()

    def update_conversation_list(self, conversations: List[Dict[str, Any]]):
        if self._conversation_list is None:
            return

        self._conversation_list.clear()
        current_title = "新对话"

        for conv in conversations:
            item = QListWidgetItem()
            title = (conv.get("title") or "").strip() or "新对话"
            item.setText(title)
            item.setToolTip(title)
            item.setData(Qt.ItemDataRole.UserRole, conv.get("id"))

            if conv.get("id") == self.conversation_id:
                item.setSelected(True)
                current_title = title

            self._conversation_list.addItem(item)

        if self._chat_title_label is not None:
            self._chat_title_label.setText(current_title)
            self._chat_title_label.setToolTip(current_title)
        self._refresh_goal_state()

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

    def set_current_conversation(self, conversation_id: str, messages: List[Dict[str, Any]]):
        self._conversation_id = conversation_id
        self._messages = []
        if self._chat_title_label is not None:
            self._chat_title_label.setText("新对话")

        for msg in messages:
            self._messages.append({"role": msg.get("role"), "content": msg.get("content")})

        self._update_context_status()
        self._refresh_chat_display()
        self._refresh_conversation_list()
        self._refresh_goal_state()

    def is_current_conversation_empty(self) -> bool:
        return len(self._messages) == 0

    def _update_context_status(self):
        """更新上下文状态栏 (token 使用量 / 上下文上限)。"""
        if self._context_label is None:
            return  # UI 尚未初始化
        from llm_chat.utils.token_counter import count_tokens, get_context_limit

        # 对话历史 token 计数（跳过卡片消息，它们没有 content 字段）
        history = [
            {"role": m["role"], "content": m.get("content", "")}
            for m in self._messages
            if m.get("role") != "card"
        ]
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

        self._context_label.setText(self._format_context_text(total_tokens, limit, usage_percent))

        if usage_percent < 50:
            color = "#28a745"
        elif usage_percent < 80:
            color = "#ffc107"
        else:
            color = "#dc3545"

        self._context_label.setStyleSheet(f"color: {color}; padding: 2px; font-weight: bold;")

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
                self._cost_label.setText(f"💲 {total_tokens:,} tokens · $" + f"{total_cost:.4f}")
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
            self._config.llm.model if (self._config and hasattr(self._config, "llm")) else "unknown"
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
            params["reasoning_effort"] = reasoning_levels[self._reasoning_combo.currentIndex()]

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
            self._streaming_browser.setHtml('<span style="color:#8B7355;">● ● ●</span>')

        current_conv_id = self.conversation_id
        model_params = self._get_model_params()
        try:
            current_goal = self._conversation_goal()
        except Exception:
            logger.debug("Failed to resolve conversation goal for turn", exc_info=True)
            current_goal = None

        def stream_response():
            try:
                chat_core = self._chat_core
                if chat_core is None:
                    self._stream_signals.error_occurred.emit(current_conv_id, "ChatCore 未初始化")
                    return

                run_context = {}
                if current_goal is not None:
                    from llm_chat.runtime import RunType

                    run_context = {
                        "work_item_id": current_goal.id,
                        "run_type": RunType.WORKFLOW,
                    }
                full_text = chat_core.send_message_stream(
                    conversation_id=current_conv_id,
                    message=message,
                    on_chunk=lambda text: self._stream_signals.text_received.emit(text),
                    on_tool_start=lambda name, args: self._stream_signals.tool_call_started.emit(
                        name, args
                    ),
                    on_tool_end=lambda name, args, result: self._stream_signals.tool_call_finished.emit(
                        name, args, result
                    ),
                    on_context_update=lambda used, limit: self._stream_signals.context_updated.emit(
                        used, limit
                    ),
                    on_card=lambda card: self._card_signals.card_created.emit(card),
                    **run_context,
                    **model_params,
                )
                if current_goal is not None and hasattr(
                    self._app_instance,
                    "finalize_work_item_result",
                ):
                    self._app_instance.finalize_work_item_result(current_goal.id)
                self._stream_signals.stream_finished.emit(current_conv_id, full_text)
            except Exception as e:
                self._stream_signals.error_occurred.emit(current_conv_id, str(e))

        self._worker_thread = threading.Thread(target=stream_response, daemon=True)
        self._worker_thread.start()

    def _display_user_message(self, content: str):
        if self._chat_layout is None:
            return

        escaped = self._escape_html(content)

        # 用户输入作为中性浮层，品牌色不再占据大面积阅读区域。
        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        outer = QHBoxLayout(wrapper)
        outer.setContentsMargins(96, 5, 0, 5)
        outer.addStretch()

        bubble = QLabel(f"<div style='color:{Colors.TEXT_PRIMARY};'>{escaped}</div>")
        bubble.setTextFormat(Qt.TextFormat.RichText)
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble.setStyleSheet(
            f"""
            background-color: {Colors.SURFACE_RAISED};
            color: {Colors.TEXT_PRIMARY};
            border: 1px solid {Colors.BORDER};
            border-radius: 14px;
            padding: 10px 14px;
            font-size: 14px;
        """
        )
        bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        bubble.setMaximumWidth(720)
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
        """开始一条助手消息，不额外渲染重复的品牌头部。"""
        self._dismiss_welcome_state()
        self._streaming_browser = None

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
            html_content += (
                f'<span style="color:{Colors.PRIMARY}; animation:blink 1s infinite;">▌</span>'
            )
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
        self._refresh_goal_state()
        self._update_execution_center_indicator()

    def _on_stream_error(self, conv_id: str, error: str):
        if conv_id != self.conversation_id:
            return

        self._is_streaming = False
        self._streaming_conversation_id = None
        self.display_error(error)
        self._set_input_state(True)
        self._refresh_goal_state()

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
                    logger.info(f"调用 widget.set_result, result_len={len(result) if result else 0}")
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
            conv = app.conversation_manager.create_conversation(title=f"\U0001f4a1 每日话题 {today}")
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
            self._context_label.setStyleSheet(f"color: {color}; padding: 2px; font-weight: bold;")
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
        """滚动到底部。使用 QTimer 延迟，避免 processEvents 重入。"""
        if self._chat_scroll_area:
            from PyQt6.QtCore import QTimer

            scrollbar = self._chat_scroll_area.verticalScrollBar()
            # 统一用延迟滚动，避免 processEvents 导致主线程卡死
            delay = 100 if force_layout else 50
            QTimer.singleShot(delay, lambda: scrollbar.setValue(scrollbar.maximum()))

    def _clear_chat_widgets(self):
        if self._chat_layout is None:
            return

        self._welcome_widgets.clear()
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
        """空态：只呈现一个目标和少量可选起点。"""
        if self._chat_layout is None:
            return

        self._dismiss_welcome_state()

        logo = QLabel("V")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(40, 40)
        logo.setStyleSheet(
            f"""
            font-size: 16px;
            font-weight: 700;
            color: {Colors.ACTION_TEXT};
            background: {Colors.ACTION_BG};
            border-radius: 12px;
            margin-top: 42px;
            """
        )
        logo_wrapper = QWidget()
        logo_wrapper.setStyleSheet("background:transparent;")
        logo_row = QHBoxLayout(logo_wrapper)
        logo_row.setContentsMargins(0, 42, 0, 6)
        logo_row.addStretch()
        logo_row.addWidget(logo)
        logo_row.addStretch()
        self._add_widget_to_chat(logo_wrapper)
        self._welcome_widgets.append(logo_wrapper)

        title = QLabel("今天想完成什么？")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"""
            font-size: 22px; font-weight: 650;
            color: {Colors.TEXT_PRIMARY};
            background: transparent;
            margin-bottom: 4px;
        """
        )
        self._add_widget_to_chat(title)
        self._welcome_widgets.append(title)

        subtitle = QLabel("描述目标，Vermilion 会规划、执行并在需要时向你确认。")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(
            f"""
            font-size: 12px;
            color: {Colors.TEXT_MUTED};
            background: transparent;
            margin-bottom: 18px;
        """
        )
        self._add_widget_to_chat(subtitle)
        self._welcome_widgets.append(subtitle)

        shortcuts = [
            ("检查项目", "检查当前项目，给出架构、功能和实现上的优化建议"),
            ("实现功能", "阅读当前项目并实现下面这个功能："),
            ("规划任务", "把下面的目标拆解成可持续执行的任务："),
        ]

        shortcut_row = QWidget()
        shortcut_row.setStyleSheet("background: transparent;")
        row = QHBoxLayout(shortcut_row)
        row.setSpacing(8)
        row.setContentsMargins(72, 0, 72, 0)

        for label, prompt in shortcuts:
            card = QPushButton(label)
            card.setFixedHeight(34)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: transparent;
                    border: 1px solid {Colors.CHAT_BORDER};
                    border-radius: 9px;
                    padding: 5px 13px;
                    font-size: 11px;
                    color: {Colors.TEXT_SECONDARY};
                }}
                QPushButton:hover {{
                    background-color: {Colors.SURFACE_HOVER};
                    border-color: {Colors.BORDER_STRONG};
                    color: {Colors.TEXT_PRIMARY};
                }}
            """
            )
            card.clicked.connect(lambda checked, p=prompt: self._fill_prompt(p))
            row.addWidget(card)

        self._add_widget_to_chat(shortcut_row)
        self._welcome_widgets.append(shortcut_row)
        self._scroll_to_bottom(force_layout=True)

    def _dismiss_welcome_state(self):
        """首条真实内容出现时，只移除空态，不扰动现有消息。"""
        if self._chat_layout is None or not self._welcome_widgets:
            return

        for widget in self._welcome_widgets:
            widget.hide()
            self._chat_layout.removeWidget(widget)
            widget.deleteLater()
        self._welcome_widgets.clear()

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
        if self._task_workspace is not None:
            self._task_workspace.close()
        if self._task_center_dialog is not None:
            self._task_center_dialog.close()
        if self._execution_center_dialog is not None:
            self._execution_center_dialog.close()
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
        if self._task_workspace is not None:
            self._task_workspace.close()
        if self._task_center_dialog is not None:
            self._task_center_dialog.close()
        if self._execution_center_dialog is not None:
            self._execution_center_dialog.close()
        if self._execution_center_timer is not None:
            self._execution_center_timer.stop()
        if self._app:
            self._app.quit()

    # ── LaTeX → HTML 渲染 ──────────────────────────────────────────

    # 常见 LaTeX 命令 → Unicode / HTML 映射
    _LATEX_SYMBOLS = {
        # 希腊字母
        r"\alpha": "α",
        r"\beta": "β",
        r"\gamma": "γ",
        r"\delta": "δ",
        r"\epsilon": "ε",
        r"\zeta": "ζ",
        r"\eta": "η",
        r"\theta": "θ",
        r"\iota": "ι",
        r"\kappa": "κ",
        r"\lambda": "λ",
        r"\mu": "μ",
        r"\nu": "ν",
        r"\xi": "ξ",
        r"\pi": "π",
        r"\rho": "ρ",
        r"\sigma": "σ",
        r"\tau": "τ",
        r"\upsilon": "υ",
        r"\phi": "φ",
        r"\chi": "χ",
        r"\psi": "ψ",
        r"\omega": "ω",
        r"\Gamma": "Γ",
        r"\Delta": "Δ",
        r"\Theta": "Θ",
        r"\Lambda": "Λ",
        r"\Xi": "Ξ",
        r"\Pi": "Π",
        r"\Sigma": "Σ",
        r"\Phi": "Φ",
        r"\Psi": "Ψ",
        r"\Omega": "Ω",
        # 运算符 & 关系
        r"\times": "×",
        r"\cdot": "·",
        r"\div": "÷",
        r"\pm": "±",
        r"\mp": "∓",
        r"\approx": "≈",
        r"\equiv": "≡",
        r"\neq": "≠",
        r"\leq": "≤",
        r"\geq": "≥",
        r"\ll": "≪",
        r"\gg": "≫",
        r"\propto": "∝",
        r"\sim": "∼",
        r"\simeq": "≃",
        r"\to": "→",
        r"\rightarrow": "→",
        r"\leftarrow": "←",
        r"\Rightarrow": "⇒",
        r"\Leftrightarrow": "⇔",
        r"\uparrow": "↑",
        r"\downarrow": "↓",
        # 集合 & 逻辑
        r"\forall": "∀",
        r"\exists": "∃",
        r"\in": "∈",
        r"\notin": "∉",
        r"\subset": "⊂",
        r"\subseteq": "⊆",
        r"\cup": "∪",
        r"\cap": "∩",
        r"\emptyset": "∅",
        r"\infty": "∞",
        r"\partial": "∂",
        r"\nabla": "∇",
        r"\int": "∫",
        r"\sum": "∑",
        r"\prod": "∏",
        r"\sqrt": "√",
        # 杂项
        r"\ldots": "…",
        r"\cdots": "⋯",
        r"\vdots": "⋮",
        r"\ddots": "⋱",
        r"\angle": "∠",
        r"\degree": "°",
        r"\triangle": "△",
        r"\circ": "∘",
        r"\bullet": "•",
        r"\star": "★",
        # 间距
        r"\quad": "  ",
        r"\qquad": "    ",
        r"\,": " ",
        r"\;": "  ",
    }

    @classmethod
    def _render_latex_block(cls, latex: str) -> str:
        """将单个 LaTeX 块转换为 HTML。

        处理顺序：
        1. \\text{...} → 普通文本
        2. \\frac{a}{b} → 带分数线的 HTML
        3. ^{...} / _{...} → <sup>/<sub>
        4. 常见命令 → Unicode 符号
        5. 残留反斜杠命令 → 移除反斜杠
        """
        import re

        result = latex.strip()

        # 1. \text{...} → 提取内部文本
        def _text_replacer(m: re.Match) -> str:
            inner = m.group(1)
            # 递归处理嵌套 LaTeX
            return cls._render_latex_inner(inner)

        result = re.sub(r"\\text\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}", _text_replacer, result)
        # 也处理 \mathrm{...}, \mathbf{...} 等
        result = re.sub(
            r"\\(?:mathrm|mathbf|mathit|mathsf|mathtt)\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}",
            _text_replacer,
            result,
        )

        # 2. \frac{a}{b} → 带样式的分数
        def _frac_replacer(m: re.Match) -> str:
            num = cls._render_latex_inner(m.group(1))
            den = cls._render_latex_inner(m.group(2))
            return f'<span class="math-frac"><sup>{num}</sup><span>/</span><sub>{den}</sub></span>'

        result = re.sub(
            r"\\frac\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}"
            r"\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}",
            _frac_replacer,
            result,
        )

        # 3. ^{...} / _{...} → sup/sub
        result = re.sub(
            r"\^\{((?:[^{}]|\{[^{}]*\})*)\}",
            lambda m: f"<sup>{cls._render_latex_inner(m.group(1))}</sup>",
            result,
        )
        result = re.sub(
            r"_\{((?:[^{}]|\{[^{}]*\})*)\}",
            lambda m: f"<sub>{cls._render_latex_inner(m.group(1))}</sub>",
            result,
        )

        # 4. 常见 LaTeX 命令 → Unicode
        for cmd, symbol in sorted(cls._LATEX_SYMBOLS.items(), key=lambda x: -len(x[0])):
            result = result.replace(cmd, symbol)

        # 5. 转义字符 \% \$ \# \_ \{ \} \& → 对应字符
        result = result.replace(r"\%", "%")
        result = result.replace(r"\$", "$")
        result = result.replace(r"\#", "#")
        result = result.replace(r"\_", "_")
        result = result.replace(r"\{", "{")
        result = result.replace(r"\}", "}")
        result = result.replace(r"\&", "&")

        # 6. 残留反斜杠命令 → 移除反斜杠 (如 \FCF → FCF)
        result = re.sub(r"\\([a-zA-Z]+)", r"\1", result)

        return result

    @classmethod
    def _render_latex_inner(cls, latex: str) -> str:
        """渲染内联 LaTeX（不包裹外层 div）。"""
        import re

        result = latex.strip()
        # 应用符号替换
        for cmd, symbol in sorted(cls._LATEX_SYMBOLS.items(), key=lambda x: -len(x[0])):
            result = result.replace(cmd, symbol)
        result = re.sub(r"\\([a-zA-Z]+)", r"\1", result)
        # 处理 sup/sub
        result = re.sub(
            r"\^\{((?:[^{}]|\{[^{}]*\})*)\}", lambda m: f"<sup>{m.group(1)}</sup>", result
        )
        result = re.sub(
            r"_\{((?:[^{}]|\{[^{}]*\})*)\}", lambda m: f"<sub>{m.group(1)}</sub>", result
        )
        return result

    @classmethod
    def _preprocess_latex(cls, text: str) -> str:
        """预处理文本中的 LaTeX 数学公式，转换为 HTML。

        - $$...$$ → display math block
        - $...$   → inline math
        """
        import re

        # 先处理 $$...$$ 显示公式
        def _display_replacer(m: re.Match) -> str:
            inner = m.group(1)
            html = cls._render_latex_block(inner)
            return f'<div class="math-block">{html}</div>'

        text = re.sub(r"\$\$(.+?)\$\$", _display_replacer, text, flags=re.DOTALL)

        # 再处理 $...$ 内联公式
        def _inline_replacer(m: re.Match) -> str:
            inner = m.group(1)
            html = cls._render_latex_block(inner)
            return f'<span class="math-inline">{html}</span>'

        text = re.sub(r"\$(.+?)\$", _inline_replacer, text)

        return text

    # ── Markdown 渲染 ─────────────────────────────────────────────

    def _render_markdown(self, text: str) -> str:
        # 0. 预处理 LaTeX → HTML（在 markdown 转换之前）
        text = self._preprocess_latex(text)

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

                    logging.getLogger(__name__).warning(f"Markdown 渲染失败，使用纯文本: {e}")
        return text.replace("\n", "<br>")

    def display_message(self, message: Message):
        if self._chat_layout is None:
            return

        self._dismiss_welcome_state()
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

        self._dismiss_welcome_state()
        error_label = QLabel(
            f"<span style='color:{Colors.ERROR_TEXT};'>运行失败：{self._escape_html(error)}</span>"
        )
        error_label.setWordWrap(True)
        error_label.setTextFormat(Qt.TextFormat.RichText)
        error_label.setStyleSheet(error_label_style())
        self._add_widget_to_chat(error_label)
        self._scroll_to_bottom(force_layout=True)

    def display_info(self, info: str):
        if self._chat_layout is None:
            return
        if info == "服务就绪":
            if self._model_combo is not None:
                self._model_combo.setToolTip("服务已就绪")
            return

        self._dismiss_welcome_state()
        info_label = QLabel(
            f"<span style='color:{Colors.TEXT_MUTED};'>{self._escape_html(info)}</span>"
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
            self._dismiss_welcome_state()
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
            f"background-color:{Colors.BORDER}; max-height:1px; margin:10px 0;"
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
            store.record(
                card_id=card_id,
                card_type="decision",
                title=f"card:{card_id}",
                selected_option_id=option_id,
            )
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

    def _create_conversation_from_card(self, card: DecisionCard, selected):
        """从卡片选项创建新对话并立即触发 LLM 响应。"""
        app = self._app_instance
        if not app:
            return

        option_text = f"{card.title} — {selected.label}"
        conv = app.conversation_manager.create_conversation(title=option_text[:80])

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
            f"<span style='color:{Colors.TEXT_MUTED}; font-style:italic;'>卡片已暂缓</span>"
        )
        info.setStyleSheet("padding: 4px 8px; margin: 2px 0;")
        self._add_widget_to_chat(info)
        self._scroll_to_bottom(force_layout=True)

    @property
    def conversation_id(self) -> str:
        return self._conversation_id if hasattr(self, "_conversation_id") else "default"

    def request_rename_input(self, conversation_id: str, current_title: str) -> Optional[str]:
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
