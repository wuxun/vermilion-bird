import sys
import threading
from typing import Optional
from llm_chat.frontends.base import BaseFrontend, Message, ConversationContext, MessageType

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTextEdit, QPushButton, QLabel, QFrame
    )
    from PyQt6.QtCore import Qt, QTimer, QSize
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
    QPushButton = None
    QLabel = None
    QFrame = None
    Qt = None
    QTimer = None
    QSize = None
    QFont = None
    QTextCursor = None
    QKeyEvent = None


class InputTextEdit(QTextEdit):
    if PYQT_AVAILABLE:
        from PyQt6.QtCore import pyqtSignal
        send_requested = pyqtSignal()
    
    def keyPressEvent(self, event):
        if PYQT_AVAILABLE:
            if event.key() == Qt.Key.Key_Return and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.send_requested.emit()
                event.accept()
                return
        super().keyPressEvent(event)


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
        self._chat_display: Optional[QTextEdit] = None
        self._input_field: Optional[InputTextEdit] = None
        self._send_button: Optional[QPushButton] = None
        self._clear_button: Optional[QPushButton] = None
        self._worker_thread: Optional[threading.Thread] = None
    
    def start(self):
        self._app = QApplication(sys.argv)
        self._app.setStyle("Fusion")
        
        self._main_window = QMainWindow()
        self._main_window.setWindowTitle(self.title)
        self._main_window.setMinimumSize(QSize(800, 600))
        
        central_widget = QWidget()
        self._main_window.setCentralWidget(central_widget)
        
        self._setup_ui(central_widget)
        self._apply_styles()
        
        self._main_window.closeEvent = self._on_close_event
        
        self.display_info("Welcome to Vermilion Bird!")
        self.display_info("Press Ctrl+Enter to send message")
        
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
        
        self._clear_button = QPushButton("Clear")
        self._clear_button.setFixedWidth(80)
        self._clear_button.clicked.connect(self._on_clear)
        header_layout.addWidget(self._clear_button)
        
        main_layout.addLayout(header_layout)
        
        self._chat_display = QTextEdit()
        self._chat_display.setReadOnly(True)
        self._chat_display.setFont(QFont("Arial", 11))
        self._chat_display.setFrameStyle(QFrame.Shape.StyledPanel)
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
            QTextEdit {
                background-color: #fafafa;
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 10px;
            }
        """)
        
        self._input_field.setStyleSheet("""
            QTextEdit {
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 5px;
            }
            QTextEdit:focus {
                border: 1px solid #2196F3;
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
    
    def _on_send(self):
        if self._input_field is None:
            return
        
        content = self._input_field.toPlainText().strip()
        if not content:
            return
        
        self._input_field.clear()
        
        message = Message(
            content=content,
            role="user",
            msg_type=MessageType.TEXT
        )
        ctx = ConversationContext(conversation_id=self.conversation_id)
        
        self.display_message(message)
        self._set_input_state(False)
        
        def send_and_display():
            self._handle_message(message, ctx)
        
        self._worker_thread = threading.Thread(target=send_and_display, daemon=True)
        self._worker_thread.start()
        
        def check_thread():
            if self._worker_thread and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=0.1)
                if self._worker_thread.is_alive():
                    if self._app:
                        QTimer.singleShot(100, check_thread)
                else:
                    self._set_input_state(True)
            else:
                self._set_input_state(True)
        
        if self._app:
            QTimer.singleShot(100, check_thread)
    
    def _on_clear(self):
        ctx = ConversationContext(conversation_id=self.conversation_id)
        self._handle_clear(ctx)
        
        if self._chat_display:
            self._chat_display.clear()
        
        self.display_info("Conversation cleared")
    
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
    
    def display_message(self, message: Message):
        if self._chat_display is None:
            return
        
        cursor = self._chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        if message.role == "user":
            cursor.insertHtml('<p style="color: #2196F3; font-weight: bold;">You:</p>')
            cursor.insertText(f" {message.content}\n")
        elif message.role == "assistant":
            cursor.insertHtml('<p style="color: #4CAF50; font-weight: bold;">AI:</p>')
            cursor.insertText(f" {message.content}\n")
            cursor.insertHtml('<p style="color: #9E9E9E;">' + "-" * 40 + "</p>")
        
        self._chat_display.setTextCursor(cursor)
        self._chat_display.ensureCursorVisible()
    
    def display_error(self, error: str):
        if self._chat_display is None:
            return
        
        cursor = self._chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(f'<p style="color: #F44336;">Error: {error}</p>')
        self._chat_display.setTextCursor(cursor)
        self._chat_display.ensureCursorVisible()
    
    def display_info(self, info: str):
        if self._chat_display is None:
            return
        
        cursor = self._chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(f'<p style="color: #9E9E9E; font-style: italic;">[{info}]</p>')
        self._chat_display.setTextCursor(cursor)
        self._chat_display.ensureCursorVisible()
