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
    class CardSignals(QObject):
        card_created = None
        card_decided = None
        card_dismissed = None


# ── 样式 ─────────────────────────────────────────────────────────────

_CARD_STYLE = f"""
QFrame#__card__ {{
    background-color: {_COLORS['bg']};
    border: 1px solid {_COLORS['border']};
    border-radius: 8px;
    margin: 4px 0px;
    padding: 8px;
}}
QFrame#__card__:hover {{
    border-color: {_COLORS['accent']};
}}
"""


def _make_button(text: str, primary: bool = False) -> "QPushButton":
    """创建卡片选项按钮。"""
    if not PYQT_AVAILABLE:
        return None
    if primary:
        style = f"""
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
        """
    else:
        style = f"""
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
        """
    btn = QPushButton(text)
    btn.setStyleSheet(style)
    return btn


# ── 卡片组件 ─────────────────────────────────────────────────────────


class DecisionCardWidget(QFrame):
    """单张决策卡片的 QFrame 渲染。"""

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

    def _build_ui(self):
        if not PYQT_AVAILABLE:
            return

        self.setObjectName("__card__")
        self.setStyleSheet(_CARD_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # ── 标题 ──
        title_label = QLabel(f"\U0001f3af {self._card.title}")
        tf = QFont()
        tf.setPointSize(12)
        tf.setBold(True)
        title_label.setFont(tf)
        title_label.setStyleSheet(f"color: {_COLORS['title']};")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        # ── 背景摘要 ──
        if self._card.context:
            ctx = QLabel(self._card.context)
            ctx.setStyleSheet(f"color: {_COLORS['text']}; font-size: 11px;")
            ctx.setWordWrap(True)
            ctx.setContentsMargins(0, 0, 0, 4)
            layout.addWidget(ctx)

        # ── 选项列表（非表格，用 QFrame 卡片布局） ──
        self._build_options_list(layout)

        # ── 按钮行 ──
        self._build_button_row(layout)

        # ── 来源 ──
        if self._card.sources:
            src = QLabel(f"来源: {', '.join(self._card.sources)}")
            src.setStyleSheet(f"color: {_COLORS['muted']}; font-size: 10px;")
            layout.addWidget(src)

        # 如果卡片已决策，禁用按钮
        if self._card.status != CardStatus.PENDING:
            self._set_decided_state(None)

    def _build_options_list(self, layout: QVBoxLayout):
        """用左右布局展示选项：左侧 A/B/C 序号，右侧标题+描述+详情。"""
        if not self._card.options:
            return

        option_ids = [o.id for o in self._card.options]

        for opt in self._card.options:
            is_rec = opt.id == self._card.recommendation

            # 整个选项的水平布局（序号 | 内容）
            option_row = QHBoxLayout()
            option_row.setSpacing(10)

            # ── 左侧：A/B/C 序号 ──
            idx_label = QLabel(opt.id)
            idx_font = QFont()
            idx_font.setPointSize(16)
            idx_font.setBold(True)
            idx_label.setFont(idx_font)
            idx_label.setFixedWidth(30)
            idx_label.setAlignment(
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
            )
            idx_label.setStyleSheet(f"""
                color: {_COLORS['accent'] if is_rec else _COLORS['border']};
                margin-top: 4px;
            """)
            option_row.addWidget(idx_label)

            # ── 右侧：内容区 ──
            content_col = QVBoxLayout()
            content_col.setSpacing(3)

            # 行 1: 标题 + 推荐标记 + 置信度
            header_row = QHBoxLayout()
            header_row.setSpacing(6)

            name = QLabel(opt.label)
            name.setStyleSheet(f"""
                font-weight: bold; font-size: 12px;
                color: {_COLORS['accent'] if is_rec else _COLORS['text']};
            """)
            name.setWordWrap(True)
            header_row.addWidget(name, 1)

            if is_rec:
                rec_tag = QLabel("推荐")
                rec_tag.setStyleSheet(f"""
                    background-color: {_COLORS['recommend_border']};
                    color: white;
                    border-radius: 3px;
                    padding: 1px 6px;
                    font-size: 9px;
                    font-weight: bold;
                """)
                header_row.addWidget(rec_tag)

            conf_label = QLabel(f"{int(opt.confidence * 100)}%")
            conf_label.setStyleSheet(f"color: {_COLORS['muted']}; font-size: 10px;")
            header_row.addWidget(conf_label)

            content_col.addLayout(header_row)

            # 行 2: 描述（description + expected_effect 合并）
            desc_parts = []
            if opt.description:
                desc_parts.append(opt.description)
            if opt.expected_effect and opt.description not in (opt.expected_effect, ""):
                desc_parts.append(f"✨ {opt.expected_effect}")
            if desc_parts:
                desc = QLabel("  ".join(desc_parts))
                desc.setStyleSheet(f"color: {_COLORS['text']}; font-size: 11px;")
                desc.setWordWrap(True)
                content_col.addWidget(desc)

            # 行 3: 风险 + 置信度进度条
            detail_row = QHBoxLayout()
            detail_row.setSpacing(8)

            if opt.risk:
                risk = QLabel(f"⚠️ {opt.risk}")
                risk.setStyleSheet(f"color: {_COLORS['muted']}; font-size: 10px;")
                risk.setWordWrap(True)
                detail_row.addWidget(risk, 1)

            # 置信度进度条（紧凑型）
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(opt.confidence * 100))
            bar.setTextVisible(False)
            bar.setFixedHeight(5)
            bar.setFixedWidth(80)
            bar.setStyleSheet(f"""
                QProgressBar {{
                    background-color: {_COLORS['progress_bg']};
                    border: none;
                    border-radius: 3px;
                }}
                QProgressBar::chunk {{
                    background-color: {_COLORS['recommend_border'] if is_rec else _COLORS['progress_fill']};
                    border-radius: 3px;
                }}
            """)
            detail_row.addWidget(bar)

            content_col.addLayout(detail_row)

            # 分隔线（最后一项不画）
            option_row.addLayout(content_col, 1)
            layout.addLayout(option_row)

            if opt.id != option_ids[-1]:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet(
                    f"background-color: {_COLORS['border']}44;"
                    f"max-height: 1px; margin: 2px 0;"
                )
                layout.addWidget(sep)

    def _build_button_row(self, layout: QVBoxLayout):
        """构建选项按钮行。"""
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        for opt in self._card.options:
            is_rec = opt.id == self._card.recommendation
            text = f"{'✅ ' if is_rec else ''}选 {opt.id}"
            btn = _make_button(text, primary=is_rec)
            btn.clicked.connect(
                lambda checked, oid=opt.id: self._on_decide_clicked(oid)
            )
            self._option_buttons[opt.id] = btn
            btn_layout.addWidget(btn)

        btn_layout.addStretch()

        # 了解更多
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

        # 忽略
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
        try:
            self._card.decide(option_id)
        except ValueError as e:
            logger.warning(str(e))
            return

        self._set_decided_state(option_id)

        if self._on_decide:
            self._on_decide(self._card.id, option_id)

    def _on_dismiss_clicked(self):
        try:
            self._card.dismiss()
        except ValueError as e:
            logger.warning(str(e))
            return

        for btn in self._option_buttons.values():
            btn.setEnabled(False)
        if self._dismiss_btn:
            self._dismiss_btn.setEnabled(False)

        self.setStyleSheet(_CARD_STYLE.replace(_COLORS["bg"], "#f5f5f5"))

        if self._on_dismiss:
            self._on_dismiss(self._card.id)

    def _on_more_clicked(self):
        details = []
        for opt in self._card.options:
            if opt.description:
                details.append(f"<b>{opt.label}:</b> {opt.description}")
        if details:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.information(self, "选项详情", "\n\n".join(details))

    def _set_decided_state(self, option_id: Optional[str]):
        for oid, btn in self._option_buttons.items():
            btn.setEnabled(False)
            if oid == option_id:
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

    @property
    def card(self) -> DecisionCard:
        return self._card
