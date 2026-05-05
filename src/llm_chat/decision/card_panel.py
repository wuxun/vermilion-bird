"""决策卡片 GUI 组件。

CardSignals — 跨线程信号通道
DecisionCardWidget — 单张卡片的 QFrame 渲染

用法:
    from llm_chat.decision.card_panel import DecisionCardWidget, CardSignals

    # 在 GUI 主线程
    signals = CardSignals()
    signals.card_decided.connect(on_decided)

    # 在后台线程
    signals.card_created.emit(card)

    # 添加到聊天流
    widget = DecisionCardWidget(card, on_decide=on_decided)
    chat_layout.addWidget(widget)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from llm_chat.decision.schema import DecisionCard, DecisionOption, CardStatus

logger = logging.getLogger(__name__)

# ── 惰性导入 PyQt6 ──────────────────────────────────────────────────

try:
    from PyQt6.QtCore import Qt, pyqtSignal, QObject
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import (
        QFrame,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
        QSizePolicy,
        QHeaderView,
        QProgressBar,
    )
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False
    QObject = object
    pyqtSignal = None


# ── 颜色常量 ─────────────────────────────────────────────────────────

_COLORS = {
    "bg": "#FFF8F0",
    "border": "#D4A574",
    "title": "#B8312F",
    "text": "#3D2C2E",
    "muted": "#8B7355",
    "accent": "#C84B31",
    "accent_hover": "#EC994B",
    "recommend_bg": "#E8F5E9",
    "recommend_border": "#4CAF50",
    "progress_fill": "#EC994B",
    "progress_bg": "#F5E6D3",
}


# ── 信号通道 ─────────────────────────────────────────────────────────

if PYQT_AVAILABLE:

    class CardSignals(QObject):
        """决策卡片的跨线程信号通道（后台线程 → GUI 主线程）。"""
        card_created = pyqtSignal(object)  # DecisionCard
        card_decided = pyqtSignal(str, str)  # card_id, selected_option_id
        card_dismissed = pyqtSignal(str)  # card_id

else:
    # Fallback: 纯 Python 模拟（用于测试/CLI）
    class CardSignals(QObject):
        card_created = None
        card_decided = None
        card_dismissed = None


# ── 样式 ─────────────────────────────────────────────────────────────

_CARD_STYLE = """
QFrame#{name} {{
    background-color: {bg};
    border: 1px solid {border};
    border-radius: 8px;
    margin: 4px 0px;
    padding: 8px;
}}
QFrame#{name}:hover {{
    border-color: {accent};
}}
""".format(**_COLORS, name="__card__")


def _make_button(text: str, primary: bool = False) -> "QPushButton":
    """创建卡片选项按钮。"""
    if not PYQT_AVAILABLE:
        return None
    btn = QPushButton(text)
    if primary:
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_COLORS['accent']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {_COLORS['accent_hover']};
            }}
            QPushButton:disabled {{
                background-color: #ccc;
                color: #999;
            }}
        """)
    else:
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: white;
                color: {_COLORS['text']};
                border: 1px solid {_COLORS['border']};
                border-radius: 4px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background-color: {_COLORS['accent_hover']};
                color: white;
                border-color: {_COLORS['accent_hover']};
            }}
            QPushButton:disabled {{
                background-color: #f0f0f0;
                color: #ccc;
                border-color: #e0e0e0;
            }}
        """)
    return btn


# ── 卡片组件 ─────────────────────────────────────────────────────────


class DecisionCardWidget(QFrame):
    """单张决策卡片的 QFrame 渲染。

    包含:
    - 标题 + 背景摘要
    - 选项对比表格（置信度进度条）
    - 按钮行（选 A / 选 B / 了解更多 / 忽略）
    """

    def __init__(
        self,
        card: DecisionCard,
        on_decide: Optional[Callable[[str, str], None]] = None,
        on_dismiss: Optional[Callable[[str], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._card = card
        self._on_decide = on_decide
        self._on_dismiss = on_dismiss
        self._option_buttons: Dict[str, QPushButton] = {}

        self._build_ui()

    # ── 构建 UI ─────────────────────────────────────────────────────

    def _build_ui(self):
        if not PYQT_AVAILABLE:
            return

        self.setObjectName("__card__")
        self.setStyleSheet(_CARD_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # 标题
        title_label = QLabel(f"\U0001f3af {self._card.title}")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {_COLORS['title']};")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        # 背景摘要
        if self._card.context:
            ctx = QLabel(self._card.context)
            ctx.setStyleSheet(f"color: {_COLORS['text']}; font-size: 11px;")
            ctx.setWordWrap(True)
            ctx.setContentsMargins(0, 0, 0, 4)
            layout.addWidget(ctx)

        # 选项对比表格
        self._build_options_table(layout)

        # 按钮行
        self._build_button_row(layout)

        # 来源
        if self._card.sources:
            src = QLabel(f"来源: {', '.join(self._card.sources)}")
            src.setStyleSheet(f"color: {_COLORS['muted']}; font-size: 10px;")
            layout.addWidget(src)

        # 如果已决策，禁用按钮
        if self._card.status != CardStatus.PENDING:
            self._set_decided_state(self._card.selected_option_id if hasattr(self._card, 'selected_option_id') else None)

    def _build_options_table(self, layout: QVBoxLayout):
        """构建选项对比表格。"""
        if not self._card.options:
            return

        # 使用 QTableWidget 做对比表格
        table = QTableWidget(len(self._card.options), 4)
        table.setHorizontalHeaderLabels(["", "选项", "预期效果", "风险"])
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table.setColumnWidth(0, 24)

        table.setStyleSheet(f"""
            QTableWidget {{
                border: none;
                background-color: transparent;
                font-size: 11px;
            }}
            QTableWidget::item {{
                padding: 4px 6px;
                border-bottom: 1px solid {_COLORS['border']}44;
                color: {_COLORS['text']};
            }}
            QHeaderView::section {{
                background-color: {_COLORS['bg']};
                color: {_COLORS['muted']};
                border: none;
                font-weight: bold;
                font-size: 10px;
                padding: 4px 6px;
            }}
        """)

        for row, opt in enumerate(self._card.options):
            # 推荐标记
            is_rec = opt.id == self._card.recommendation
            rec_label = QLabel("⭐" if is_rec else "")
            rec_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setCellWidget(row, 0, rec_label)

            # 选项名 + 置信度进度条
            opt_widget = QWidget()
            opt_layout = QVBoxLayout(opt_widget)
            opt_layout.setContentsMargins(0, 0, 0, 4)
            opt_layout.setSpacing(2)

            opt_name = QLabel(opt.label)
            opt_name.setStyleSheet("font-weight: bold; color: {}".format(
                _COLORS['accent'] if is_rec else _COLORS['text']
            ))
            opt_layout.addWidget(opt_name)

            # 置信度进度条
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(opt.confidence * 100))
            bar.setTextVisible(True)
            bar.setFixedHeight(14)
            bar.setStyleSheet(f"""
                QProgressBar {{
                    background-color: {_COLORS['progress_bg']};
                    border: none;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 9px;
                    color: {_COLORS['text']};
                }}
                QProgressBar::chunk {{
                    background-color: {_COLORS['progress_fill']};
                    border-radius: 3px;
                }}
            """)
            opt_layout.addWidget(bar)

            table.setCellWidget(row, 1, opt_widget)

            # 预期效果
            effect = QLabel(opt.expected_effect or "")
            effect.setWordWrap(True)
            table.setCellWidget(row, 2, effect)

            # 风险
            risk = QLabel(opt.risk or "")
            risk.setWordWrap(True)
            table.setCellWidget(row, 3, risk)

        # 行高自动
        for row in range(len(self._card.options)):
            table.setRowHeight(row, 60)

        table.setFixedHeight(min(len(self._card.options) * 64 + 30, 200))
        layout.addWidget(table)

    def _build_button_row(self, layout: QVBoxLayout):
        """构建选项按钮行。"""
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        for opt in self._card.options:
            is_rec = opt.id == self._card.recommendation
            text = f"{'✅ ' if is_rec else ''}选 {opt.id}"
            btn = _make_button(text, primary=is_rec)
            btn.clicked.connect(lambda checked, oid=opt.id: self._on_decide_clicked(oid))
            self._option_buttons[opt.id] = btn
            btn_layout.addWidget(btn)

        btn_layout.addStretch()

        # 了解更多按钮（扩展选项描述）
        if any(o.description for o in self._card.options):
            more_btn = QPushButton("了解更多")
            more_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {_COLORS['accent']};
                    border: none;
                    text-decoration: underline;
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    color: {_COLORS['accent_hover']};
                }}
            """)
            more_btn.clicked.connect(self._on_more_clicked)
            btn_layout.addWidget(more_btn)

        # 忽略按钮
        dismiss_btn = QPushButton("稍后")
        dismiss_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {_COLORS['muted']};
                border: 1px solid {_COLORS['border']};
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                color: {_COLORS['accent']};
                border-color: {_COLORS['accent']};
            }}
            QPushButton:disabled {{
                color: #ccc;
                border-color: #e0e0e0;
            }}
        """)
        dismiss_btn.clicked.connect(self._on_dismiss_clicked)
        self._dismiss_btn = dismiss_btn
        btn_layout.addWidget(dismiss_btn)

        layout.addLayout(btn_layout)

    # ── 事件处理 ─────────────────────────────────────────────────────

    def _on_decide_clicked(self, option_id: str):
        """用户点击了选项按钮。"""
        try:
            self._card.decide(option_id)
        except ValueError as e:
            logger.warning(str(e))
            return

        self._set_decided_state(option_id)

        if self._on_decide:
            self._on_decide(self._card.id, option_id)

    def _on_dismiss_clicked(self):
        """用户点击了忽略。"""
        try:
            self._card.dismiss()
        except ValueError as e:
            logger.warning(str(e))
            return

        for btn in self._option_buttons.values():
            btn.setEnabled(False)
        if self._dismiss_btn:
            self._dismiss_btn.setEnabled(False)

        # 变灰
        self.setStyleSheet(_CARD_STYLE.replace(_COLORS['bg'], "#f5f5f5"))

        if self._on_dismiss:
            self._on_dismiss(self._card.id)

    def _on_more_clicked(self):
        """展开选项的详细描述。"""
        # 简单实现：弹出一个 info label
        details = []
        for opt in self._card.options:
            if opt.description:
                details.append(f"<b>{opt.label}:</b> {opt.description}")
        if details:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "选项详情",
                "\n\n".join(details),
            )

    def _set_decided_state(self, option_id: Optional[str]):
        """决策后禁用按钮并高亮选中项。"""
        for oid, btn in self._option_buttons.items():
            btn.setEnabled(False)
            if oid == option_id:
                # 高亮选中按钮：绿色边框
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {_COLORS['recommend_bg']};
                        color: {_COLORS['recommend_border']};
                        border: 2px solid {_COLORS['recommend_border']};
                        border-radius: 4px;
                        padding: 6px 14px;
                        font-weight: bold;
                    }}
                """)
        if self._dismiss_btn:
            self._dismiss_btn.setEnabled(False)

    # ── 访问器 ───────────────────────────────────────────────────────

    @property
    def card(self) -> DecisionCard:
        return self._card
