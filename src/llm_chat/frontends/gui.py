import sys
import threading
import time
import logging
from typing import Optional, List, Dict, Any, Callable
from llm_chat.frontends.base import BaseFrontend, Message, ConversationContext, MessageType

logger = logging.getLogger(__name__)

try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTextEdit, QTextBrowser, QPushButton, QLabel, QFrame, QMessageBox,
        QListWidget, QListWidgetItem, QSplitter, QLineEdit, QInputDialog,
        QAbstractItemView
    )
    from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal, QObject
    from PyQt6.QtGui import QFont, QTextCursor, QKeyEvent
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
    Qt = None
    QTimer = None
    QSize = None
    QFont = None
    QTextCursor = None
    QKeyEvent = None
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


class InputTextEdit(QTextEdit):
    if PYQT_AVAILABLE:
        send_requested = pyqtSignal()
    
    def keyPressEvent(self, event):
        if PYQT_AVAILABLE:
            if event.key() == Qt.Key.Key_Return and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.send_requested.emit()
                event.accept()
                return
        super().keyPressEvent(event)


class StreamSignals(QObject):
    if PYQT_AVAILABLE:
        text_received = pyqtSignal(str)
        stream_finished = pyqtSignal(str, str)
        error_occurred = pyqtSignal(str, str)
        tool_call_received = pyqtSignal(str, str)


class ConversationListSignals(QObject):
    if PYQT_AVAILABLE:
        conversations_updated = pyqtSignal()


class GUIFrontend(BaseFrontend):
    def __init__(self, conversation_id: str = "default", title: str = "Vermilion Bird"):
        BaseFrontend.__init__(self, "gui")
        self.conversation_id = conversation_id
        self.title = title
        
        if not PYQT_AVAILABLE:
            raise ImportError(
                "PyQt6 未安装。GUI 前端需要 PyQt6。\n"
                "请运行: pip install PyQt6\n"
                "或使用 Poetry: poetry add PyQt6"
            )
        
        self._app: Optional[QApplication] = None
        self._main_window: Optional[QMainWindow] = None
        self._chat_display: Optional[QTextBrowser] = None
        self._input_field: Optional[InputTextEdit] = None
        self._send_button: Optional[QPushButton] = None
        self._clear_button: Optional[QPushButton] = None
        self._mcp_button: Optional[QPushButton] = None
        self._mcp_dialog = None
        self._worker_thread: Optional[threading.Thread] = None
        self._stream_signals: Optional[StreamSignals] = None
        self._conv_list_signals: Optional[ConversationListSignals] = None
        self._current_stream_text: str = ""
        self._stream_start_position: int = 0
        self._messages: list = []
        self._is_streaming: bool = False
        self._streaming_conversation_id: Optional[str] = None
        self._storage: Optional[Any] = None
        
        self._conversation_list: Optional[QListWidget] = None
        self._new_conv_button: Optional[QPushButton] = None
        self._delete_conv_button: Optional[QPushButton] = None
        self._rename_conv_button: Optional[QPushButton] = None
        
        self._on_new_conversation: Optional[Callable] = None
        self._on_delete_conversation: Optional[Callable] = None
        self._on_rename_conversation: Optional[Callable] = None
        self._on_switch_conversation: Optional[Callable] = None
        self._on_list_conversations: Optional[Callable] = None
    
    def set_storage(self, storage: Any):
        self._storage = storage
    
    def set_conversation_callbacks(
        self,
        on_new: Callable,
        on_delete: Callable,
        on_rename: Callable,
        on_switch: Callable,
        on_list: Callable
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
        self._stream_signals.tool_call_received.connect(self._on_tool_call)
        
        self._conv_list_signals = ConversationListSignals()
        self._conv_list_signals.conversations_updated.connect(self._refresh_conversation_list)
        
        self._main_window = QMainWindow()
        self._main_window.setWindowTitle(self.title)
        self._main_window.setMinimumSize(QSize(1000, 600))
        
        central_widget = QWidget()
        self._main_window.setCentralWidget(central_widget)
        
        self._setup_ui(central_widget)
        self._apply_styles()
        
        self._main_window.closeEvent = self._on_close_event
        
        self._refresh_conversation_list()
        
        self.display_info("Welcome to Vermilion Bird!")
        self.display_info("Press Enter to send, Shift+Enter for new line")
        
        self._main_window.show()
        sys.exit(self._app.exec())
    
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
        self._conversation_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
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
        
        self._clear_button = QPushButton("Clear")
        self._clear_button.setFixedWidth(80)
        self._clear_button.clicked.connect(self._on_clear)
        header_layout.addWidget(self._clear_button)
        
        layout.addLayout(header_layout)
        
        self._chat_display = QTextBrowser()
        self._chat_display.setReadOnly(True)
        self._chat_display.setFont(QFont("Arial", 11))
        self._chat_display.setFrameStyle(QFrame.Shape.StyledPanel)
        self._chat_display.setOpenExternalLinks(True)
        layout.addWidget(self._chat_display, stretch=1)
        
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
                border: 1px solid #E8D5C4;
                border-radius: 8px;
                padding: 10px;
                color: #3D2C2E;
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
        
        for btn in [self._new_conv_button, self._rename_conv_button, self._delete_conv_button]:
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
    
    def set_current_conversation(self, conversation_id: str, messages: List[Dict[str, Any]]):
        self.conversation_id = conversation_id
        self._messages = []
        
        for msg in messages:
            self._messages.append({
                "role": msg.get("role"),
                "content": msg.get("content")
            })
        
        self._refresh_chat_display()
        self._refresh_conversation_list()
    
    def is_current_conversation_empty(self) -> bool:
        return len(self._messages) == 0
    
    def _on_send(self):
        if self._input_field is None:
            return
        
        content = self._input_field.toPlainText().strip()
        if not content:
            return
        
        self._input_field.clear()
        
        self._messages.append({"role": "user", "content": content})
        
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
        self._is_streaming = True
        self._streaming_conversation_id = self.conversation_id
        self._stream_start_position = self._chat_display.textCursor().position()
        
        self._display_ai_prefix()
        
        current_conv_id = self.conversation_id
        
        def stream_response():
            try:
                from llm_chat.config import Config
                from llm_chat.client import LLMClient
                
                history = [{"role": m["role"], "content": m["content"]} for m in self._messages[:-1]]
                
                if config.enable_tools and client.has_builtin_tools():
                    tools = client.get_builtin_tools()
                    
                    full_text = ""
                    for chunk in client.chat_stream_with_tools(content, tools, history):
                        if isinstance(chunk, tuple) and chunk[0] == "tool_call":
                            _, tool_name, tool_args = chunk
                            self._stream_signals.tool_call_received.emit(tool_name, tool_args)
                        elif isinstance(chunk, str):
                            full_text += chunk
                            self._stream_signals.text_received.emit(chunk)
                    
                    self._stream_signals.stream_finished.emit(current_conv_id, full_text)
                else:
                    full_text = ""
                    for chunk in client.chat_stream(content, history):
                        full_text += chunk
                        self._stream_signals.text_received.emit(chunk)
                    
                    self._stream_signals.stream_finished.emit(current_conv_id, full_text)
                
            except Exception as e:
                self._stream_signals.error_occurred.emit(current_conv_id, str(e))
        
        self._worker_thread = threading.Thread(target=stream_response, daemon=True)
        self._worker_thread.start()
    
    def _display_user_message(self, content: str):
        if self._chat_display is None:
            return
        
        cursor = self._chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml('<p style="color: #B8312F; font-weight: bold;">You:</p>')
        cursor.insertText(f" {content}\n")
        self._chat_display.setTextCursor(cursor)
        self._chat_display.ensureCursorVisible()
    
    def _display_ai_prefix(self):
        if self._chat_display is None:
            return
        
        cursor = self._chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml('<p style="color: #D4652F; font-weight: bold;">AI:</p>')
        self._chat_display.setTextCursor(cursor)
    
    def _on_stream_text(self, text: str):
        if self._chat_display is None or not self._is_streaming:
            return
        
        self._current_stream_text += text
        
        cursor = self._chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self._chat_display.setTextCursor(cursor)
        self._chat_display.ensureCursorVisible()
    
    def _on_stream_finished(self, conv_id: str, full_text: str):
        if conv_id != self.conversation_id:
            return
        
        self._is_streaming = False
        self._streaming_conversation_id = None
        self._messages.append({"role": "assistant", "content": full_text})
        
        if self._storage:
            self._storage.add_message(conv_id, "assistant", full_text)
        
        self._refresh_chat_display()
        self._set_input_state(True)
        
        self._refresh_conversation_list()
    
    def _on_stream_error(self, conv_id: str, error: str):
        if conv_id != self.conversation_id:
            return
        
        self._is_streaming = False
        self._streaming_conversation_id = None
        self.display_error(error)
        self._set_input_state(True)
    
    def _on_tool_call(self, tool_name: str, tool_args: str):
        if self._chat_display is None:
            return
        
        cursor = self._chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        tool_info = f"🔧 调用工具: {tool_name}"
        if tool_args:
            try:
                import json
                args_dict = json.loads(tool_args)
                if args_dict:
                    args_str = ", ".join(f"{k}={v}" for k, v in args_dict.items())
                    tool_info += f" ({args_str})"
            except:
                tool_info += f" ({tool_args})"
        
        cursor.insertHtml(f'<p style="color: #9C27B0; background-color: #F3E5F5; padding: 5px; border-radius: 3px; font-style: italic;">{tool_info}</p>')
        self._chat_display.setTextCursor(cursor)
        self._chat_display.ensureCursorVisible()
    
    def _refresh_chat_display(self):
        if self._chat_display is None:
            return
        
        self._chat_display.clear()
        
        for msg in self._messages:
            cursor = self._chat_display.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            
            if msg["role"] == "user":
                cursor.insertHtml('<p style="color: #B8312F; font-weight: bold;">You:</p>')
                cursor.insertText(f" {msg['content']}\n")
            elif msg["role"] == "assistant":
                cursor.insertHtml('<p style="color: #D4652F; font-weight: bold;">AI:</p>')
                html_content = self._render_markdown(msg["content"])
                cursor.insertHtml(f'<div>{html_content}</div>')
                cursor.insertHtml('<hr style="border: none; border-top: 1px solid #D4A574; margin: 10px 0;">')
        
        self._chat_display.ensureCursorVisible()
    
    def _on_clear(self):
        ctx = ConversationContext(conversation_id=self.conversation_id)
        self._handle_clear(ctx)
        
        self._messages = []
        
        if self._chat_display:
            self._chat_display.clear()
        
        self.display_info("Conversation cleared")
    
    def _on_mcp_config(self):
        try:
            from llm_chat.frontends.mcp_dialog import MCPConfigDialog
            if self._mcp_dialog is None:
                self._mcp_dialog = MCPConfigDialog(self._main_window)
            self._mcp_dialog.exec()
        except ImportError as e:
            QMessageBox.warning(self._main_window, "Error", f"MCP module not available: {e}")
    
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
            md = markdown.Markdown(extensions=['tables', 'fenced_code', 'codehilite'])
            html = md.convert(text)
            return f"{MARKDOWN_CSS}{html}"
        return text.replace('\n', '<br>')
    
    def display_message(self, message: Message):
        if self._chat_display is None:
            return
        
        cursor = self._chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        if message.role == "user":
            cursor.insertHtml('<p style="color: #B8312F; font-weight: bold;">You:</p>')
            cursor.insertText(f" {message.content}\n")
        elif message.role == "assistant":
            cursor.insertHtml('<p style="color: #D4652F; font-weight: bold;">AI:</p>')
            html_content = self._render_markdown(message.content)
            cursor.insertHtml(f'<div>{html_content}</div>')
            cursor.insertHtml('<hr style="border: none; border-top: 1px solid #D4A574; margin: 10px 0;">')
        
        self._chat_display.setTextCursor(cursor)
        self._chat_display.ensureCursorVisible()
    
    def display_error(self, error: str):
        if self._chat_display is None:
            return
        
        cursor = self._chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(f'<p style="color: #8B0000;">Error: {error}</p>')
        self._chat_display.setTextCursor(cursor)
        self._chat_display.ensureCursorVisible()
    
    def display_info(self, info: str):
        if self._chat_display is None:
            return
        
        cursor = self._chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(f'<p style="color: #6B4423; font-style: italic;">[{info}]</p>')
        self._chat_display.setTextCursor(cursor)
        self._chat_display.ensureCursorVisible()
