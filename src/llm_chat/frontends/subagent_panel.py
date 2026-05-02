"""SubAgent Panel — 子 Agent 实时运行面板

线程安全：registry 回调在后台线程触发 → pyqtSignal + QueuedConnection → 主线程更新 UI。
"""

from __future__ import annotations

import time
import logging
from typing import Dict, Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)
from PyQt6.QtGui import QFont

if TYPE_CHECKING:
    from llm_chat.skills.task_delegator.registry import SubAgentRegistry

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Status helpers
# ------------------------------------------------------------------

_STATUS_ICONS = {
    "running": "\U0001F7E1",      # 🟡
    "spawned": "\U0001F535",      # 🔵
    "completed": "\u2705",        # ✅
    "failed": "\u274C",           # ❌
    "cancelled": "\u2298",        # ⊘
}

_STATUS_TEXT = {
    "running": "running",
    "spawned": "spawned",
    "completed": "ok",
    "failed": "failed",
    "cancelled": "cancelled",
}


def _status_icon(status: str) -> str:
    return _STATUS_ICONS.get(status, "\u2753")  # ❓ fallback


def _elapsed_str(start: float) -> str:
    dt = time.time() - start
    if dt < 60:
        return f"{dt:.1f}s"
    m, s = divmod(int(dt), 60)
    return f"{m}m{s}s"


# ------------------------------------------------------------------
# AgentEntryWidget
# ------------------------------------------------------------------


class AgentEntryWidget(QFrame):
    """单个子 agent 的显示条目。"""

    cancelled = pyqtSignal(str)  # agent_id

    def __init__(self, agent_id: str, task: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.agent_id = agent_id
        self._task = task or "(no description)"
        self._status = "running"
        self._result: str = ""
        self._start_time = time.time()
        self._expanded = False

        self.setObjectName("agentEntry")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("""
            QFrame#agentEntry {
                background-color: #FFFCF7;
                border: 1px solid #E8D5C4;
                border-radius: 4px;
            }
            QLabel { color: #3D2C2E; }
        """)

        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(2)

        # ---- 摘要行 ----
        summary = QHBoxLayout()
        summary.setSpacing(6)

        self._icon_label = QLabel(_status_icon(self._status))
        self._icon_label.setFixedWidth(20)
        self._icon_label.setStyleSheet("border: none; background: transparent; color: #3D2C2E;")
        summary.addWidget(self._icon_label)

        task_text = self._task[:60] + ("..." if len(self._task) > 60 else "")
        self._task_label = QLabel(task_text)
        self._task_label.setFont(QFont("Arial", 10))
        self._task_label.setStyleSheet("color: #3D2C2E; border: none; background: transparent;")
        self._task_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        summary.addWidget(self._task_label, stretch=1)

        self._elapsed_label = QLabel(_elapsed_str(self._start_time))
        self._elapsed_label.setFont(QFont("Arial", 9))
        self._elapsed_label.setStyleSheet("color: #6B4423; border: none; background: transparent;")
        summary.addWidget(self._elapsed_label)

        self._cancel_button = QPushButton("cancel")
        self._cancel_button.setFixedSize(50, 20)
        self._cancel_button.setFont(QFont("Arial", 8))
        self._cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #FFF3E6;
                border: 1px solid #D4A574;
                border-radius: 3px;
                color: #6B4423;
            }
            QPushButton:hover { background-color: #F5E6D3; }
        """)
        self._cancel_button.clicked.connect(lambda: self.cancelled.emit(self.agent_id))
        summary.addWidget(self._cancel_button)

        self._expand_btn = QPushButton("▸")
        self._expand_btn.setFixedSize(20, 20)
        self._expand_btn.setFont(QFont("Arial", 8))
        self._expand_btn.setStyleSheet("border: none; background: transparent; color: #6B4423;")
        self._expand_btn.clicked.connect(self._toggle_expand)
        summary.addWidget(self._expand_btn)

        outer.addLayout(summary)

        # ---- 详情区（默认隐藏） ----
        self._detail = QLabel("")
        self._detail.setFont(QFont("Arial", 9))
        self._detail.setStyleSheet("color: #4A2C2A; padding: 2px 0 2px 26px; border: none; background: transparent;")
        self._detail.setWordWrap(True)
        self._detail.setMaximumHeight(0)
        self._detail.hide()
        outer.addWidget(self._detail)

    def update_status(self, status: str, result: str):
        """主线程调用：更新状态图标、时间、详情。"""
        self._status = status
        self._icon_label.setText(_status_icon(status))
        self._elapsed_label.setText(_elapsed_str(self._start_time))

        is_done = status in ("completed", "failed", "cancelled")
        if is_done:
            self._cancel_button.setEnabled(False)
            self._cancel_button.setText("")
            self._cancel_button.setStyleSheet("border: none; background: transparent;")

        if result:
            self._result = result[:500]
            self._detail.setText(result[:500])

    def _toggle_expand(self):
        self._expanded = not self._expanded
        if self._expanded:
            self._detail.show()
            self._detail.setMaximumHeight(200)
            self._expand_btn.setText("▾")
        else:
            self._detail.hide()
            self._detail.setMaximumHeight(0)
            self._expand_btn.setText("▸")

    def _tick(self):
        """每秒更新耗时。"""
        if self._status in ("running", "spawned"):
            self._elapsed_label.setText(_elapsed_str(self._start_time))


# ------------------------------------------------------------------
# SubAgentPanel
# ------------------------------------------------------------------


class SubAgentPanel(QFrame):
    """可折叠的子 agent 实时面板。

    线程安全：registry 回调在后台线程 → emit signal → QueuedConnection 入队主线程。
    """

    #: registry 回调触发此 signal（在后台线程 emit，自动排队到主线程）
    status_updated = pyqtSignal(str, str, str, str)  # agent_id, status, task, result

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._entries: Dict[str, AgentEntryWidget] = {}
        self._registry: Optional[SubAgentRegistry] = None
        self._collapsed = True
        self._all_done_timer: Optional[int] = None  # 自动折叠延时 id

        self.setObjectName("subAgentPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            QFrame#subAgentPanel {
                background-color: #F5E6D3;
                border: 1px solid #D4A574;
                border-radius: 6px;
            }
            QLabel { color: #3D2C2E; }
            QPushButton { color: #3D2C2E; }
        """)

        self._build_ui()

        # signal → slot（QueuedConnection 确保主线程执行）
        self.status_updated.connect(self._on_status, Qt.ConnectionType.QueuedConnection)

        # 每秒刷新耗时
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick_all)
        self._tick_timer.start(1000)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- 标题栏 ----
        header = QHBoxLayout()
        header.setContentsMargins(8, 2, 8, 2)

        self._title_label = QLabel("🔄 Sub Agents")
        self._title_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self._title_label.setStyleSheet("color: #6B4423; border: none; background: transparent;")
        header.addWidget(self._title_label)

        header.addStretch()

        self._collapse_btn = QPushButton("▾")
        self._collapse_btn.setFixedSize(20, 20)
        self._collapse_btn.setFont(QFont("Arial", 8))
        self._collapse_btn.setStyleSheet("border: none; background: transparent; color: #6B4423;")
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        header.addWidget(self._collapse_btn)

        outer.addLayout(header)

        # ---- 条目容器 ----
        self._container = QWidget()
        self._container.setStyleSheet("QLabel { color: #3D2C2E; }")
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(2, 0, 2, 2)
        self._container_layout.setSpacing(2)
        self._container_layout.addStretch()
        outer.addWidget(self._container)

        self._container.hide()

    # ------------------------------------------------------------------
    # Registry binding
    # ------------------------------------------------------------------

    def connect_registry(self, registry: SubAgentRegistry):
        """绑定到 SubAgentRegistry。重复调用安全（先解绑旧 registry）。"""
        self.disconnect_registry()
        self._registry = registry
        registry.on_agent_status_change(self._on_registry_change)
        # 显示折叠的入口
        self._title_label.setText("🔄 Sub Agents (0)")
        self._title_label.setStyleSheet("color: #3D2C2E; border: none; background: transparent;")
        self._collapse_btn.setText("▸")
        self._collapsed = True
        self._container.hide()
        self.show()
        logger.info("SubAgentPanel connected to registry")

    def disconnect_registry(self):
        """解绑，widget 销毁时调用防止悬垂回调。"""
        if self._registry is not None:
            self._registry.remove_callback(self._on_registry_change)
            self._registry = None
        # 无 registry 时完全隐藏
        self._collapsed = True
        self._container.hide()
        self._title_label.setText("🔄 Sub Agents")
        self._title_label.setStyleSheet("color: #6B4423; border: none; background: transparent;")
        self.hide()

    # ------------------------------------------------------------------
    # Callbacks (thread-safe)
    # ------------------------------------------------------------------

    def _on_registry_change(self, agent_id: str, status: str, task: str, result: Optional[str]):
        """后台线程回调：发射 signal 跨线程。"""
        self.status_updated.emit(agent_id, status, task, result or "")

    def _on_status(self, agent_id: str, status: str, task: str, result: str):
        """主线程 slot：创建或更新条目。"""
        # 系统内部 agent（如根 "main"）不显示
        if agent_id == "main":
            return

        if agent_id not in self._entries:
            entry = AgentEntryWidget(agent_id, task, self)
            entry.cancelled.connect(self._on_cancel_agent)
            self._container_layout.insertWidget(
                max(0, self._container_layout.count() - 1), entry
            )
            self._entries[agent_id] = entry
            self._expand_if_collapsed()

        entry = self._entries[agent_id]
        entry.update_status(status, result)
        self._update_title()

        # 全部完成 → 延迟自动折叠
        self._schedule_auto_collapse()

    def _on_cancel_agent(self, agent_id: str):
        """用户点击取消按钮。"""
        if self._registry:
            self._registry.cancel(agent_id)
            logger.info("User cancelled sub-agent '%s' via panel", agent_id)

    # ------------------------------------------------------------------
    # Collapse / expand
    # ------------------------------------------------------------------

    def _expand_if_collapsed(self):
        if self._collapsed:
            self._collapsed = False
            self._container.show()
            self._collapse_btn.setText("▾")

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self._container.setVisible(not self._collapsed)
        self._collapse_btn.setText("▸" if self._collapsed else "▾")

    def _schedule_auto_collapse(self):
        active = sum(
            1 for e in self._entries.values()
            if e._status in ("running", "spawned")
        )
        if active == 0 and self._entries:
            # 全部完成，5 秒后折叠
            QTimer.singleShot(5000, self._auto_collapse_if_all_done)

    def _auto_collapse_if_all_done(self):
        active = sum(
            1 for e in self._entries.values()
            if e._status in ("running", "spawned")
        )
        if active == 0 and not self._collapsed:
            self._collapsed = True
            self._container.hide()
            self._collapse_btn.setText("▸")

    # ------------------------------------------------------------------
    # Periodic updates
    # ------------------------------------------------------------------

    def _tick_all(self):
        """每秒更新所有运行中条目的耗时。"""
        for entry in self._entries.values():
            entry._tick()

    def _update_title(self):
        active = sum(
            1 for e in self._entries.values()
            if e._status in ("running", "spawned")
        )
        total = len(self._entries)
        self._title_label.setText(f"🔄 Sub Agents ({active} active, {total} total)")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self.disconnect_registry()
        self._tick_timer.stop()
        super().closeEvent(event)
