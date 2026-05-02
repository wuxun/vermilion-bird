"""SubAgent Panel — 子 Agent 实时运行面板

面板内每行显示 agent 摘要（状态图标 + 任务 + 耗时 + 取消）。
点击行打开 DetailDialog 弹窗，展示模型/协议、工具白名单、工具调用时间线、完整结果。

线程安全：registry 回调在后台线程触发 → pyqtSignal + QueuedConnection → 主线程更新 UI。
"""

from __future__ import annotations

import json
import time
import logging
from typing import Dict, Optional, Any, List, TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QScrollArea,
    QTextEdit,
)
from PyQt6.QtGui import QFont

if TYPE_CHECKING:
    from llm_chat.skills.task_delegator.registry import SubAgentRegistry

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Color palette (warm brown theme)
# ------------------------------------------------------------------

C_DARK    = "#3D2C2E"
C_MEDIUM  = "#6B4423"
C_LIGHT   = "#A67B5B"
C_ACCENT  = "#8B5E3C"
C_BG      = "#FFFCF7"
C_BG_PANEL = "#F5E6D3"
C_BORDER  = "#E8D5C4"
C_BORDER2 = "#D4A574"
C_SUCCESS = "#2E7D32"
C_ERROR   = "#C0392B"
C_BLUE    = "#1565C0"
C_TOOL_BG = "#FDF2E9"

# ------------------------------------------------------------------
# Status helpers
# ------------------------------------------------------------------

_STATUS_ICONS = {
    "running":   "\U0001F7E1",   # 🟡
    "spawned":   "\U0001F535",   # 🔵
    "completed": "\u2705",       # ✅
    "failed":    "\u274C",       # ❌
    "cancelled": "\u2298",       # ⊘
}

_STATUS_COLORS = {
    "running":   "#E67E22",
    "spawned":   "#2980B9",
    "completed": C_SUCCESS,
    "failed":    C_ERROR,
    "cancelled": "#95A5A6",
}

_STATUS_LABELS = {
    "running":   "Running",
    "spawned":   "Spawned",
    "completed": "Completed",
    "failed":    "Failed",
    "cancelled": "Cancelled",
}


def _status_icon(status: str) -> str:
    return _STATUS_ICONS.get(status, "\u2753")


def _elapsed_str(start: float) -> str:
    dt = time.time() - start
    if dt < 60:
        return f"{dt:.1f}s"
    m, s = divmod(int(dt), 60)
    return f"{m}m{s:02d}s"


def _fmt_label(text: str, font_size: int = 10, bold: bool = False, color: str = C_DARK) -> QLabel:
    lbl = QLabel(text)
    w = QFont.Weight.Bold if bold else QFont.Weight.Normal
    lbl.setFont(QFont("Arial", font_size, w))
    lbl.setStyleSheet(f"color: {color}; border: none; background: transparent; padding: 0;")
    lbl.setWordWrap(True)
    return lbl


def _fmt_badge(text: str, bg: str = C_TOOL_BG, fg: str = C_MEDIUM) -> QLabel:
    badge = QLabel(text)
    badge.setFont(QFont("Arial", 9))
    badge.setStyleSheet(
        f"color: {fg}; background-color: {bg}; border: 1px solid {C_BORDER}; "
        f"border-radius: 3px; padding: 0 4px;"
    )
    badge.setFixedHeight(18)
    return badge


# ------------------------------------------------------------------
# Agent Detail Dialog
# ------------------------------------------------------------------


class AgentDetailDialog(QDialog):
    """子 Agent 详情弹窗 —— 展示执行全貌。

    Modeless: 可同时打开多个，agent 运行时实时更新。
    """

    _instances: Dict[str, "AgentDetailDialog"] = {}  # agent_id → dialog

    @classmethod
    def open_for(cls, entry: "AgentEntryWidget", parent: Optional[QWidget] = None):
        """打开或激活已存在的详情弹窗。"""
        aid = entry.agent_id
        existing = cls._instances.get(aid)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        dlg = cls(entry, parent)
        cls._instances[aid] = dlg
        dlg.finished.connect(lambda: cls._instances.pop(aid, None))
        # Non-modal: show independently
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()

    def __init__(self, entry: "AgentEntryWidget", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._entry = entry
        self.setWindowTitle(f"Sub Agent — {entry._task[:60]}")
        self.setMinimumSize(520, 400)
        self.resize(600, 500)
        self.setStyleSheet(f"QDialog {{ background-color: {C_BG}; }}")
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        # ---- Header ----
        header = QHBoxLayout()
        icon = _status_icon(self._entry._status)
        color = _STATUS_COLORS.get(self._entry._status, C_DARK)
        self._header_icon = QLabel(icon)
        self._header_icon.setFont(QFont("Arial", 16))
        self._header_icon.setStyleSheet(f"color: {color}; border: none; background: transparent;")
        header.addWidget(self._header_icon)

        self._header_task = _fmt_label(self._entry._task, font_size=12, bold=True, color=C_DARK)
        header.addWidget(self._header_task, stretch=1)

        self._header_status = _fmt_label("", font_size=10, color=color)
        header.addWidget(self._header_status)
        layout.addLayout(header)

        # ---- Meta badges row ----
        self._meta_layout = QHBoxLayout()
        self._meta_layout.setSpacing(6)
        self._meta_layout.addStretch()
        layout.addLayout(self._meta_layout)

        # ---- Tools row ----
        self._tools_layout = QHBoxLayout()
        self._tools_layout.setSpacing(4)
        layout.addLayout(self._tools_layout)

        # ---- Tool calls section ----
        self._tool_calls_label = _fmt_label("📋 Tool Calls", font_size=10, bold=True, color=C_MEDIUM)
        layout.addWidget(self._tool_calls_label)

        self._tool_calls_scroll = QScrollArea()
        self._tool_calls_scroll.setWidgetResizable(True)
        self._tool_calls_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._tool_calls_scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            QScrollArea QWidget#toolCallsContainer {{ background-color: {C_BG}; }}
        """)
        self._tool_calls_scroll.setMaximumHeight(200)
        self._tool_calls_container = QWidget()
        self._tool_calls_container.setObjectName("toolCallsContainer")
        self._tool_calls_container_layout = QVBoxLayout(self._tool_calls_container)
        self._tool_calls_container_layout.setContentsMargins(0, 0, 0, 0)
        self._tool_calls_container_layout.setSpacing(3)
        self._tool_calls_container_layout.addStretch()
        self._tool_calls_scroll.setWidget(self._tool_calls_container)
        layout.addWidget(self._tool_calls_scroll)

        # ---- Result section ----
        self._result_label = _fmt_label("📤 Result", font_size=10, bold=True, color=C_MEDIUM)
        layout.addWidget(self._result_label)

        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setFont(QFont("Menlo", 9))
        self._result_text.setStyleSheet(
            f"QTextEdit {{ background-color: {C_TOOL_BG}; border: 1px solid {C_BORDER}; "
            f"border-radius: 4px; padding: 8px; color: {C_DARK}; }}"
        )
        layout.addWidget(self._result_text, stretch=1)

        # ---- Error section ----
        self._error_label = _fmt_label("⚠ Error", font_size=10, bold=True, color=C_ERROR)
        layout.addWidget(self._error_label)

        self._error_text = QTextEdit()
        self._error_text.setReadOnly(True)
        self._error_text.setFont(QFont("Menlo", 9))
        self._error_text.setMaximumHeight(100)
        self._error_text.setStyleSheet(
            f"QTextEdit {{ background-color: #FDEDEC; border: 1px solid #E6B0AA; "
            f"border-radius: 4px; padding: 8px; color: {C_ERROR}; }}"
        )
        layout.addWidget(self._error_text)

        # ---- Close button ----
        close_btn = QPushButton("Close")
        close_btn.setFont(QFont("Arial", 10))
        close_btn.setFixedHeight(32)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C_BG_PANEL};
                border: 1px solid {C_BORDER2};
                border-radius: 4px;
                color: {C_MEDIUM};
            }}
            QPushButton:hover {{ background-color: {C_BORDER}; }}
        """)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _refresh(self):
        """从 AgentEntryWidget 拖取最新数据并刷新 UI。"""
        e = self._entry
        status = e._status
        color = _STATUS_COLORS.get(status, C_DARK)

        # Header
        self._header_icon.setText(_status_icon(status))
        self._header_icon.setStyleSheet(f"color: {color}; border: none; background: transparent;")
        self._header_task.setText(e._task)
        self._header_status.setText(_STATUS_LABELS.get(status, status))
        self._header_status.setStyleSheet(f"color: {color}; border: none; background: transparent;")

        # Meta badges
        _clear_layout(self._meta_layout, keep_stretch=False)
        if e._model:
            self._meta_layout.insertWidget(0, _fmt_badge(f"🧠 {e._model}", bg="#EBF5FB", fg=C_BLUE))
        if e._protocol:
            self._meta_layout.insertWidget(0, _fmt_badge(f"⚡ {e._protocol}", bg="#F4ECF7", fg="#6C3483"))
        self._meta_layout.addStretch()

        # Tools
        _clear_layout(self._tools_layout)
        if e._allowed_tools:
            self._tools_layout.addWidget(_fmt_label("Tools:", font_size=9, bold=True, color=C_MEDIUM))
            for t in e._allowed_tools[:12]:
                self._tools_layout.addWidget(_fmt_badge(t))
            if len(e._allowed_tools) > 12:
                self._tools_layout.addWidget(_fmt_badge(f"+{len(e._allowed_tools) - 12}"))
            self._tools_layout.addStretch()

        # Tool calls
        _clear_layout(self._tool_calls_container_layout, keep_stretch=False)
        has_calls = bool(e._tool_calls_log)
        self._tool_calls_label.setVisible(has_calls)
        self._tool_calls_scroll.setVisible(has_calls)
        if has_calls:
            for i, call in enumerate(e._tool_calls_log):
                _add_tool_call_row(self._tool_calls_container_layout, i, call)
            self._tool_calls_container_layout.addStretch()

        # Result
        is_ok = status == "completed"
        self._result_label.setVisible(is_ok and bool(e._result))
        self._result_text.setVisible(is_ok and bool(e._result))
        if is_ok and e._result:
            self._result_text.setPlainText(e._result)

        # Error
        is_err = status in ("failed", "cancelled") and bool(e._result)
        self._error_label.setVisible(is_err)
        self._error_text.setVisible(is_err)
        if is_err:
            self._error_text.setPlainText(e._result)

    # ------------------------------------------------------------------
    # Called by AgentEntryWidget when status updates
    # ------------------------------------------------------------------

    def refresh_from_entry(self):
        """外部调用：entry 状态更新后刷新弹窗。"""
        self._refresh()


# ------------------------------------------------------------------
# AgentEntryWidget — single summary row
# ------------------------------------------------------------------


class AgentEntryWidget(QFrame):
    """单行摘要条目：状态图标 + 任务文字 + 耗时 + 取消 + 详情按钮。

    点击整行或「详情」按钮打开 AgentDetailDialog。
    """

    cancelled = pyqtSignal(str)  # agent_id
    detail_requested = pyqtSignal(object)  # self

    MAX_TASK_LEN = 70

    def __init__(self, agent_id: str, task: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.agent_id = agent_id
        self._task = task or "(no description)"
        self._status = "running"
        self._result: str = ""
        self._start_time = time.time()

        # Execution metadata (filled by update)
        self._model: str = ""
        self._protocol: str = ""
        self._allowed_tools: List[str] = []
        self._tool_calls_log: List[Dict[str, Any]] = []

        self.setObjectName("agentEntry")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"""
            QFrame#agentEntry {{
                background-color: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
            }}
            QFrame#agentEntry:hover {{ background-color: {C_TOOL_BG}; }}
            QFrame#agentEntry QLabel {{ color: {C_DARK}; }}
        """)

        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(5, 3, 5, 3)
        outer.setSpacing(0)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(0, 0, 0, 0)

        self._icon_label = QLabel(_status_icon(self._status))
        self._icon_label.setFixedWidth(20)
        self._icon_label.setFont(QFont("Arial", 11))
        row.addWidget(self._icon_label)

        task_text = self._task[:self.MAX_TASK_LEN]
        if len(self._task) > self.MAX_TASK_LEN:
            task_text += "…"
        self._task_label = QLabel(task_text)
        self._task_label.setFont(QFont("Arial", 10))
        self._task_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(self._task_label, stretch=1)

        self._elapsed_label = QLabel(_elapsed_str(self._start_time))
        self._elapsed_label.setFont(QFont("Arial", 9))
        row.addWidget(self._elapsed_label)

        self._cancel_button = QPushButton("cancel")
        self._cancel_button.setFixedSize(50, 20)
        self._cancel_button.setFont(QFont("Arial", 8))
        self._cancel_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #FFF3E6;
                border: 1px solid {C_BORDER2};
                border-radius: 3px;
                color: {C_MEDIUM};
            }}
            QPushButton:hover {{ background-color: #F5E6D3; }}
        """)
        self._cancel_button.clicked.connect(lambda: self.cancelled.emit(self.agent_id))
        row.addWidget(self._cancel_button)

        self._detail_btn = QPushButton("detail")
        self._detail_btn.setFixedSize(42, 20)
        self._detail_btn.setFont(QFont("Arial", 8))
        self._detail_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C_TOOL_BG};
                border: 1px solid {C_BORDER2};
                border-radius: 3px;
                color: {C_ACCENT};
            }}
            QPushButton:hover {{ background-color: {C_BORDER}; }}
        """)
        self._detail_btn.clicked.connect(lambda: self.detail_requested.emit(self))
        row.addWidget(self._detail_btn)

        outer.addLayout(row)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_status(self, status: str, result: str, extra: Optional[Dict[str, Any]] = None):
        """主线程调用：更新状态、元数据。"""
        self._status = status
        self._icon_label.setText(_status_icon(status))
        self._elapsed_label.setText(_elapsed_str(self._start_time))

        color = _STATUS_COLORS.get(status, C_DARK)
        self._icon_label.setStyleSheet(f"border: none; background: transparent; color: {color};")

        is_done = status in ("completed", "failed", "cancelled")
        if is_done:
            self._cancel_button.setEnabled(False)
            self._cancel_button.setText("-")
            self._cancel_button.setStyleSheet("border: none; background: transparent; color: #AAA;")

        if extra:
            self._model = extra.get("model", "") or ""
            self._protocol = extra.get("protocol", "") or ""
            self._allowed_tools = extra.get("allowed_tools", []) or []
            self._tool_calls_log = extra.get("tool_calls_log", []) or []

        if result:
            self._result = result

        # Refresh open detail dialog if any
        dlg = AgentDetailDialog._instances.get(self.agent_id)
        if dlg is not None and dlg.isVisible():
            dlg.refresh_from_entry()

    def _tick(self):
        """每秒更新耗时。"""
        if self._status in ("running", "spawned"):
            self._elapsed_label.setText(_elapsed_str(self._start_time))


# ------------------------------------------------------------------
# SubAgentPanel (container)
# ------------------------------------------------------------------


class SubAgentPanel(QFrame):
    """可折叠的子 agent 实时面板。

    线程安全：registry 回调在后台线程 → emit signal → QueuedConnection 入队主线程。
    """

    # (agent_id, status, task, result, extra_json)
    status_updated = pyqtSignal(str, str, str, str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._entries: Dict[str, AgentEntryWidget] = {}
        self._registry: Optional["SubAgentRegistry"] = None
        self._collapsed = True

        self.setObjectName("subAgentPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            QFrame#subAgentPanel {{
                background-color: {C_BG_PANEL};
                border: 1px solid {C_BORDER2};
                border-radius: 6px;
            }}
            QFrame#subAgentPanel QLabel {{ color: {C_DARK}; }}
            QFrame#subAgentPanel QPushButton {{ color: {C_DARK}; }}
        """)

        self._build_ui()

        self.status_updated.connect(self._on_status, Qt.ConnectionType.QueuedConnection)

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick_all)
        self._tick_timer.start(1000)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- 标题栏 ----
        header = QHBoxLayout()
        header.setContentsMargins(8, 3, 8, 3)

        self._title_label = QLabel("🔄 Sub Agents")
        self._title_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        header.addWidget(self._title_label)

        header.addStretch()

        self._collapse_btn = QPushButton("▾")
        self._collapse_btn.setFixedSize(22, 22)
        self._collapse_btn.setFont(QFont("Arial", 9))
        self._collapse_btn.setStyleSheet(f"border: none; background: transparent; color: {C_MEDIUM};")
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        header.addWidget(self._collapse_btn)

        outer.addLayout(header)

        # ---- 条目容器 (scrollable) ----
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._container = QWidget()
        self._container.setStyleSheet("background-color: transparent;")
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(4, 0, 4, 4)
        self._container_layout.setSpacing(3)
        self._container_layout.addStretch()

        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll)

        self._scroll.hide()

    # ------------------------------------------------------------------
    # Registry binding
    # ------------------------------------------------------------------

    def connect_registry(self, registry: "SubAgentRegistry"):
        self.disconnect_registry()
        self._registry = registry
        registry.on_agent_status_change(self._on_registry_change)
        self._title_label.setText("🔄 Sub Agents (0)")
        self._collapse_btn.setText("▸")
        self._collapsed = True
        self._scroll.hide()
        self.show()
        logger.info("SubAgentPanel connected to registry")

    def disconnect_registry(self):
        if self._registry is not None:
            self._registry.remove_callback(self._on_registry_change)
            self._registry = None
        self._collapsed = True
        self._scroll.hide()
        self._title_label.setText("🔄 Sub Agents")
        self.hide()

    # ------------------------------------------------------------------
    # Callbacks (thread-safe)
    # ------------------------------------------------------------------

    def _on_registry_change(self, agent_id: str, status: str, task: str, result: Optional[str], extra: Dict[str, Any]):
        extra_json = json.dumps(extra or {}, ensure_ascii=False)
        self.status_updated.emit(agent_id, status, task, result or "", extra_json)

    def _on_status(self, agent_id: str, status: str, task: str, result: str, extra_json: str):
        if agent_id == "main":
            return

        try:
            extra = json.loads(extra_json) if extra_json else {}
        except json.JSONDecodeError:
            extra = {}

        if agent_id not in self._entries:
            entry = AgentEntryWidget(agent_id, task, self)
            entry.cancelled.connect(self._on_cancel_agent)
            entry.detail_requested.connect(self._on_detail_requested)
            self._container_layout.insertWidget(
                max(0, self._container_layout.count() - 1), entry
            )
            self._entries[agent_id] = entry
            self._expand_if_collapsed()

        entry = self._entries[agent_id]
        entry.update_status(status, result, extra)
        self._update_title()
        self._schedule_auto_collapse()

    def _on_cancel_agent(self, agent_id: str):
        if self._registry:
            self._registry.cancel(agent_id)
            logger.info("User cancelled sub-agent '%s' via panel", agent_id)

    def _on_detail_requested(self, entry: AgentEntryWidget):
        """打开详情弹窗。"""
        AgentDetailDialog.open_for(entry, parent=self)

    # ------------------------------------------------------------------
    # Collapse / expand
    # ------------------------------------------------------------------

    def _expand_if_collapsed(self):
        if self._collapsed:
            self._collapsed = False
            self._scroll.show()
            self._collapse_btn.setText("▾")

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self._scroll.setVisible(not self._collapsed)
        self._collapse_btn.setText("▸" if self._collapsed else "▾")

    def _schedule_auto_collapse(self):
        active = sum(1 for e in self._entries.values() if e._status in ("running", "spawned"))
        if active == 0 and self._entries:
            QTimer.singleShot(5000, self._auto_collapse_if_all_done)

    def _auto_collapse_if_all_done(self):
        active = sum(1 for e in self._entries.values() if e._status in ("running", "spawned"))
        if active == 0 and not self._collapsed:
            self._collapsed = True
            self._scroll.hide()
            self._collapse_btn.setText("▸")

    # ------------------------------------------------------------------
    # Periodic updates
    # ------------------------------------------------------------------

    def _tick_all(self):
        for entry in self._entries.values():
            entry._tick()

    def _update_title(self):
        active = sum(1 for e in self._entries.values() if e._status in ("running", "spawned"))
        total = len(self._entries)
        done = total - active
        self._title_label.setText(f"🔄 Sub Agents ({active} running, {done} done, {total} total)")

    def closeEvent(self, event):
        self.disconnect_registry()
        self._tick_timer.stop()
        super().closeEvent(event)


# ------------------------------------------------------------------
# Layout helpers
# ------------------------------------------------------------------

def _clear_layout(layout, keep_stretch: bool = False):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _add_tool_call_row(layout, index: int, call: Dict[str, Any]):
    tool_name = call.get("tool", "?")
    args_str = call.get("args", "{}")
    result_str = call.get("result", "")

    row = QWidget()
    row_layout = QVBoxLayout(row)
    row_layout.setContentsMargins(0, 1, 0, 1)
    row_layout.setSpacing(1)

    call_text = f"#{index + 1} <b>{tool_name}</b>(<span style='color:{C_MEDIUM};'>{args_str[:120]}</span>)"
    call_lbl = QLabel(call_text)
    call_lbl.setFont(QFont("Arial", 9))
    call_lbl.setStyleSheet(f"color: {C_DARK}; border: none; background: transparent; padding: 2px 0 0 4px;")
    call_lbl.setWordWrap(True)
    call_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    row_layout.addWidget(call_lbl)

    if result_str:
        preview = result_str[:200]
        if len(result_str) > 200:
            preview += "..."
        res_lbl = QLabel(preview)
        res_lbl.setFont(QFont("Arial", 8))
        res_lbl.setStyleSheet(
            f"color: #4A2C2A; border: none; background-color: #FFF8F0; "
            f"border-radius: 3px; padding: 3px 6px; margin-left: 12px;"
        )
        res_lbl.setWordWrap(True)
        res_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row_layout.addWidget(res_lbl)

    layout.addWidget(row)
