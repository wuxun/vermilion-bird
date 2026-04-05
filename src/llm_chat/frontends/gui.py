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

logger = logging.getLogger(__name__)

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
    QScrollArea = None
    QSizePolicy = None
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


MARKDOWN_CSS = """
<style>
    body { font-family: Arial, sans-serif; line-height: 1.6; color: #3D2C2E; }
    h1 { color: #B8312F; border-bottom: 2px solid #C84B31; padding-bottom: 5px; }
    h2 { color: #C84B31; border-bottom: 1px solid #EC994B; padding-bottom: 5px; }
    h3 { color: #D4652F; }
    code { background-color: #FFF3E6; padding: 2px 6px; border-radius: 3px; font-family: Consolas, monospace; color: #8B4513; }
    pre { background-color: #2D2D2D; padding: 10px; border-radius: 5px; overflow-x: auto; }
    pre code { background-color: transparent; padding: 0; color: #F5E6D3; }
    blockquote { border-left: 4px solid #C84B31; margin-left: 0; padding-left: 15px; color: #6B4423; background-color: #FFF8F0; }
    ul, ol { padding-left: 20px; }
    li { margin: 5px 0; }
    table { border-collapse: collapse; width: 100%; margin: 10px 0; }
    th, td { border: 1px solid #D4A574; padding: 8px; text-align: left; }
    th { background-color: #F5E6D3; color: #6B4423; }
    a { color: #B8312F; text-decoration: none; }
    a:hover { text-decoration: underline; color: #C84B31; }
</style>
"""

if PYQT_AVAILABLE:

    class InputTextEdit(QTextEdit):
        send_requested = pyqtSignal()

        def keyPressEvent(self, event):
            if event.key() == Qt.Key.Key_Return and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                self.send_requested.emit()
                event.accept()
                return
            super().keyPressEvent(event)

    class CollapsibleToolCall(QFrame):
        toggled = pyqtSignal(bool)

        def __init__(self, tool_id: str, tool_name: str, tool_args: str, parent=None):
            super().__init__(parent)
            self._tool_id = tool_id
            self._tool_name = tool_name
            self._tool_args = tool_args
            self._result = None
            self._is_expanded = True
            self._is_completed = False
            self._setup_ui()

        def _setup_ui(self):
            self.setFrameShape(QFrame.Shape.StyledPanel)
            self.setStyleSheet("""
                CollapsibleToolCall {
                    background-color: #F3E5F5;
                    border: 1px solid #9C27B0;
                    border-radius: 8px;
                    margin: 4px 0px;
                }
            """)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self._header = QPushButton()
            self._header.setStyleSheet("""
                QPushButton {
                    background-color: #E1BEE7;
                    border: none;
                    border-radius: 8px 8px 0 0;
                    padding: 8px 12px;
                    text-align: left;
                    font-weight: bold;
                    color: #7B1FA2;
                }
                QPushButton:hover {
                    background-color: #CE93D8;
                }
            """)
            self._header.clicked.connect(self._toggle)
            self._update_header_text()
            layout.addWidget(self._header)

            self._content = QWidget()
            self._content.setStyleSheet(
                "background-color: #FFFFFF; border-radius: 0 0 8px 8px;"
            )
            content_layout = QVBoxLayout(self._content)
            content_layout.setContentsMargins(12, 10, 12, 10)
            content_layout.setSpacing(8)

            args_label = QLabel("参数:")
            args_label.setStyleSheet(
                "color: #7B1FA2; font-weight: bold; border: none; background: transparent;"
            )
            content_layout.addWidget(args_label)

            self._args_text = QTextEdit()
            self._args_text.setPlainText(self._tool_args)
            self._args_text.setReadOnly(True)
            self._args_text.setMaximumHeight(120)
            self._args_text.setStyleSheet("""
                QTextEdit {
                    background-color: #F5F5F5;
                    border-radius: 4px;
                    border: none;
                    padding: 8px;
                    font-family: Consolas, monospace;
                    font-size: 12px;
                    color: #4A148C;
                }
            """)
            content_layout.addWidget(self._args_text)

            self._result_label = QLabel("结果:")
            self._result_label.setStyleSheet(
                "color: #2E7D32; font-weight: bold; border: none; background: transparent;"
            )
            self._result_label.hide()
            content_layout.addWidget(self._result_label)

            self._result_text = QTextEdit()
            self._result_text.setReadOnly(True)
            self._result_text.setMaximumHeight(150)
            self._result_text.setStyleSheet("""
                QTextEdit {
                    background-color: #E8F5E9;
                    border-radius: 4px;
                    border-left: 3px solid #4CAF50;
                    padding: 8px;
                    font-family: Consolas, monospace;
                    font-size: 11px;
                    color: #2E7D32;
                }
            """)
            self._result_text.hide()
            content_layout.addWidget(self._result_text)

            layout.addWidget(self._content)

        def _update_header_text(self):
            if self._is_completed:
                icon = "✅"
                status = ""
            else:
                icon = "🔧"
                status = " ▼ 执行中..."

            expand_icon = "▼" if self._is_expanded else "▶"
            self._header.setText(
                f"{expand_icon} {icon} 工具调用: {self._tool_name}{status}"
            )

        def _toggle(self):
            self._is_expanded = not self._is_expanded
            self._content.setVisible(self._is_expanded)
            self._update_header_text()
            self.toggled.emit(self._is_expanded)
            logger.info(
                f"工具调用控件折叠状态切换: {self._tool_name}, expanded={self._is_expanded}"
            )

        def set_result(self, result: str):
            self._result = result if result else "无返回结果"
            self._is_completed = True
            self._result_text.setPlainText(self._result)
            self._result_label.show()
            self._result_text.show()
            self._update_header_text()
            self.collapse()
            logger.info(f"工具调用完成并自动折叠: {self._tool_name}")

        def collapse(self):
            self._is_expanded = False
            self._content.setVisible(False)
            self._update_header_text()

        def expand(self):
            self._is_expanded = True
            self._content.setVisible(True)
            self._update_header_text()

        @property
        def tool_id(self) -> str:
            return self._tool_id

        @property
        def tool_name(self) -> str:
            return self._tool_name

        @property
        def result(self) -> str:
            return self._result or ""
else:
    InputTextEdit = None
    CollapsibleToolCall = None

if PYQT_AVAILABLE:

    class StreamSignals(QObject):
        text_received = pyqtSignal(str)
        stream_finished = pyqtSignal(str, str)
        error_occurred = pyqtSignal(str, str)
        tool_call_started = pyqtSignal(str, str)
        tool_call_finished = pyqtSignal(str, str, str)
        context_updated = pyqtSignal(int, int)

    class ConversationListSignals(QObject):
        conversations_updated = pyqtSignal()
else:
    StreamSignals = None
    ConversationListSignals = None


class GUIFrontend(BaseFrontend):
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
        self._app_instance: Optional[Any] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._stream_signals: Optional[StreamSignals] = None
        self._conv_list_signals: Optional[ConversationListSignals] = None
        self._current_stream_text: str = ""
        self._streaming_label: Optional[QLabel] = None
        self._streaming_browser: Optional[QTextBrowser] = None
        self._messages: list = []
        self._current_tool_calls: list = []
        self._current_tool_call_widgets: Dict[str, CollapsibleToolCall] = {}
        self._is_streaming: bool = False
        self._streaming_conversation_id: Optional[str] = None
        self._storage: Optional[Any] = None

        self._conversation_list: Optional[QListWidget] = None
        self._new_conv_button: Optional[QPushButton] = None
        self._delete_conv_button: Optional[QPushButton] = None
        self._rename_conv_button: Optional[QPushButton] = None
        self._context_label: Optional[QLabel] = None
        self._current_model: str = "gpt-3.5-turbo"

        self._on_new_conversation: Optional[Callable] = None
        self._on_delete_conversation: Optional[Callable] = None
        self._on_rename_conversation: Optional[Callable] = None
        self._on_switch_conversation: Optional[Callable] = None
        self._on_list_conversation: Optional[Callable] = None
        self._config: Optional[Any] = None
        self._model_combo: Optional[QComboBox] = None
        self._scheduler_button: Optional[QPushButton] = None
        self._scheduler_dialog = None

    def set_storage(self, storage: Any):
        self._storage = storage

    def set_config(self, config: Any):
        self._config = config

    def set_app(self, app: Any):
        self._app_instance = app

    def _init_model_combo(self):
        if self._model_combo is None:
            return
        self._model_combo.clear()
        if self._config is None:
            self._model_combo.addItem(self._current_model)
            self._model_combo.setCurrentText(self._current_model)
            return
        available_models = getattr(self._config.llm, "available_models", [])
        if available_models:
            for model_info in available_models:
                if hasattr(model_info, "name"):
                    model_name = model_info.name
                elif hasattr(model_info, "get"):
                    model_name = model_info.get("id")
                else:
                    model_name = str(model_info)
                self._model_combo.addItem(model_name)
            current_model = self._config.llm.model
            index = self._model_combo.findText(current_model)
            if index >= 0:
                self._model_combo.setCurrentIndex(index)
            else:
                self._model_combo.setCurrentText(current_model)
        else:
            self._model_combo.addItem(self._current_model)
            self._model_combo.setCurrentText(self._current_model)

    def _on_model_changed(self, index: int):
        if self._config is None or self._model_combo is None:
            return
        model_name = self._model_combo.currentText()
        old_model = self._config.llm.model
        if model_name == old_model:
            return
        available_models = getattr(self._config.llm, "available_models", [])
        model_id = model_name
        selected_model_info = None
        if available_models:
            for model_info in available_models:
                info_name = (
                    model_info.name
                    if hasattr(model_info, "name")
                    else (
                        model_info.get("name")
                        if hasattr(model_info, "get")
                        else str(model_info)
                    )
                )
                if info_name == model_name:
                    model_id = (
                        model_info.id
                        if hasattr(model_info, "id")
                        else (
                            model_info.get("id")
                            if hasattr(model_info, "get")
                            else model_name
                        )
                    )
                    selected_model_info = model_info
                    break
        self._config.llm.model = model_id
        self._current_model = model_id
        if selected_model_info:
            if (
                hasattr(selected_model_info, "base_url")
                and selected_model_info.base_url
            ):
                self._config.llm.base_url = selected_model_info.base_url
            if hasattr(selected_model_info, "api_key") and selected_model_info.api_key:
                self._config.llm.api_key = selected_model_info.api_key
            if (
                hasattr(selected_model_info, "protocol")
                and selected_model_info.protocol
            ):
                self._config.llm.protocol = selected_model_info.protocol
        logger.info(f"模型切换: {old_model} -> {model_id}")
        self._save_config()

    def _save_config(self):
        if self._config is None:
            return
        try:
            self._config.to_yaml()
            logger.info("配置已保存到 config.yaml")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

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

    def start(self):
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

        self._main_window = QMainWindow()
        self._main_window.setWindowTitle(self._title)
        self._main_window.setMinimumSize(QSize(1000, 600))

        self._set_window_icon()

        central_widget = QWidget()
        self._main_window.setCentralWidget(central_widget)

        self._setup_ui(central_widget)
        self._apply_styles()

        self._init_model_combo()

        self._main_window.closeEvent = self._on_close_event

        self._refresh_conversation_list()

        self.display_info("Welcome to Vermilion Bird!")
        self.display_info("Press Enter to send, Shift+Enter for new line")

        self._main_window.show()
        # If there are preloaded messages (set_current_conversation called before start),
        # render them now that the UI is constructed.
        try:
            if (
                hasattr(self, "_messages")
                and isinstance(self._messages, list)
                and len(self._messages) > 0
            ):
                self._refresh_chat_display()
                self._scroll_to_bottom()
        except Exception:
            # Ignore UI rendering errors here; proceed to start the event loop.
            pass
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

        sidebar = self._create_sidebar()
        main_layout.addWidget(sidebar)

        chat_area = self._create_chat_area()
        main_layout.addWidget(chat_area, stretch=1)

    def _create_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setFixedWidth(220)
        sidebar.setObjectName("sidebar")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        title_label = QLabel("Conversations")
        title_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)

        button_layout = QHBoxLayout()

        self._new_conv_button = QPushButton("+")
        self._new_conv_button.setFixedSize(30, 30)
        self._new_conv_button.setToolTip("New Conversation")
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

        self._conversation_list = QListWidget()
        self._conversation_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._conversation_list.itemClicked.connect(self._on_conversation_selected)
        layout.addWidget(self._conversation_list, stretch=1)

        return sidebar

    def _create_chat_area(self) -> QWidget:
        chat_area = QFrame()
        chat_area.setObjectName("chatArea")

        layout = QVBoxLayout(chat_area)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        header_layout = QHBoxLayout()

        title_label = QLabel("Vermilion Bird")
        title_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        self._mcp_button = QPushButton("MCP Tools")
        self._mcp_button.setFixedWidth(100)
        self._mcp_button.clicked.connect(self._on_mcp_config)
        header_layout.addWidget(self._mcp_button)

        self._skills_button = QPushButton("Skills")
        self._skills_button.setFixedWidth(100)
        self._skills_button.clicked.connect(self._on_skills_config)
        header_layout.addWidget(self._skills_button)

        self._models_button = QPushButton("Models")
        self._models_button.setFixedWidth(100)
        self._models_button.clicked.connect(self._on_models_config)
        header_layout.addWidget(self._models_button)

        self._scheduler_button = QPushButton("Scheduler")
        self._scheduler_button.setFixedWidth(100)
        self._scheduler_button.clicked.connect(self._on_scheduler_config)
        header_layout.addWidget(self._scheduler_button)

        self._clear_button = QPushButton("Clear")
        self._clear_button.setFixedWidth(80)
        self._clear_button.clicked.connect(self._on_clear)
        header_layout.addWidget(self._clear_button)

        layout.addLayout(header_layout)

        self._context_label = QLabel("上下文: 0 / 4096 tokens (0.0%)")
        self._context_label.setFont(QFont("Arial", 10))
        self._context_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._context_label)

        self._chat_scroll_area = QScrollArea()
        self._chat_scroll_area.setWidgetResizable(True)
        self._chat_scroll_area.setFrameShape(QFrame.Shape.StyledPanel)
        self._chat_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._chat_container = QWidget()
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(10, 10, 10, 10)
        self._chat_layout.setSpacing(10)
        self._chat_layout.addStretch()

        self._chat_scroll_area.setWidget(self._chat_container)
        layout.addWidget(self._chat_scroll_area, stretch=1)

        self._chat_display = QTextBrowser()
        self._chat_display.setReadOnly(True)
        self._chat_display.setFont(QFont("Arial", 11))
        self._chat_display.setFrameShape(QFrame.Shape.NoFrame)
        self._chat_display.setOpenExternalLinks(True)
        self._chat_display.setMaximumHeight(0)
        self._chat_display.hide()

        params_container = QWidget()
        params_container.setStyleSheet("""
            QWidget {
                background-color: #F5E6D3;
                border: 1px solid #D4A574;
                border-radius: 4px;
                padding: 2px;
            }
            QLabel {
                color: #4A2C2A;
                font-size: 11px;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #D4A574;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #8B4513;
                width: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QComboBox {
                background-color: white;
                border: 1px solid #D4A574;
                border-radius: 3px;
                padding: 2px 5px;
                color: #4A2C2A;
            }
            QComboBox::drop-down {
                border: none;
            }
        """)
        params_layout = QHBoxLayout(params_container)
        params_layout.setContentsMargins(8, 3, 8, 3)
        params_layout.setSpacing(10)

        temp_label = QLabel("温度:")
        params_layout.addWidget(temp_label)

        self._temperature_slider = QSlider(Qt.Orientation.Horizontal)
        self._temperature_slider.setMinimum(0)
        self._temperature_slider.setMaximum(20)
        self._temperature_slider.setValue(7)
        self._temperature_slider.setFixedWidth(80)
        self._temperature_slider.valueChanged.connect(self._on_temperature_changed)
        params_layout.addWidget(self._temperature_slider)

        self._temperature_value = QLabel("0.7")
        self._temperature_value.setFixedWidth(25)
        params_layout.addWidget(self._temperature_value)

        params_layout.addSpacing(10)

        reasoning_label = QLabel("推理:")
        params_layout.addWidget(reasoning_label)

        self._reasoning_combo = QComboBox()
        self._reasoning_combo.addItems(["关闭", "低", "中", "高"])
        self._reasoning_combo.setCurrentIndex(0)
        self._reasoning_combo.setFixedWidth(60)
        self._reasoning_combo.currentIndexChanged.connect(self._on_reasoning_changed)
        params_layout.addWidget(self._reasoning_combo)

        params_layout.addSpacing(15)

        model_label = QLabel("模型:")
        params_layout.addWidget(model_label)

        self._model_combo = QComboBox()
        self._model_combo.setFixedWidth(150)
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        params_layout.addWidget(self._model_combo)

        params_layout.addStretch()

        self._params_container = params_container
        layout.addWidget(params_container)

        input_container = QVBoxLayout()
        input_container.setSpacing(5)

        input_label = QLabel("Message:")
        input_container.addWidget(input_label)

        input_row = QHBoxLayout()

        self._input_field = InputTextEdit()
        self._input_field.setMaximumHeight(100)
        self._input_field.setFont(QFont("Arial", 11))
        self._input_field.setPlaceholderText("Type your message here...")
        self._input_field.send_requested.connect(self._on_send)
        input_row.addWidget(self._input_field, stretch=1)

        button_column = QVBoxLayout()
        button_column.setSpacing(5)

        self._send_button = QPushButton("Send")
        self._send_button.setFixedSize(80, 35)
        self._send_button.clicked.connect(self._on_send)
        self._send_button.setDefault(True)
        button_column.addWidget(self._send_button)

        exit_button = QPushButton("Exit")
        exit_button.setFixedSize(80, 35)
        exit_button.clicked.connect(self._on_close)
        button_column.addWidget(exit_button)

        input_row.addLayout(button_column)
        input_container.addLayout(input_row)

        layout.addLayout(input_container)

        return chat_area

    def _apply_styles(self):
        self._main_window.setStyleSheet("""
            QFrame#sidebar {
                background-color: #4A2C2A;
                border-right: 1px solid #3D2422;
            }
            QFrame#chatArea {
                background-color: #FFFBF5;
            }
        """)

        self._chat_display.setStyleSheet("""
            QTextBrowser {
                background-color: #FFF8F0;
                border: none;
                padding: 10px;
                color: #3D2C2E;
            }
        """)

        self._chat_scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #FFF8F0;
                border: 1px solid #E8D5C4;
                border-radius: 8px;
            }
            QWidget {
                background-color: #FFF8F0;
            }
        """)

        self._input_field.setStyleSheet("""
            QTextEdit {
                border: 1px solid #D4A574;
                border-radius: 8px;
                padding: 8px;
                background-color: #FFFCF7;
                color: #3D2C2E;
            }
            QTextEdit:focus {
                border: 2px solid #C84B31;
            }
        """)

        self._send_button.setStyleSheet("""
            QPushButton {
                background-color: #C84B31;
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #B8312F;
            }
            QPushButton:disabled {
                background-color: #D4A574;
            }
        """)

        self._clear_button.setStyleSheet("""
            QPushButton {
                background-color: #FFF3E6;
                border: 1px solid #D4A574;
                border-radius: 8px;
                color: #6B4423;
            }
            QPushButton:hover {
                background-color: #F5E6D3;
            }
        """)

        self._mcp_button.setStyleSheet("""
            QPushButton {
                background-color: #D4652F;
                color: white;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #C84B31;
            }
        """)

        self._skills_button.setStyleSheet("""
            QPushButton {
                background-color: #D4652F;
                color: white;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #C84B31;
            }
        """)

        self._models_button.setStyleSheet("""
            QPushButton {
                background-color: #D4652F;
                color: white;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #C84B31;
            }
        """)

        self._scheduler_button.setStyleSheet("""
            QPushButton {
                background-color: #D4652F;
                color: white;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #C84B31;
            }
        """)

        self._conversation_list.setStyleSheet("""
            QListWidget {
                border: none;
                border-radius: 8px;
                background-color: #5C3D3A;
                color: #F5E6D3;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 12px 8px;
                border-bottom: 1px solid #4A2C2A;
                color: #F5E6D3;
            }
            QListWidget::item:selected {
                background-color: #C84B31;
                color: white;
            }
            QListWidget::item:hover:!selected {
                background-color: #6B4D4A;
                color: #F5E6D3;
            }
        """)

        sidebar_title = self._main_window.findChild(QLabel, "sidebar_title")

        for btn in [
            self._new_conv_button,
            self._rename_conv_button,
            self._delete_conv_button,
        ]:
            if btn:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #5C3D3A;
                        border: 1px solid #7A5A56;
                        border-radius: 5px;
                        font-size: 14px;
                        color: #F5E6D3;
                    }
                    QPushButton:hover {
                        background-color: #7A5A56;
                    }
                """)

    def _on_new_conv(self):
        if self._is_streaming:
            self.display_info("Please wait for the current response to finish")
            return

        if self._on_new_conversation:
            self._on_new_conversation()

    def _on_delete_conv(self):
        if self._is_streaming:
            self.display_info("Please wait for the current response to finish")
            return

        if self._on_delete_conversation:
            self._on_delete_conversation(self.conversation_id)

    def _on_rename_conv(self):
        if self._on_rename_conversation:
            self._on_rename_conversation(self.conversation_id)

    def _on_conversation_selected(self, item: QListWidgetItem):
        if self._is_streaming:
            self.display_info("Please wait for the current response to finish")
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
        from llm_chat.utils.token_counter import (
            calculate_context_usage,
            format_context_usage_short,
            count_tokens,
            get_context_limit,
        )

        # 基础对话历史
        history = [{"role": m["role"], "content": m["content"]} for m in self._messages]

        # 计算对话历史的 token
        base_usage = calculate_context_usage(history, self._current_model)
        total_tokens = base_usage["used_tokens"]

        # 计算系统提示词（记忆上下文）的 token
        if self._config and self._config.memory.enabled:
            try:
                from llm_chat.memory import MemoryStorage, MemoryManager
                from llm_chat.client import LLMClient

                memory_storage = MemoryStorage(self._config.memory.storage_dir)
                # 使用临时 client 仅用于 memory manager
                temp_client = LLMClient(self._config, skip_skills_setup=True)
                memory_manager = MemoryManager(
                    storage=memory_storage,
                    db_storage=None,
                    llm_client=temp_client,
                    config={},
                )
                system_context = memory_manager.build_system_prompt()
                if system_context:
                    system_tokens = count_tokens(system_context, self._current_model)
                    # 系统消息格式开销（类似 OpenAI 格式）
                    system_tokens += 4  # {"role": "system", "content": "..."} 格式开销
                    total_tokens += system_tokens
                    logger.debug(f"系统上下文 token: {system_tokens}")
            except Exception as e:
                logger.warning(f"计算系统上下文 token 失败: {e}")

        # 计算工具定义的 token
        if self._config and self._config.enable_tools:
            try:
                from llm_chat.client import LLMClient
                import json

                temp_client = LLMClient(self._config, skip_skills_setup=True)
                if temp_client.has_builtin_tools():
                    tools = temp_client.get_builtin_tools()
                    if tools:
                        # 工具定义序列化为 JSON 计算 token
                        tools_json = json.dumps(tools, ensure_ascii=False)
                        tools_tokens = count_tokens(tools_json, self._current_model)
                        total_tokens += tools_tokens
                        logger.debug(f"工具定义 token: {tools_tokens}")
            except Exception as e:
                logger.warning(f"计算工具定义 token 失败: {e}")

        # 构建完整的使用量信息
        limit = get_context_limit(self._current_model)
        usage_percent = (total_tokens / limit) * 100 if limit > 0 else 0
        usage = {
            "used_tokens": total_tokens,
            "limit": limit,
            "usage_percent": round(usage_percent, 1),
            "remaining_tokens": max(0, limit - total_tokens),
            "model": self._current_model,
        }

        status_text = format_context_usage_short(usage)

        if self._context_label:
            self._context_label.setText(status_text)

            percent = usage["usage_percent"]
            if percent < 50:
                color = "#28a745"
            elif percent < 80:
                color = "#ffc107"
            else:
                color = "#dc3545"

            self._context_label.setStyleSheet(
                f"color: {color}; padding: 2px; font-weight: bold;"
            )

    def _on_temperature_changed(self, value):
        """温度滑块变化处理"""
        temp = value / 10.0
        self._temperature_value.setText(f"{temp:.1f}")
        logger.info(f"温度设置为: {temp}")

    def _on_reasoning_changed(self, index):
        """推理深度变化处理"""
        levels = ["关闭", "低", "中", "高"]
        logger.info(f"推理深度设置为: {levels[index]}")

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

        self._messages.append({"role": "user", "content": content})

        self._update_context_status()

        if self._storage:
            self._storage.add_message(self.conversation_id, "user", content)
            conv = self._storage.get_conversation(self.conversation_id)
            if not conv or not conv.get("title"):
                title = content[:30]
                if len(content) > 30:
                    title += "..."
                self._storage.update_conversation(self.conversation_id, title=title)

        self._display_user_message(content)

        self._set_input_state(False)

        self._current_stream_text = ""
        self._current_tool_calls = []
        self._is_streaming = True
        self._streaming_conversation_id = self.conversation_id

        self._display_ai_prefix()

        current_conv_id = self.conversation_id
        model_params = self._get_model_params()

        def stream_response():
            try:
                from llm_chat.config import Config
                from llm_chat.cli import setup_logging
                from llm_chat.memory import MemoryStorage, MemoryManager

                setup_logging(logging.INFO)

                if self._app_instance:
                    config = self._app_instance.config
                else:
                    config = Config()

                history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in self._messages[:-1]
                ]

                system_context = None
                if config.memory.enabled:
                    try:
                        memory_storage = MemoryStorage(config.memory.storage_dir)
                        memory_manager = MemoryManager(
                            storage=memory_storage,
                            db_storage=None,
                            llm_client=self._app_instance.client
                            if self._app_instance
                            else None,
                            config={},
                        )
                        system_context = memory_manager.build_system_prompt()
                        if system_context:
                            logger.info(f"加载记忆上下文: {len(system_context)} 字符")
                    except Exception as e:
                        logger.warning(f"加载记忆上下文失败: {e}")

                if config.enable_tools and (
                    self._app_instance.client.has_builtin_tools()
                    or (self._app_instance and self._app_instance.has_tools_available())
                ):
                    tools = (
                        self._app_instance.get_available_tools()
                        if self._app_instance
                        else self._app_instance.client.get_builtin_tools()
                    )

                    full_text = ""
                    for chunk in self._app_instance.client.chat_stream_with_tools(
                        content,
                        tools,
                        history,
                        system_context=system_context,
                        **model_params,
                    ):
                        if isinstance(chunk, tuple) and chunk[0] == "tool_call_start":
                            _, tool_name, tool_args = chunk
                            self._stream_signals.tool_call_started.emit(
                                tool_name, tool_args
                            )
                        elif isinstance(chunk, tuple) and chunk[0] == "tool_call_end":
                            _, tool_name, tool_args, result = chunk
                            self._stream_signals.tool_call_finished.emit(
                                tool_name, tool_args, result
                            )
                        elif isinstance(chunk, tuple) and chunk[0] == "context_update":
                            _, used_tokens, limit = chunk
                            self._stream_signals.context_updated.emit(
                                used_tokens, limit
                            )
                        elif isinstance(chunk, str):
                            full_text += chunk
                            self._stream_signals.text_received.emit(chunk)

                    self._stream_signals.stream_finished.emit(
                        current_conv_id, full_text
                    )
                else:
                    full_text = ""
                    for chunk in self._app_instance.client.chat_stream(
                        content, history, system_context=system_context, **model_params
                    ):
                        full_text += chunk
                        self._stream_signals.text_received.emit(chunk)

                    self._stream_signals.stream_finished.emit(
                        current_conv_id, full_text
                    )

            except Exception as e:
                self._stream_signals.error_occurred.emit(current_conv_id, str(e))

        self._worker_thread = threading.Thread(target=stream_response, daemon=True)
        self._worker_thread.start()

    def _display_user_message(self, content: str):
        if self._chat_layout is None:
            return

        user_browser = self._create_message_browser(
            f"<b style='color: #B8312F;'>You:</b> <span style='color: #3D2C2E;'>{content}</span>"
        )
        self._add_widget_to_chat(user_browser)
        self._scroll_to_bottom()

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

        ai_label = QLabel("<b style='color: #D4652F;'>AI:</b>")
        ai_label.setStyleSheet("margin-top: 5px; color: #3D2C2E;")
        self._add_widget_to_chat(ai_label)

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
            html_content = self._render_markdown(self._current_stream_text)
            self._streaming_browser.setHtml(html_content)

        self._scroll_to_bottom()

    def _on_stream_finished(self, conv_id: str, full_text: str):
        if conv_id != self.conversation_id:
            return

        self._is_streaming = False
        self._streaming_conversation_id = None

        tool_calls_data = self._current_tool_calls.copy()
        self._messages.append(
            {"role": "assistant", "content": full_text, "tool_calls": tool_calls_data}
        )

        self._current_tool_calls = []
        self._current_tool_call_widgets.clear()

        self._update_context_status()

        if self._storage:
            self._storage.add_message(conv_id, "assistant", full_text)

        self._extract_memory_async(full_text)

        self._refresh_chat_display()
        self._set_input_state(True)

        self._refresh_conversation_list()

    def _extract_memory_async(self, assistant_response: str):
        """异步处理记忆 - 短期记忆直接写入"""
        if len(self._messages) < 2:
            return

        user_message = None
        for msg in reversed(self._messages[:-1]):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break

        if not user_message:
            return

        def process_memory():
            try:
                from llm_chat.config import Config
                from llm_chat.memory import MemoryStorage, MemoryManager
                from llm_chat.client import LLMClient

                config = Config.from_yaml()
                if not config.memory.enabled:
                    return

                memory_storage = MemoryStorage(config.memory.storage_dir)
                client = LLMClient(config, skip_skills_setup=True)

                memory_manager = MemoryManager(
                    storage=memory_storage,
                    db_storage=None,
                    llm_client=client,
                    config={
                        "extraction_interval": config.memory.extraction_interval,
                        "extraction_time_interval": config.memory.extraction_time_interval,
                        "short_term_max_entries": config.memory.short_term_max_entries,
                    },
                )

                messages = [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": assistant_response},
                ]

                memory_manager.schedule_extraction(messages)
                memory_manager.process_pending_extractions()

                logger.info("记忆处理完成")
            except Exception as e:
                logger.warning(f"记忆处理失败: {e}")

        import threading

        thread = threading.Thread(target=process_memory, daemon=True)
        thread.start()

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
        except:
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

        self._scroll_to_bottom()
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

    def _on_context_updated(self, used_tokens: int, limit: int):
        from llm_chat.utils.token_counter import format_context_usage_short

        usage_percent = (used_tokens / limit) * 100 if limit > 0 else 0
        usage = {
            "used_tokens": used_tokens,
            "limit": limit,
            "usage_percent": round(usage_percent, 1),
            "remaining_tokens": max(0, limit - used_tokens),
            "model": self._current_model,
        }

        status_text = format_context_usage_short(usage)

        if self._context_label:
            self._context_label.setText(status_text)

            percent = usage["usage_percent"]
            if percent < 50:
                color = "#28a745"
            elif percent < 80:
                color = "#ffc107"
            else:
                color = "#dc3545"

            self._context_label.setStyleSheet(
                f"color: {color}; padding: 2px; font-weight: bold;"
            )

        logger.debug(
            f"上下文已更新: {used_tokens}/{limit} tokens ({usage_percent:.1f}%)"
        )

    def _escape_html(self, text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    def _scroll_to_bottom(self):
        if self._chat_scroll_area:
            from PyQt6.QtCore import QCoreApplication

            QCoreApplication.processEvents()
            scrollbar = self._chat_scroll_area.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

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
        browser.setStyleSheet("""
            QTextBrowser {
                padding: 5px;
                background-color: rgba(255,255,255,0.5);
                border-radius: 4px;
                border: none;
                color: #3D2C2E;
            }
            QMenu {
                background-color: #FFFBF5;
                color: #3D2C2E;
                border: 1px solid #D4A574;
            }
            QMenu::item:selected {
                background-color: #D4A574;
                color: white;
            }
        """)
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
                user_browser = self._create_message_browser(
                    f"<b style='color: #B8312F;'>You:</b> <span style='color: #3D2C2E;'>{msg['content']}</span>"
                )
                self._add_widget_to_chat(user_browser)
            elif msg["role"] == "assistant":
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    tool_header = QLabel("🔧 工具调用记录")
                    tool_header.setStyleSheet("""
                        QLabel {
                            padding: 5px 10px;
                            background-color: #F3E5F5;
                            border-left: 3px solid #9C27B0;
                            border-radius: 4px;
                            color: #7B1FA2;
                            font-weight: bold;
                            margin: 5px 0;
                        }
                    """)
                    self._add_widget_to_chat(tool_header)

                    for tc in tool_calls:
                        tc_id = tc.get("id", "")
                        tc_name = tc.get("name", "unknown")
                        tc_args = tc.get("args", "{}")
                        tc_result = tc.get("result", "")

                        tool_widget = CollapsibleToolCall(tc_id, tc_name, tc_args)
                        tool_widget.set_result(tc_result)
                        self._add_widget_to_chat(tool_widget)

                ai_label = QLabel("<b style='color: #D4652F;'>AI:</b>")
                ai_label.setStyleSheet("margin-top: 10px; color: #3D2C2E;")
                self._add_widget_to_chat(ai_label)

                html_content = self._render_markdown(msg["content"])
                content_browser = self._create_message_browser(html_content)
                self._add_widget_to_chat(content_browser)

                separator = QFrame()
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setStyleSheet(
                    "background-color: #D4A574; max-height: 1px; margin: 10px 0;"
                )
                self._add_widget_to_chat(separator)

        self._scroll_to_bottom()

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

    def _on_clear(self):
        ctx = ConversationContext(conversation_id=self.conversation_id)
        self._handle_clear(ctx)

        self._messages = []
        self._current_tool_call_widgets.clear()

        if self._chat_layout:
            self._clear_chat_widgets()

        self.display_info("Conversation cleared")

    def _on_mcp_config(self):
        try:
            from llm_chat.frontends.mcp_dialog import MCPConfigDialog

            if self._mcp_dialog is None:
                self._mcp_dialog = MCPConfigDialog(self._main_window)
            self._mcp_dialog.exec()
        except ImportError as e:
            QMessageBox.warning(
                self._main_window, "Error", f"MCP module not available: {e}"
            )

    def _on_skills_config(self):
        """打开技能管理对话框"""
        try:
            from llm_chat.frontends.skills_dialog import SkillsConfigDialog

            dialog = SkillsConfigDialog(self._main_window)
            dialog.exec()
        except ImportError as e:
            QMessageBox.warning(
                self._main_window, "Error", f"Skills module not available: {e}"
            )

    def _on_models_config(self):
        """打开模型配置对话框"""
        try:
            from llm_chat.frontends.models_dialog import ModelsConfigDialog

            dialog = ModelsConfigDialog(self._main_window, self._config)
            dialog.exec()
            self._init_model_combo()
        except ImportError as e:
            QMessageBox.warning(
                self._main_window, "Error", f"Models module not available: {e}"
            )

    def _on_scheduler_config(self):
        """打开定时任务管理对话框"""
        try:
            from llm_chat.frontends.scheduler_dialog import SchedulerDialog

            if not hasattr(self, "_app_instance") or self._app_instance is None:
                QMessageBox.warning(
                    self._main_window, "Error", "App instance not available"
                )
                return

            if (
                not hasattr(self._app_instance, "scheduler")
                or self._app_instance.scheduler is None
            ):
                QMessageBox.warning(
                    self._main_window,
                    "Error",
                    "Scheduler is disabled or not initialized",
                )
                return

            if self._scheduler_dialog is None:
                self._scheduler_dialog = SchedulerDialog(
                    self._main_window,
                    scheduler=self._app_instance.scheduler,
                    storage=self._storage,
                )
            self._scheduler_dialog.exec()
        except ImportError as e:
            QMessageBox.warning(
                self._main_window, "Error", f"Scheduler module not available: {e}"
            )
        except Exception as e:
            QMessageBox.warning(
                self._main_window, "Error", f"Failed to open scheduler: {str(e)}"
            )
            self._scheduler_dialog.exec()
        except ImportError as e:
            QMessageBox.warning(
                self._main_window, "Error", f"Scheduler module not available: {e}"
            )
        except AttributeError:
            QMessageBox.warning(
                self._main_window, "Error", "Scheduler is not initialized"
            )

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
        if self._input_field:
            self._input_field.setEnabled(enabled)

    def stop(self):
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
            user_browser = self._create_message_browser(
                f"<b style='color: #B8312F;'>You:</b> <span style='color: #3D2C2E;'>{message.content}</span>"
            )
            self._add_widget_to_chat(user_browser)
        elif message.role == "assistant":
            ai_label = QLabel("<b style='color: #D4652F;'>AI:</b>")
            ai_label.setStyleSheet("margin-top: 10px; color: #3D2C2E;")
            self._add_widget_to_chat(ai_label)

            html_content = self._render_markdown(message.content)
            content_browser = self._create_message_browser(html_content)
            self._add_widget_to_chat(content_browser)

            separator = QFrame()
            separator.setFrameShape(QFrame.Shape.HLine)
            separator.setStyleSheet(
                "background-color: #D4A574; max-height: 1px; margin: 10px 0;"
            )
            self._add_widget_to_chat(separator)

        self._scroll_to_bottom()

    def display_error(self, error: str):
        if self._chat_layout is None:
            return

        error_label = QLabel(f"<span style='color: #8B0000;'>Error: {error}</span>")
        error_label.setWordWrap(True)
        error_label.setTextFormat(Qt.TextFormat.RichText)
        error_label.setStyleSheet(
            "padding: 5px; background-color: #FFEBEE; border-radius: 4px; margin: 2px 0; color: #8B0000;"
        )
        self._add_widget_to_chat(error_label)
        self._scroll_to_bottom()

    def display_info(self, info: str):
        if self._chat_layout is None:
            return

        info_label = QLabel(
            f"<span style='color: #6B4423; font-style: italic;'>[{info}]</span>"
        )
        info_label.setWordWrap(True)
        info_label.setTextFormat(Qt.TextFormat.RichText)
        info_label.setStyleSheet(
            "padding: 5px; background-color: rgba(255,255,255,0.5); border-radius: 4px; margin: 2px 0; color: #6B4423;"
        )
        self._add_widget_to_chat(info_label)
        self._scroll_to_bottom()

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
