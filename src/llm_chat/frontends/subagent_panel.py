"""SubAgent Panel — 子 Agent 实时运行面板

展开后展示：模型/协议、工具白名单、工具调用时间线、完整结果。

线程安全：registry 回调在后台线程触发 → pyqtSignal + QueuedConnection → 主线程更新 UI。
"""

from __future__ import annotations

import json
import time
import logging
from typing import Dict, Optional, Any, List, TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QScrollArea,
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
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


def _fmt_badge(text: str, bg: str = "#FDF2E9", fg: str = C_MEDIUM) -> QLabel:
    badge = QLabel(text)
    badge.setFont(QFont("Arial", 9))
    badge.setStyleSheet(
        f"color: {fg}; background-color: {bg}; border: 1px solid {C_BORDER}; "
        f"border-radius: 3px; padding: 0 4px;"
    )
    badge.setFixedHeight(18)
    return badge


# ------------------------------------------------------------------
# AgentEntryWidget
# ------------------------------------------------------------------


class AgentEntryWidget(QFrame):
    """单个子 agent 的显示条目。展开后显示执行全貌。"""

    cancelled = pyqtSignal(str)  # agent_id

    # Limits
    MAX_RESULT_LINES = 30
    MAX_TOOL_RESULT_LINES = 5
    MAX_TASK_LEN = 80

    def __init__(self, agent_id: str, task: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.agent_id = agent_id
        self._task = task or "(no description)"
        self._status = "running"
        self._result: str = ""
        self._start_time = time.time()
        self._expanded = False

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
            QFrame#agentEntry QLabel {{ color: {C_DARK}; }}
        """)

        self._build_ui()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 3, 4, 3)
        outer.setSpacing(0)

        # ---- 摘要行 ----
        summary = QHBoxLayout()
        summary.setSpacing(6)
        summary.setContentsMargins(0, 0, 0, 0)

        self._icon_label = QLabel(_status_icon(self._status))
        self._icon_label.setFixedWidth(20)
        summary.addWidget(self._icon_label)

        task_text = self._task[:self.MAX_TASK_LEN]
        if len(self._task) > self.MAX_TASK_LEN:
            task_text += "..."
        self._task_label = QLabel(task_text)
        self._task_label.setFont(QFont("Arial", 10))
        self._task_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        summary.addWidget(self._task_label, stretch=1)

        self._elapsed_label = QLabel(_elapsed_str(self._start_time))
        self._elapsed_label.setFont(QFont("Arial", 9))
        summary.addWidget(self._elapsed_label)

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
        summary.addWidget(self._cancel_button)

        self._expand_btn = QPushButton("▸")
        self._expand_btn.setFixedSize(20, 20)
        self._expand_btn.setFont(QFont("Arial", 9))
        self._expand_btn.setStyleSheet(f"border: none; background: transparent; color: {C_MEDIUM};")
        self._expand_btn.clicked.connect(self._toggle_expand)
        summary.addWidget(self._expand_btn)

        outer.addLayout(summary)

        # ---- 详情区（默认隐藏） ----
        self._detail_container = QWidget()
        self._detail_container.hide()
        self._detail_container.setStyleSheet(f"background-color: transparent;")
        self._detail_layout = QVBoxLayout(self._detail_container)
        self._detail_layout.setContentsMargins(26, 4, 4, 4)
        self._detail_layout.setSpacing(4)
        outer.addWidget(self._detail_container)

        # 子区域（动态填充）
        self._meta_row = QWidget()
        self._meta_layout = QHBoxLayout(self._meta_row)
        self._meta_layout.setContentsMargins(0, 0, 0, 0)
        self._meta_layout.setSpacing(6)
        self._meta_layout.addStretch()
        self._detail_layout.addWidget(self._meta_row)

        self._tools_row = QWidget()
        self._tools_layout = QHBoxLayout(self._tools_row)
        self._tools_layout.setContentsMargins(0, 0, 0, 0)
        self._tools_layout.setSpacing(4)
        self._detail_layout.addWidget(self._tools_row)
        self._tools_row.hide()

        self._tool_calls_section = QWidget()
        self._tool_calls_section_layout = QVBoxLayout(self._tool_calls_section)
        self._tool_calls_section_layout.setContentsMargins(0, 0, 0, 0)
        self._tool_calls_section_layout.setSpacing(2)
        self._detail_layout.addWidget(self._tool_calls_section)
        self._tool_calls_section.hide()

        self._result_section = QWidget()
        self._result_section_layout = QVBoxLayout(self._result_section)
        self._result_section_layout.setContentsMargins(0, 0, 0, 0)
        self._result_section_layout.setSpacing(2)
        self._detail_layout.addWidget(self._result_section)
        self._result_section.hide()

        self._error_section = QWidget()
        self._error_section_layout = QVBoxLayout(self._error_section)
        self._error_section_layout.setContentsMargins(0, 0, 0, 0)
        self._error_section_layout.setSpacing(2)
        self._detail_layout.addWidget(self._error_section)
        self._error_section.hide()

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_status(self, status: str, result: str, extra: Optional[Dict[str, Any]] = None):
        """主线程调用：更新状态、元数据、详情。"""
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

        # Parse extra metadata
        if extra:
            self._model = extra.get("model", "")
            self._protocol = extra.get("protocol", "")
            self._allowed_tools = extra.get("allowed_tools", []) or []
            self._tool_calls_log = extra.get("tool_calls_log", []) or []

        if result:
            self._result = result

        # Rebuild detail sections
        self._rebuild_details()

    def _rebuild_details(self):
        """根据最新元数据重建详情区域。"""
        # --- Meta badges (model, protocol) ---
        _clear_layout(self._meta_layout, keep_stretch=False)
        if self._model:
            model_badge = _fmt_badge(f"🧠 {self._model}", bg="#EBF5FB", fg=C_BLUE)
            self._meta_layout.insertWidget(0, model_badge)
        if self._protocol:
            proto_badge = _fmt_badge(f"⚡ {self._protocol}", bg="#F4ECF7", fg="#6C3483")
            self._meta_layout.insertWidget(0, proto_badge)
        self._meta_layout.addStretch()

        # --- Tools row ---
        _clear_layout(self._tools_layout)
        if self._allowed_tools:
            tools_label = _fmt_label("Tools:", font_size=9, bold=True, color=C_MEDIUM)
            self._tools_layout.addWidget(tools_label)
            for t in self._allowed_tools[:10]:
                self._tools_layout.addWidget(_fmt_badge(t))
            if len(self._allowed_tools) > 10:
                self._tools_layout.addWidget(_fmt_badge(f"+{len(self._allowed_tools) - 10}"))
            self._tools_layout.addStretch()
            self._tools_row.show()
        else:
            self._tools_row.hide()

        # --- Tool calls timeline ---
        _clear_layout(self._tool_calls_section_layout)
        if self._tool_calls_log:
            _add_section_header(self._tool_calls_section_layout, "📋 Tool Calls")
            for i, call in enumerate(self._tool_calls_log):
                _add_tool_call_row(self._tool_calls_section_layout, i, call)
            self._tool_calls_section.show()
        else:
            self._tool_calls_section.hide()

        # --- Result section ---
        _clear_layout(self._result_section_layout)
        if self._result and self._status in ("completed",):
            _add_section_header(self._result_section_layout, "📤 Result")
            # Truncate to MAX_RESULT_LINES
            lines = self._result.split("\n")
            display = "\n".join(lines[:self.MAX_RESULT_LINES])
            if len(lines) > self.MAX_RESULT_LINES:
                display += f"\n... ({len(lines) - self.MAX_RESULT_LINES} more lines)"
            result_label = _fmt_label(display, font_size=9, color=C_DARK)
            result_label.setStyleSheet(
                f"color: {C_DARK}; border: none; background: {C_TOOL_BG}; "
                f"border-radius: 4px; padding: 6px 8px;"
            )
            self._result_section_layout.addWidget(result_label)
            self._result_section.show()
        else:
            self._result_section.hide()

        # --- Error section ---
        _clear_layout(self._error_section_layout)
        if self._status in ("failed", "cancelled") and self._result:
            _add_section_header(self._error_section_layout, "⚠ Error")
            err_label = _fmt_label(self._result, font_size=9, color=C_ERROR)
            err_label.setStyleSheet(
                f"color: {C_ERROR}; border: none; background: #FDEDEC; "
                f"border-radius: 4px; padding: 6px 8px;"
            )
            self._error_section_layout.addWidget(err_label)
            self._error_section.show()
        else:
            self._error_section.hide()

    # ------------------------------------------------------------------
    # Expand / collapse
    # ------------------------------------------------------------------

    def _toggle_expand(self):
        self._expanded = not self._expanded
        if self._expanded:
            self._detail_container.show()
            self._expand_btn.setText("▾")
        else:
            self._detail_container.hide()
            self._expand_btn.setText("▸")

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
    signal 传递 extra 字典 (JSON 字符串，跨线程安全)。
    """

    # (agent_id, status, task, result, extra_json)
    status_updated = pyqtSignal(str, str, str, str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._entries: Dict[str, AgentEntryWidget] = {}
        self._registry: Optional[SubAgentRegistry] = None
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

        # signal → slot (QueuedConnection)
        self.status_updated.connect(self._on_status, Qt.ConnectionType.QueuedConnection)

        # Tick timer
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
        self._scroll.setStyleSheet(f"QScrollArea {{ border: none; background: transparent; }}")

        self._container = QWidget()
        self._container.setStyleSheet(f"background-color: transparent;")
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(4, 0, 4, 4)
        self._container_layout.setSpacing(3)
        self._container_layout.addStretch()

        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll)

        # 初始隐藏
        self._scroll.hide()

    # ------------------------------------------------------------------
    # Registry binding
    # ------------------------------------------------------------------

    def connect_registry(self, registry: SubAgentRegistry):
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
        """后台线程回调：发射 signal 跨线程。extra 序列化为 JSON 保证线程安全。"""
        extra_json = json.dumps(extra or {}, ensure_ascii=False)
        self.status_updated.emit(agent_id, status, task, result or "", extra_json)

    def _on_status(self, agent_id: str, status: str, task: str, result: str, extra_json: str):
        """主线程 slot：创建或更新条目。"""
        if agent_id == "main":
            return

        # 反序列化 extra
        try:
            extra = json.loads(extra_json) if extra_json else {}
        except json.JSONDecodeError:
            extra = {}

        if agent_id not in self._entries:
            entry = AgentEntryWidget(agent_id, task, self)
            entry.cancelled.connect(self._on_cancel_agent)
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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self.disconnect_registry()
        self._tick_timer.stop()
        super().closeEvent(event)


# ------------------------------------------------------------------
# Layout helpers
# ------------------------------------------------------------------

def _clear_layout(layout, keep_stretch: bool = False):
    """Remove all widgets from a layout."""
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _add_section_header(layout, text: str):
    """Add a section header label to the layout."""
    lbl = _fmt_label(text, font_size=9, bold=True, color=C_MEDIUM)
    layout.addWidget(lbl)


def _add_tool_call_row(layout, index: int, call: Dict[str, Any]):
    """Add a single tool call entry to the layout.

    Shows: #N tool_name(args) → result_summary
    """
    tool_name = call.get("tool", "?")
    args_str = call.get("args", "{}")
    result_str = call.get("result", "")

    row = QWidget()
    row_layout = QVBoxLayout(row)
    row_layout.setContentsMargins(0, 1, 0, 1)
    row_layout.setSpacing(1)

    # Tool call header: "#1 web_search(...)"
    call_text = f"#{index + 1} <b>{tool_name}</b>(<span style='color:{C_LIGHT};'>{args_str[:120]}</span>)"
    call_lbl = QLabel(call_text)
    call_lbl.setFont(QFont("Arial", 9))
    call_lbl.setStyleSheet(f"color: {C_DARK}; border: none; background: transparent; padding: 0 0 0 4px;")
    call_lbl.setWordWrap(True)
    call_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    row_layout.addWidget(call_lbl)

    # Result preview (truncated)
    if result_str:
        preview = result_str[:200]
        if len(result_str) > 200:
            preview += "..."
        res_lbl = QLabel(preview)
        res_lbl.setFont(QFont("Arial", 8))
        res_lbl.setStyleSheet(
            f"color: {C_MEDIUM}; border: none; background: {C_TOOL_BG}; "
            f"border-radius: 3px; padding: 2px 6px; margin-left: 12px;"
        )
        res_lbl.setWordWrap(True)
        res_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row_layout.addWidget(res_lbl)

    layout.addWidget(row)
