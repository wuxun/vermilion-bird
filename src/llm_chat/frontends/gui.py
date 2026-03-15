import sys
import threading
from typing import Optional
from llm_chat.frontends.base import BaseFrontend, Message, ConversationContext, MessageType

try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTextEdit, QTextBrowser, QPushButton, QLabel, QFrame, QMessageBox
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
    body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
    h1 { color: #1976D2; border-bottom: 2px solid #1976D2; padding-bottom: 5px; }
    h2 { color: #1565C0; border-bottom: 1px solid #1565C0; padding-bottom: 5px; }
    h3 { color: #0D47A1; }
    code { background-color: #e8e8e8; padding: 2px 6px; border-radius: 3px; font-family: Consolas, monospace; color: #333; }
    pre { background-color: #2d2d2d; padding: 10px; border-radius: 5px; overflow-x: auto; }
    pre code { background-color: transparent; padding: 0; color: #f8f8f2; }
    blockquote { border-left: 4px solid #4CAF50; margin-left: 0; padding-left: 15px; color: #555; }
    ul, ol { padding-left: 20px; }
    li { margin: 5px 0; }
    table { border-collapse: collapse; width: 100%; margin: 10px 0; }
    th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
    th { background-color: #e0e0e0; }
    a { color: #1976D2; text-decoration: none; }
    a:hover { text-decoration: underline; }
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
        stream_finished = pyqtSignal(str)
        error_occurred = pyqtSignal(str)


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
        self._current_stream_text: str = ""
        self._stream_start_position: int = 0
        self._messages: list = []
        self._is_streaming: bool = False
    
    def start(self):
        self._app = QApplication(sys.argv)
        self._app.setStyle("Fusion")
        
        self._stream_signals = StreamSignals()
        self._stream_signals.text_received.connect(self._on_stream_text)
        self._stream_signals.stream_finished.connect(self._on_stream_finished)
        self._stream_signals.error_occurred.connect(self._on_stream_error)
        
        self._main_window = QMainWindow()
        self._main_window.setWindowTitle(self.title)
        self._main_window.setMinimumSize(QSize(800, 600))
        
        central_widget = QWidget()
        self._main_window.setCentralWidget(central_widget)
        
        self._setup_ui(central_widget)
        self._apply_styles()
        
        self._main_window.closeEvent = self._on_close_event
        
        self.display_info("Welcome to Vermilion Bird!")
        self.display_info("Press Enter to send, Shift+Enter for new line")
        
        self._main_window.show()
        sys.exit(self._app.exec())
    
    def _setup_ui(self, parent: QWidget):
        main_layout = QVBoxLayout(parent)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
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
        
        main_layout.addLayout(header_layout)
        
        self._chat_display = QTextBrowser()
        self._chat_display.setReadOnly(True)
        self._chat_display.setFont(QFont("Arial", 11))
        self._chat_display.setFrameStyle(QFrame.Shape.StyledPanel)
        self._chat_display.setOpenExternalLinks(True)
        main_layout.addWidget(self._chat_display, stretch=1)
        
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
        
        main_layout.addLayout(input_container)
    
    def _apply_styles(self):
        self._chat_display.setStyleSheet("""
            QTextBrowser {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 10px;
                color: #333;
            }
        """)
        
        self._input_field.setStyleSheet("""
            QTextEdit {
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 5px;
                background-color: #fff;
                color: #333;
            }
            QTextEdit:focus {
                border: 1px solid #1976D2;
            }
        """)
        
        self._send_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #bbb;
            }
        """)
        
        self._clear_button.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)
        
        self._mcp_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #388E3C;
            }
        """)
    
    def _on_send(self):
        if self._input_field is None:
            return
        
        content = self._input_field.toPlainText().strip()
        if not content:
            return
        
        self._input_field.clear()
        
        self._messages.append({"role": "user", "content": content})
        self._display_user_message(content)
        
        self._set_input_state(False)
        
        self._current_stream_text = ""
        self._is_streaming = True
        self._stream_start_position = self._chat_display.textCursor().position()
        
        self._display_ai_prefix()
        
        def stream_response():
            try:
                from llm_chat.config import Config
                from llm_chat.client import LLMClient
                config = Config()
                client = LLMClient(config)
                
                full_text = ""
                for chunk in client.chat_stream(content, []):
                    full_text += chunk
                    self._stream_signals.text_received.emit(chunk)
                
                self._stream_signals.stream_finished.emit(full_text)
                
            except Exception as e:
                self._stream_signals.error_occurred.emit(str(e))
        
        self._worker_thread = threading.Thread(target=stream_response, daemon=True)
        self._worker_thread.start()
    
    def _display_user_message(self, content: str):
        if self._chat_display is None:
            return
        
        cursor = self._chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml('<p style="color: #1565C0; font-weight: bold;">You:</p>')
        cursor.insertText(f" {content}\n")
        self._chat_display.setTextCursor(cursor)
        self._chat_display.ensureCursorVisible()
    
    def _display_ai_prefix(self):
        if self._chat_display is None:
            return
        
        cursor = self._chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml('<p style="color: #2E7D32; font-weight: bold;">AI:</p>')
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
    
    def _on_stream_finished(self, full_text: str):
        self._is_streaming = False
        self._messages.append({"role": "assistant", "content": full_text})
        
        self._refresh_chat_display()
        self._set_input_state(True)
    
    def _on_stream_error(self, error: str):
        self._is_streaming = False
        self.display_error(error)
        self._set_input_state(True)
    
    def _refresh_chat_display(self):
        if self._chat_display is None:
            return
        
        self._chat_display.clear()
        
        for msg in self._messages:
            cursor = self._chat_display.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            
            if msg["role"] == "user":
                cursor.insertHtml('<p style="color: #1565C0; font-weight: bold;">You:</p>')
                cursor.insertText(f" {msg['content']}\n")
            elif msg["role"] == "assistant":
                cursor.insertHtml('<p style="color: #2E7D32; font-weight: bold;">AI:</p>')
                html_content = self._render_markdown(msg["content"])
                cursor.insertHtml(f'<div>{html_content}</div>')
                cursor.insertHtml('<hr style="border: none; border-top: 1px solid #ccc; margin: 10px 0;">')
        
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
            cursor.insertHtml('<p style="color: #1565C0; font-weight: bold;">You:</p>')
            cursor.insertText(f" {message.content}\n")
        elif message.role == "assistant":
            cursor.insertHtml('<p style="color: #2E7D32; font-weight: bold;">AI:</p>')
            html_content = self._render_markdown(message.content)
            cursor.insertHtml(f'<div>{html_content}</div>')
            cursor.insertHtml('<hr style="border: none; border-top: 1px solid #ccc; margin: 10px 0;">')
        
        self._chat_display.setTextCursor(cursor)
        self._chat_display.ensureCursorVisible()
    
    def display_error(self, error: str):
        if self._chat_display is None:
            return
        
        cursor = self._chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(f'<p style="color: #C62828;">Error: {error}</p>')
        self._chat_display.setTextCursor(cursor)
        self._chat_display.ensureCursorVisible()
    
    def display_info(self, info: str):
        if self._chat_display is None:
            return
        
        cursor = self._chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(f'<p style="color: #616161; font-style: italic;">[{info}]</p>')
        self._chat_display.setTextCursor(cursor)
        self._chat_display.ensureCursorVisible()
