"""GUI 自定义 Widget 组件。

从 gui.py 拆分，便于独立维护和复用。
"""

from __future__ import annotations
import logging

try:
    from PyQt6.QtWidgets import (
        QWidget,
        QVBoxLayout,
        QTextEdit,
        QPushButton,
        QLabel,
        QFrame,
        QListWidget,
        QListWidgetItem,
    )
    from PyQt6.QtCore import Qt, pyqtSignal, QObject, QRect
    from PyQt6.QtGui import QTextCursor

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

    class ProactiveMessageSignals(QObject):
        """主动消息信号通道（后台线程 → GUI 主线程）。"""
        opener_ready = pyqtSignal(str)

else:
    StreamSignals = object  # fallback
    ConversationListSignals = object
    ProactiveMessageSignals = object


# -- widgets ------------------------------------------------------------

if PYQT_AVAILABLE:

    # ── / 命令自动补全数据 ──────────────────────────────────────

    _SLASH_COMMANDS = [
        ("/help", "显示帮助信息"),
        ("/new", "新建会话"),
        ("/clear", "清空当前会话"),
        ("/style", "切换回复风格 (academic/casual/concise/coach/architect/default)"),
        ("/search", "搜索历史对话"),
        ("/file", "打开文件"),
        ("/code", "代码模式"),
        ("/remember", "记住事实到长期记忆"),
        ("/set", "设置模型参数 (temperature/max_tokens/top_p/reasoning)"),
        ("/params", "显示当前模型参数"),
        ("/reset", "重置模型参数为默认值"),
    ]

    _STYLE_NAMES = ["default", "academic", "casual", "concise", "coach", "architect"]

    # ────────────────────────────────────────────────────────────

    class InputTextEdit(QTextEdit):
        """支持 Shift+Enter 换行、Enter 发送的输入框，高度自适应。

        额外支持：
        - / 命令自动补全 (Tab 补全，下拉列表选择)
        - /style 子命令补全 (风格名 Tab 补全)
        """
        send_requested = pyqtSignal()

        def __init__(self, parent=None):
            super().__init__(parent)
            self._min_height = 36
            self._max_height = 150
            self._popup: Optional[QListWidget] = None
            self._completing = False  # 防止递归 textChanged
            self.document().documentLayout().documentSizeChanged.connect(
                self._adjust_height
            )
            self.textChanged.connect(self._on_text_changed)
            self._adjust_height()

        def _adjust_height(self):
            doc_height = int(self.document().size().height())
            margins = self.contentsMargins()
            needed = doc_height + margins.top() + margins.bottom() + 8
            new_height = max(self._min_height, min(self._max_height, needed))
            self.setFixedHeight(new_height)

        # ── 补全 ─────────────────────────────────────────────

        def _current_word(self) -> str:
            """返回当前行光标前的词（到上一个空格为止）。"""
            tc = self.textCursor()
            tc.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor)
            line = tc.selectedText()
            # 取最后一个空格之后的部分
            return line.rsplit(" ", 1)[-1] if " " in line else line

        def _word_before_slash(self) -> Optional[str]:
            """返回 / 命令词（第一个 / 开头的词），用于判断补全上下文。"""
            tc = self.textCursor()
            tc.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor)
            line = tc.selectedText()
            words = line.split(" ")
            for w in words:
                if w.startswith("/"):
                    return w
            return None

        def _matches(self, partial: str, candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
            """返回以 partial 开头的候选项。"""
            lower = partial.lower()
            return [(cmd, desc) for cmd, desc in candidates if cmd.lower().startswith(lower)]

        def _show_popup(self, items: list[tuple[str, str]]):
            """在输入框下方显示补全弹窗。"""
            if not items:
                self._hide_popup()
                return
            if self._popup is None:
                self._popup = QListWidget(self)
                self._popup.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
                self._popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                self._popup.setMaximumHeight(200)
                self._popup.setStyleSheet("""
                    QListWidget {
                        background-color: #2B2B2B;
                        border: 1px solid #555;
                        border-radius: 6px;
                        padding: 4px;
                        font-size: 13px;
                        color: #E0E0E0;
                    }
                    QListWidget::item {
                        padding: 4px 8px;
                        border-radius: 3px;
                    }
                    QListWidget::item:selected {
                        background-color: #3A6EA5;
                    }
                """)
                self._popup.itemClicked.connect(self._on_popup_selected)

            self._popup.clear()
            for cmd, desc in items:
                display = f"{cmd}  —  {desc}"
                item = QListWidgetItem(display)
                item.setData(Qt.ItemDataRole.UserRole, cmd)
                self._popup.addItem(item)

            # 定位弹窗：输入框下方
            pos = self.mapToGlobal(self.rect().bottomLeft())
            self._popup.move(pos)
            self._popup.setFixedWidth(self.width())
            self._popup.setCurrentRow(0)
            self._popup.show()

        def _hide_popup(self):
            if self._popup:
                self._popup.hide()

        def _apply_completion(self, completion: str):
            """用补全词替换当前行末尾的部分词。"""
            word = self._current_word()
            tc = self.textCursor()
            # 删除末尾词
            for _ in range(len(word)):
                tc.deletePreviousChar()
            # 插入补全词
            tc.insertText(completion)
            self.setTextCursor(tc)

        def _on_popup_selected(self, item: QListWidgetItem):
            """点击弹窗项 → 补全。"""
            cmd = item.data(Qt.ItemDataRole.UserRole)
            self._apply_completion(cmd)
            self._hide_popup()
            self.setFocus()

        def _on_text_changed(self):
            """文本变化时检测是否需要显示补全弹窗。"""
            if self._completing:
                return
            word = self._current_word()
            slash_word = self._word_before_slash()

            if word.startswith("/") and word == slash_word:
                # 正在输入 / 命令本身 → 匹配命令列表
                items = self._matches(word, self._SLASH_COMMANDS)
                if items and word != items[0][0]:  # 不完全匹配才弹
                    self._show_popup(items)
                else:
                    self._hide_popup()
            elif slash_word == "/style" and word and not word.startswith("/"):
                # /style 后面 → 匹配风格名
                items = [(s, "") for s in self._STYLE_NAMES if s.lower().startswith(word.lower())]
                if items and word != items[0][0]:
                    self._show_popup(items)
                else:
                    self._hide_popup()
            else:
                self._hide_popup()

        # ── 键盘事件 ──────────────────────────────────────────

        def keyPressEvent(self, event):
            key = event.key()

            # Tab: 使用弹窗第一项补全
            if key == Qt.Key.Key_Tab and self._popup and self._popup.isVisible():
                first_item = self._popup.item(0)
                if first_item:
                    cmd = first_item.data(Qt.ItemDataRole.UserRole)
                    self._apply_completion(cmd)
                    self._hide_popup()
                    # 如果是 /style，自动加空格方便输入风格名
                    if cmd == "/style":
                        tc = self.textCursor()
                        tc.insertText(" ")
                        self.setTextCursor(tc)
                event.accept()
                return

            # Escape: 关闭弹窗
            if key == Qt.Key.Key_Escape and self._popup and self._popup.isVisible():
                self._hide_popup()
                event.accept()
                return

            # ↓: 在弹窗中下移
            if key == Qt.Key.Key_Down and self._popup and self._popup.isVisible():
                row = self._popup.currentRow()
                if row < self._popup.count() - 1:
                    self._popup.setCurrentRow(row + 1)
                event.accept()
                return

            # ↑: 在弹窗中上移
            if key == Qt.Key.Key_Up and self._popup and self._popup.isVisible():
                row = self._popup.currentRow()
                if row > 0:
                    self._popup.setCurrentRow(row - 1)
                event.accept()
                return

            # Enter: 如果弹窗可见，选择当前项（不发送）
            if key == Qt.Key.Key_Return and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                if self._popup and self._popup.isVisible():
                    item = self._popup.currentItem()
                    if item:
                        cmd = item.data(Qt.ItemDataRole.UserRole)
                        self._apply_completion(cmd)
                        self._hide_popup()
                        if cmd == "/style":
                            tc = self.textCursor()
                            tc.insertText(" ")
                            self.setTextCursor(tc)
                    event.accept()
                    return
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
            from llm_chat.frontends.theme import Colors
            self.setFrameShape(QFrame.Shape.StyledPanel)
            self.setStyleSheet(f"""
                CollapsibleToolCall {{
                    background-color: {Colors.TOOL_BG};
                    border: 1px solid {Colors.TOOL_BORDER};
                    border-radius: 8px;
                    margin: 4px 0px;
                }}
            """)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self._header = QPushButton()
            self._header.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Colors.TOOL_HEADER};
                    border: none;
                    border-radius: 8px 8px 0 0;
                    padding: 8px 12px;
                    text-align: left;
                    font-weight: bold;
                    color: {Colors.TOOL_TEXT};
                }}
                QPushButton:hover {{
                    background-color: {Colors.TOOL_HEADER_HOVER};
                }}
            """)
            self._header.clicked.connect(self._toggle)
            self._update_header_text()
            layout.addWidget(self._header)

            self._content = QWidget()
            self._content.setStyleSheet(
                f"background-color: #FFFFFF; border-radius: 0 0 8px 8px;"
            )
            content_layout = QVBoxLayout(self._content)
            content_layout.setContentsMargins(12, 10, 12, 10)
            content_layout.setSpacing(8)

            args_label = QLabel("参数:")
            args_label.setStyleSheet(
                f"color: {Colors.TOOL_TEXT}; font-weight: bold; border: none; background: transparent;"
            )
            content_layout.addWidget(args_label)

            self._args_text = QTextEdit()
            self._args_text.setPlainText(self._tool_args)
            self._args_text.setReadOnly(True)
            self._args_text.setMaximumHeight(120)
            self._args_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: #F5F5F5;
                    border-radius: 4px;
                    border: none;
                    padding: 8px;
                    font-family: Consolas, monospace;
                    font-size: 12px;
                    color: {Colors.TOOL_TEXT};
                }}
            """)
            content_layout.addWidget(self._args_text)

            self._result_label = QLabel("结果:")
            self._result_label.setStyleSheet(
                f"color: {Colors.TOOL_RESULT_TEXT}; font-weight: bold; border: none; background: transparent;"
            )
            self._result_label.hide()
            content_layout.addWidget(self._result_label)

            self._result_text = QTextEdit()
            self._result_text.setReadOnly(True)
            self._result_text.setMaximumHeight(150)
            self._result_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {Colors.TOOL_RESULT_BG};
                    border-radius: 4px;
                    border-left: 3px solid {Colors.TOOL_RESULT_BORDER};
                    padding: 8px;
                    font-family: Consolas, monospace;
                    font-size: 11px;
                    color: {Colors.TOOL_RESULT_TEXT};
                }}
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
