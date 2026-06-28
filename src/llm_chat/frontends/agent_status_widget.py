"""AgentStatusWidget — PyQt6 widget showing sub-agent execution tree.

Displays agent hierarchy, status, role, and tool call count in real time.
Connects to SubAgentRegistry's status changes via polling or callbacks.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QPushButton, QHBoxLayout, QHeaderView,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

logger = logging.getLogger(__name__)

# Status icons
STATUS_ICONS = {
    "spawned":   "⏳",
    "running":   "⏳",
    "completed": "✅",
    "failed":    "❌",
    "timeout":   "⏰",
    "cancelled": "◼️",
    "rejected":  "🚫",
    "waiting":   "⏸",
}


class AgentStatusWidget(QWidget):
    """Collapsible panel showing sub-agent execution status.

    Usage:
        widget = AgentStatusWidget(registry)
        widget.refresh()
        # Or enable auto-refresh:
        widget.set_auto_refresh(2000)  # every 2 seconds
    """

    refresh_requested = pyqtSignal()
    agent_selected = pyqtSignal(str)  # agent_id

    def __init__(
        self,
        registry=None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._registry = registry
        self._timer: Optional[QTimer] = None
        self._collapsed = False

        self._setup_ui()

    def set_registry(self, registry):
        self._registry = registry

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        self._title = QLabel("🕸 子 Agent (0)")
        self._title.setStyleSheet("font-weight: bold; color: #888;")
        header.addWidget(self._title)

        self._toggle_btn = QPushButton("−")
        self._toggle_btn.setFixedSize(24, 24)
        self._toggle_btn.setStyleSheet("border: none; font-size: 14px;")
        self._toggle_btn.clicked.connect(self._toggle)
        header.addWidget(self._toggle_btn)

        header.addStretch()
        layout.addLayout(header)

        # Tree
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Agent", "Role", "Status", "Calls"])
        self._tree.setColumnWidth(0, 160)
        self._tree.setColumnWidth(1, 80)
        self._tree.setColumnWidth(2, 60)
        self._tree.setColumnWidth(3, 50)
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(16)
        self._tree.setStyleSheet("""
            QTreeWidget {
                font-size: 11px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            QTreeWidget::item {
                padding: 2px 4px;
            }
            QHeaderView::section {
                font-size: 10px;
                padding: 2px 4px;
                background: #f5f5f5;
                border: none;
                border-bottom: 1px solid #ddd;
            }
        """)
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree)

        self.setMaximumHeight(300)

    def _toggle(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._tree.hide()
            self._toggle_btn.setText("+")
        else:
            self._tree.show()
            self._toggle_btn.setText("−")

    def _on_item_clicked(self, item, col):
        agent_id = item.data(0, Qt.ItemDataRole.UserRole)
        if agent_id:
            self.agent_selected.emit(agent_id)

    def set_auto_refresh(self, interval_ms: int = 2000):
        """Enable periodic auto-refresh."""
        if self._timer:
            self._timer.stop()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(interval_ms)

    def stop_auto_refresh(self):
        if self._timer:
            self._timer.stop()
            self._timer = None

    def refresh(self):
        """Refresh the tree from the registry."""
        if not self._registry:
            return

        agents = self._registry.list_all()
        if not agents:
            self._tree.clear()
            self._title.setText("🕸 子 Agent (0)")
            return

        # Build parent→children mapping
        children: dict = {}
        roots = []
        for a in agents:
            pid = a.get("parent_id", "")
            if pid:
                children.setdefault(pid, []).append(a)
            else:
                roots.append(a)

        self._tree.clear()
        for root in roots:
            self._add_item(None, root, children)

        active = sum(1 for a in agents if a["status"] in ("spawned", "running"))
        done = sum(1 for a in agents if a["status"] == "completed")
        self._title.setText(f"🕸 子 Agent ({len(agents)})  ⏳{active} ✅{done}")

    def _add_item(self, parent_item, agent, children):
        status = agent.get("status", "running")
        icon = STATUS_ICONS.get(status, "❓")
        role = agent.get("role", "") or ""
        tool_calls = len(agent.get("tool_calls_log", []))
        agent_id = agent.get("agent_id", "")

        item = QTreeWidgetItem(parent_item or self._tree)
        item.setText(0, f"{icon} {agent_id[:8]}")
        item.setText(1, role)
        item.setText(2, status)
        item.setText(3, str(tool_calls) if tool_calls else "")
        item.setData(0, Qt.ItemDataRole.UserRole, agent_id)

        # Color by status
        if status == "completed":
            item.setForeground(0, Qt.GlobalColor.darkGreen)
        elif status in ("failed", "timeout"):
            item.setForeground(0, Qt.GlobalColor.red)
        elif status == "running":
            item.setForeground(0, Qt.GlobalColor.darkBlue)

        # Render children
        for child in children.get(agent_id, []):
            self._add_item(item, child, children)
