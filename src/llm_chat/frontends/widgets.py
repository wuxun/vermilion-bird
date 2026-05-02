"""GUI 自定义 Widget 组件。

从 gui.py 拆分，便于独立维护和复用。
"""

import logging

try:
    from PyQt6.QtWidgets import (
        QWidget,
        QVBoxLayout,
        QTextEdit,
        QPushButton,
        QLabel,
        QFrame,
    )
    from PyQt6.QtCore import Qt, pyqtSignal, QObject

    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False

logger = logging.getLogger(__name__)


# -- signals ------------------------------------------------------------

if PYQT_AVAILABLE:

    class StreamSignals(QObject):
        """流式回调的信号通道（后台线程 → GUI 主线程）。"""
        text_received = pyqtSignal(str)
        stream_finished = pyqtSignal(str, str)
        error_occurred = pyqtSignal(str, str)
        tool_call_started = pyqtSignal(str, str)
        tool_call_finished = pyqtSignal(str, str, str)
        context_updated = pyqtSignal(int, int)

    class ConversationListSignals(QObject):
        """会话列表操作信号通道。"""
        conversations_updated = pyqtSignal()

else:
    StreamSignals = object  # fallback
    ConversationListSignals = object


# -- widgets ------------------------------------------------------------

if PYQT_AVAILABLE:

    class InputTextEdit(QTextEdit):
        """支持 Shift+Enter 换行、Enter 发送的输入框。"""
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
        """可折叠的工具调用展示卡片。"""
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

        def set_result(self, result: str):
            self._result = result if result else "无返回结果"
            self._is_completed = True
            self._result_text.setPlainText(self._result)
            self._result_label.show()
            self._result_text.show()
            self._update_header_text()
            self.collapse()

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
