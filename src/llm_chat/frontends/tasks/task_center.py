"""用户任务与交付物中心。"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from llm_chat.frontends.theme import Colors
from llm_chat.runtime import ActionStatus, Capability
from llm_chat.work import (
    GrantScope,
    GrantStatus,
    PlanStatus,
    ResourceType,
    WorkItemKind,
    WorkItemStatus,
)


_STATUS_LABELS: Dict[WorkItemStatus, str] = {
    WorkItemStatus.DRAFT: "草稿",
    WorkItemStatus.READY: "待执行",
    WorkItemStatus.RUNNING: "执行中",
    WorkItemStatus.CANCELLING: "正在取消",
    WorkItemStatus.PAUSING: "正在暂停",
    WorkItemStatus.WAITING_APPROVAL: "待审批",
    WorkItemStatus.PAUSED: "已暂停",
    WorkItemStatus.COMPLETED: "已完成",
    WorkItemStatus.FAILED: "失败",
    WorkItemStatus.CANCELLED: "已取消",
}

_KIND_LABELS: Dict[WorkItemKind, str] = {
    WorkItemKind.CHAT: "对话",
    WorkItemKind.TASK: "任务",
    WorkItemKind.AUTOMATION: "自动化",
}


class TaskCenterSignals(QObject):
    changed = pyqtSignal()
    operation_finished = pyqtSignal(str, bool, str)


class TaskCenterDialog(QDialog):
    """面向用户的任务聚合视图；Run 细节保留在高级执行中心。"""

    def __init__(self, app: Any, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._app = app
        self._signals = TaskCenterSignals()
        self._items_by_id: Dict[str, Any] = {}
        self._artifacts_by_id: Dict[str, Any] = {}
        self._actions_by_id: Dict[str, Any] = {}
        self._grants_by_id: Dict[str, Any] = {}
        self._current_plan = None
        self._selected_work_item_id: Optional[str] = None
        self._busy_work_item_id: Optional[str] = None
        self._unsubscribe = None
        self._execution_dialog = None

        self.setWindowTitle("任务中心")
        self.resize(1120, 740)
        self.setMinimumSize(900, 580)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._build_ui()
        self._connect_service()
        self._signals.changed.connect(self.refresh)
        self._signals.operation_finished.connect(self._on_operation_finished)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(3000)
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel("任务中心")
        title.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {Colors.TEXT_PRIMARY};")
        subtitle = QLabel("围绕目标查看执行、审批和最终交付物。")
        subtitle.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header.addLayout(heading)
        header.addStretch()

        self._new_button = QPushButton("＋ 新建任务")
        self._new_button.clicked.connect(self._new_task)
        header.addWidget(self._new_button)
        self._advanced_button = QPushButton("高级执行记录")
        self._advanced_button.clicked.connect(self._open_execution_center)
        header.addWidget(self._advanced_button)
        root.addLayout(header)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("状态"))
        self._status_filter = QComboBox()
        self._status_filter.addItem("全部", None)
        for status, label in _STATUS_LABELS.items():
            self._status_filter.addItem(label, status)
        self._status_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self._status_filter)
        filters.addWidget(QLabel("类型"))
        self._kind_filter = QComboBox()
        self._kind_filter.addItem("全部", None)
        for kind, label in _KIND_LABELS.items():
            self._kind_filter.addItem(label, kind)
        self._kind_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self._kind_filter)
        filters.addStretch()
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self.refresh)
        filters.addWidget(refresh_button)
        root.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["状态", "任务", "类型", "更新时间"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self._table)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        self._detail_title = QLabel("选择一个任务")
        self._detail_title.setStyleSheet("font-size: 17px; font-weight: 700;")
        detail_layout.addWidget(self._detail_title)

        self._tabs = QTabWidget()
        self._overview = QTextBrowser()
        self._runs_table = QTableWidget(0, 4)
        self._runs_table.setHorizontalHeaderLabels(["执行", "类型", "状态", "尝试"])
        self._runs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._runs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._runs_table.verticalHeader().setVisible(False)
        self._runs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._runs_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._runs_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._runs_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self._artifacts_table = QTableWidget(0, 3)
        self._artifacts_table.setHorizontalHeaderLabels(["名称", "类型", "位置"])
        self._artifacts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._artifacts_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._artifacts_table.verticalHeader().setVisible(False)
        self._artifacts_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._artifacts_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._artifacts_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._artifacts_table.itemDoubleClicked.connect(self._open_artifact)
        self._approvals_table = QTableWidget(0, 5)
        self._approvals_table.setHorizontalHeaderLabels(["状态", "工具", "风险", "影响", "创建时间"])
        self._approvals_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._approvals_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._approvals_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._approvals_table.verticalHeader().setVisible(False)
        self._approvals_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._approvals_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._approvals_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._approvals_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self._approvals_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        self._approvals_table.itemSelectionChanged.connect(self._update_approval_actions)
        self._approvals_table.itemDoubleClicked.connect(self._show_action_detail)
        self._tabs.addTab(self._overview, "概览")
        self._tabs.addTab(self._runs_table, "执行")
        approvals_panel = QWidget()
        approvals_layout = QVBoxLayout(approvals_panel)
        approvals_layout.setContentsMargins(0, 0, 0, 0)
        approvals_layout.addWidget(self._approvals_table, 1)
        approval_actions = QHBoxLayout()
        self._approve_button = QPushButton("批准并执行")
        self._approve_button.clicked.connect(self._approve_selected_action)
        self._reject_button = QPushButton("拒绝")
        self._reject_button.clicked.connect(self._reject_selected_action)
        approval_actions.addWidget(self._approve_button)
        approval_actions.addWidget(self._reject_button)
        approval_actions.addStretch()
        approvals_layout.addLayout(approval_actions)
        self._tabs.addTab(approvals_panel, "审批")
        self._tabs.addTab(self._artifacts_table, "产物")

        plan_panel = QWidget()
        plan_layout = QVBoxLayout(plan_panel)
        plan_layout.setContentsMargins(0, 0, 0, 0)
        self._plan_summary = QLabel("暂无计划")
        self._plan_summary.setWordWrap(True)
        plan_layout.addWidget(self._plan_summary)
        self._plan_table = QTableWidget(0, 4)
        self._plan_table.setHorizontalHeaderLabels(["序号", "步骤", "状态", "预期产物"])
        self._plan_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._plan_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._plan_table.verticalHeader().setVisible(False)
        self._plan_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._plan_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._plan_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._plan_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        plan_layout.addWidget(self._plan_table, 1)
        plan_actions = QHBoxLayout()
        self._approve_plan_button = QPushButton("批准当前计划")
        self._approve_plan_button.clicked.connect(self._approve_current_plan)
        plan_actions.addWidget(self._approve_plan_button)
        plan_actions.addStretch()
        plan_layout.addLayout(plan_actions)
        self._tabs.addTab(plan_panel, "计划")

        grants_panel = QWidget()
        grants_layout = QVBoxLayout(grants_panel)
        grants_layout.setContentsMargins(0, 0, 0, 0)
        self._grants_table = QTableWidget(0, 4)
        self._grants_table.setHorizontalHeaderLabels(["状态", "能力", "资源类型", "资源"])
        self._grants_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._grants_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._grants_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._grants_table.verticalHeader().setVisible(False)
        self._grants_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._grants_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._grants_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._grants_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self._grants_table.itemSelectionChanged.connect(self._update_grant_actions)
        grants_layout.addWidget(self._grants_table, 1)
        grant_actions = QHBoxLayout()
        self._add_grant_button = QPushButton("添加授权")
        self._add_grant_button.clicked.connect(self._add_resource_grant)
        self._revoke_grant_button = QPushButton("撤销授权")
        self._revoke_grant_button.clicked.connect(self._revoke_selected_grant)
        grant_actions.addWidget(self._add_grant_button)
        grant_actions.addWidget(self._revoke_grant_button)
        grant_actions.addStretch()
        grants_layout.addLayout(grant_actions)
        self._tabs.addTab(grants_panel, "授权")
        detail_layout.addWidget(self._tabs, 1)

        actions = QHBoxLayout()
        self._cancel_button = QPushButton("取消任务")
        self._cancel_button.clicked.connect(self._cancel_selected)
        self._pause_button = QPushButton("暂停")
        self._pause_button.clicked.connect(self._pause_selected)
        self._retry_button = QPushButton("重试")
        self._retry_button.clicked.connect(self._retry_selected)
        self._resume_button = QPushButton("恢复")
        self._resume_button.clicked.connect(self._resume_selected)
        self._open_artifact_button = QPushButton("打开产物")
        self._open_artifact_button.clicked.connect(self._open_selected_artifact)
        actions.addWidget(self._cancel_button)
        actions.addWidget(self._pause_button)
        actions.addWidget(self._retry_button)
        actions.addWidget(self._resume_button)
        actions.addStretch()
        actions.addWidget(self._open_artifact_button)
        detail_layout.addLayout(actions)
        splitter.addWidget(detail_panel)
        splitter.setSizes([470, 630])
        root.addWidget(splitter, 1)

        self.setStyleSheet(
            f"""
            QDialog, QWidget {{
                background-color: {Colors.CHAT_BG};
                color: {Colors.TEXT_PRIMARY};
            }}
            QTableWidget, QTextBrowser {{
                border: 1px solid {Colors.CHAT_BORDER};
                border-radius: 7px;
                background: white;
                alternate-background-color: {Colors.CHAT_BG_ALT};
            }}
            QTableWidget::item {{ padding: 6px; }}
            QTableWidget::item:selected {{
                background: {Colors.CHAT_ACCENT};
                color: {Colors.TEXT_PRIMARY};
            }}
            QHeaderView::section {{
                background: {Colors.PARAMS_BG};
                border: none;
                border-right: 1px solid {Colors.CHAT_BORDER};
                padding: 7px;
                font-weight: 600;
            }}
            QComboBox, QPushButton {{
                border: 1px solid {Colors.CHAT_ACCENT};
                border-radius: 6px;
                padding: 6px 10px;
                background: white;
            }}
            QPushButton:hover {{ background: {Colors.PARAMS_BG}; }}
            """
        )
        self._update_actions(None)

    def _connect_service(self) -> None:
        service = getattr(self._app, "work_items", None)
        if service is not None and hasattr(service, "subscribe"):
            self._unsubscribe = service.subscribe(lambda _item: self._signals.changed.emit())

    def refresh(self) -> None:
        status = self._status_filter.currentData()
        kind = self._kind_filter.currentData()
        try:
            items = self._app.list_work_items(status=status, kind=kind, limit=500)
        except Exception as exc:
            QMessageBox.warning(self, "刷新失败", str(exc))
            return
        self._items_by_id = {item.id: item for item in items}
        self._table.setRowCount(len(items))
        selected_row = None
        for row, item in enumerate(items):
            status_item = QTableWidgetItem(_STATUS_LABELS[item.status])
            status_item.setData(Qt.ItemDataRole.UserRole, item.id)
            self._table.setItem(row, 0, status_item)
            self._table.setItem(row, 1, QTableWidgetItem(item.title))
            self._table.setItem(row, 2, QTableWidgetItem(_KIND_LABELS[item.kind]))
            self._table.setItem(row, 3, QTableWidgetItem(self._format_time(item.updated_at)))
            if item.id == self._selected_work_item_id:
                selected_row = row
        if selected_row is not None:
            self._table.selectRow(selected_row)
        elif items:
            self._table.selectRow(0)
        else:
            self._selected_work_item_id = None
            self._clear_detail()

    def _on_selection_changed(self) -> None:
        selected = self._table.selectedItems()
        if not selected:
            return
        work_item_id = self._table.item(selected[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        self._selected_work_item_id = work_item_id
        self._load_detail(work_item_id)

    def _load_detail(self, work_item_id: str) -> None:
        try:
            detail = self._app.get_work_item_detail(work_item_id)
            proposals = self._app.list_work_item_actions(work_item_id)
        except Exception as exc:
            self._overview.setPlainText(str(exc))
            return
        item = detail.work_item
        self._detail_title.setText(item.title)
        lines = [
            f"状态：{_STATUS_LABELS[item.status]}",
            f"类型：{_KIND_LABELS[item.kind]}",
            f"目标：{item.objective}",
            f"任务 ID：{item.id}",
            f"创建时间：{self._format_time(item.created_at)}",
            f"更新时间：{self._format_time(item.updated_at)}",
        ]
        if item.workspace:
            lines.append(f"工作目录：{item.workspace}")
        if item.conversation_id:
            lines.append(f"关联会话：{item.conversation_id}")
        lines.extend(
            [
                "",
                f"执行次数：{len(detail.runs)}",
                f"产物数量：{len(detail.artifacts)}",
            ]
        )
        latest = next(
            (run for run in detail.runs if run.id == item.latest_run_id),
            None,
        )
        if latest and latest.error:
            lines.extend(["", f"最近错误：{latest.error}"])
        self._overview.setPlainText("\n".join(lines))

        self._runs_table.setRowCount(len(detail.runs))
        for row, run in enumerate(detail.runs):
            self._runs_table.setItem(row, 0, QTableWidgetItem(run.id))
            self._runs_table.setItem(row, 1, QTableWidgetItem(run.type.value))
            self._runs_table.setItem(row, 2, QTableWidgetItem(run.status.value))
            self._runs_table.setItem(row, 3, QTableWidgetItem(str(run.attempt)))

        self._actions_by_id = {proposal.id: proposal for proposal in proposals}
        self._approvals_table.setRowCount(len(proposals))
        pending_count = 0
        for row, proposal in enumerate(proposals):
            status_item = QTableWidgetItem(proposal.status.value)
            status_item.setData(Qt.ItemDataRole.UserRole, proposal.id)
            self._approvals_table.setItem(row, 0, status_item)
            self._approvals_table.setItem(row, 1, QTableWidgetItem(proposal.tool_name))
            self._approvals_table.setItem(row, 2, QTableWidgetItem(proposal.risk))
            self._approvals_table.setItem(row, 3, QTableWidgetItem(proposal.impact))
            self._approvals_table.setItem(
                row,
                4,
                QTableWidgetItem(self._format_time(proposal.created_at)),
            )
            if proposal.status == ActionStatus.PENDING:
                pending_count += 1
        approval_label = f"审批 ({pending_count} 待处理)" if pending_count else "审批"
        self._tabs.setTabText(2, approval_label)
        if proposals:
            self._approvals_table.selectRow(0)
        else:
            self._update_approval_actions()

        self._artifacts_by_id = {artifact.id: artifact for artifact in detail.artifacts}
        self._artifacts_table.setRowCount(len(detail.artifacts))
        for row, artifact in enumerate(detail.artifacts):
            name_item = QTableWidgetItem(artifact.name)
            name_item.setData(Qt.ItemDataRole.UserRole, artifact.id)
            self._artifacts_table.setItem(row, 0, name_item)
            self._artifacts_table.setItem(row, 1, QTableWidgetItem(artifact.kind.value))
            location = artifact.uri or ("内嵌内容" if artifact.content else "")
            self._artifacts_table.setItem(row, 2, QTableWidgetItem(location))
        self._tabs.setTabText(3, f"产物 ({len(detail.artifacts)})")
        self._load_plan(detail.plan)
        self._load_grants(detail.grants)
        self._update_actions(item)

    def _load_plan(self, plan) -> None:
        self._current_plan = plan
        if plan is None:
            self._plan_summary.setText("暂无结构化计划。可通过 CLI 创建计划修订。")
            self._plan_table.setRowCount(0)
            self._tabs.setTabText(4, "计划")
            self._approve_plan_button.setEnabled(False)
            return
        change = f"\n变更：{plan.change_summary}" if plan.change_summary else ""
        self._plan_summary.setText(
            f"v{plan.version} · {plan.status.value} · {plan.summary}{change}"
        )
        self._plan_table.setRowCount(len(plan.steps))
        for row, step in enumerate(plan.steps):
            self._plan_table.setItem(row, 0, QTableWidgetItem(str(step.position)))
            self._plan_table.setItem(row, 1, QTableWidgetItem(step.title))
            self._plan_table.setItem(row, 2, QTableWidgetItem(step.status.value))
            expected = step.expected_artifact_kind.value if step.expected_artifact_kind else ""
            self._plan_table.setItem(row, 3, QTableWidgetItem(expected))
        self._tabs.setTabText(4, f"计划 (v{plan.version})")
        self._approve_plan_button.setEnabled(
            plan.status == PlanStatus.DRAFT and self._busy_work_item_id is None
        )

    def _load_grants(self, grants) -> None:
        self._grants_by_id = {grant.id: grant for grant in grants}
        self._grants_table.setRowCount(len(grants))
        active_count = 0
        for row, grant in enumerate(grants):
            status_item = QTableWidgetItem(grant.status.value)
            status_item.setData(Qt.ItemDataRole.UserRole, grant.id)
            self._grants_table.setItem(row, 0, status_item)
            self._grants_table.setItem(row, 1, QTableWidgetItem(grant.capability))
            self._grants_table.setItem(
                row,
                2,
                QTableWidgetItem(grant.resource_type.value),
            )
            self._grants_table.setItem(row, 3, QTableWidgetItem(grant.resource))
            if grant.status == GrantStatus.ACTIVE:
                active_count += 1
        self._tabs.setTabText(5, f"授权 ({active_count})")
        if grants:
            self._grants_table.selectRow(0)
        else:
            self._update_grant_actions()

    def _new_task(self) -> None:
        objective, ok = QInputDialog.getMultiLineText(
            self,
            "新建任务",
            "描述希望完成的目标：",
        )
        objective = objective.strip()
        if not ok or not objective:
            return
        title, ok = QInputDialog.getText(
            self,
            "任务标题",
            "标题（可留空自动生成）：",
        )
        if not ok:
            return
        try:
            item = self._app.create_work_item(
                objective,
                title=title.strip() or None,
                kind=WorkItemKind.TASK,
                metadata={"source": "gui"},
            )
        except Exception as exc:
            QMessageBox.critical(self, "创建失败", str(exc))
            return
        self._selected_work_item_id = item.id
        self.refresh()
        self._run_background(
            item.id,
            lambda: self._app.execute_work_item(item.id),
        )

    def _cancel_selected(self) -> None:
        if not self._selected_work_item_id:
            return
        if QMessageBox.question(self, "取消任务", "确定取消当前任务吗？") != (QMessageBox.StandardButton.Yes):
            return
        try:
            self._app.cancel_work_item(self._selected_work_item_id)
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, "取消失败", str(exc))

    def _retry_selected(self) -> None:
        if not self._selected_work_item_id:
            return
        work_item_id = self._selected_work_item_id
        self._run_background(
            work_item_id,
            lambda: self._app.retry_work_item(work_item_id),
        )

    def _pause_selected(self) -> None:
        if not self._selected_work_item_id:
            return
        work_item_id = self._selected_work_item_id
        try:
            self._app.pause_work_item(work_item_id)
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, "暂停失败", str(exc))

    def _resume_selected(self) -> None:
        if not self._selected_work_item_id:
            return
        work_item_id = self._selected_work_item_id
        self._run_background(
            work_item_id,
            lambda: self._app.resume_work_item(work_item_id),
        )

    def _selected_action(self):
        selected = self._approvals_table.selectedItems()
        if not selected:
            return None
        proposal_id = self._approvals_table.item(selected[0].row(), 0).data(
            Qt.ItemDataRole.UserRole
        )
        return self._actions_by_id.get(proposal_id)

    def _show_action_detail(self, _item: QTableWidgetItem) -> None:
        proposal = self._selected_action()
        if proposal is None:
            return
        QMessageBox.information(
            self,
            f"审批动作 · {proposal.tool_name}",
            self._action_detail_text(proposal),
        )

    def _approve_selected_action(self) -> None:
        proposal = self._selected_action()
        if proposal is None or proposal.status != ActionStatus.PENDING:
            return
        if (
            QMessageBox.warning(
                self,
                f"批准 {proposal.tool_name}",
                self._action_detail_text(proposal) + "\n\n批准后将立即执行该动作，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        work_item_id = self._selected_work_item_id
        if not work_item_id:
            return
        self._run_background(
            work_item_id,
            lambda: self._app.approve_action(
                proposal.id,
                conversation_id=proposal.conversation_id,
            ),
        )

    def _reject_selected_action(self) -> None:
        proposal = self._selected_action()
        if proposal is None or proposal.status != ActionStatus.PENDING:
            return
        if (
            QMessageBox.question(
                self,
                f"拒绝 {proposal.tool_name}",
                "确定拒绝该动作吗？任务将从审批点继续，并记录拒绝决定。",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        work_item_id = self._selected_work_item_id
        if not work_item_id:
            return
        self._run_background(
            work_item_id,
            lambda: self._app.reject_action(
                proposal.id,
                conversation_id=proposal.conversation_id,
            ),
        )

    def _update_approval_actions(self) -> None:
        proposal = self._selected_action()
        enabled = bool(
            proposal and proposal.status == ActionStatus.PENDING and self._busy_work_item_id is None
        )
        self._approve_button.setEnabled(enabled)
        self._reject_button.setEnabled(enabled)

    def _approve_current_plan(self) -> None:
        plan = self._current_plan
        work_item_id = self._selected_work_item_id
        if plan is None or work_item_id is None or plan.status != PlanStatus.DRAFT:
            return
        if (
            QMessageBox.question(
                self,
                "批准计划",
                f"批准计划 v{plan.version} 并将其作为当前执行基线吗？",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self._app.approve_work_item_plan(work_item_id, plan.id)
            self._load_detail(work_item_id)
        except Exception as exc:
            QMessageBox.critical(self, "批准计划失败", str(exc))

    def _selected_grant(self):
        selected = self._grants_table.selectedItems()
        if not selected:
            return None
        grant_id = self._grants_table.item(selected[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        return self._grants_by_id.get(grant_id)

    def _add_resource_grant(self) -> None:
        work_item_id = self._selected_work_item_id
        if not work_item_id:
            return
        capability, ok = QInputDialog.getItem(
            self,
            "添加资源授权",
            "能力：",
            [
                Capability.WORKSPACE_WRITE.value,
                Capability.NETWORK.value,
                Capability.EXTERNAL_MESSAGE.value,
                Capability.READ.value,
            ],
            editable=False,
        )
        if not ok:
            return
        expected_types = {
            Capability.WORKSPACE_WRITE.value: ResourceType.DIRECTORY,
            Capability.READ.value: ResourceType.DIRECTORY,
            Capability.NETWORK.value: ResourceType.DOMAIN,
            Capability.EXTERNAL_MESSAGE.value: ResourceType.MESSAGE_TARGET,
        }
        resource_type = expected_types[capability]
        item = self._items_by_id.get(work_item_id)
        default_value = (
            item.workspace
            if item and item.workspace and resource_type == ResourceType.DIRECTORY
            else ""
        )
        resource, ok = QInputDialog.getText(
            self,
            "添加资源授权",
            f"{resource_type.value}：",
            text=default_value,
        )
        resource = resource.strip()
        if not ok or not resource:
            return
        scope_value, ok = QInputDialog.getItem(
            self,
            "添加资源授权",
            "有效范围：",
            [GrantScope.ONCE.value, GrantScope.WORK_ITEM.value],
            editable=False,
        )
        if not ok:
            return
        if (
            QMessageBox.warning(
                self,
                "确认授权",
                f"允许任务使用 {capability}\n"
                f"资源边界：{resource}\n"
                f"范围：{scope_value}\n\n"
                "匹配边界内的动作将不再逐次弹出审批，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self._app.create_resource_grant(
                work_item_id=work_item_id,
                capability=capability,
                resource_type=resource_type,
                resource=resource,
                scope=GrantScope(scope_value),
                reason="GUI 任务中心授权",
            )
            self._load_detail(work_item_id)
        except Exception as exc:
            QMessageBox.critical(self, "创建授权失败", str(exc))

    def _revoke_selected_grant(self) -> None:
        grant = self._selected_grant()
        if grant is None or grant.status != GrantStatus.ACTIVE:
            return
        if (
            QMessageBox.question(
                self,
                "撤销授权",
                f"立即撤销 {grant.capability} 对 {grant.resource} 的授权吗？",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self._app.revoke_resource_grant(grant.id)
            if self._selected_work_item_id:
                self._load_detail(self._selected_work_item_id)
        except Exception as exc:
            QMessageBox.critical(self, "撤销授权失败", str(exc))

    def _update_grant_actions(self) -> None:
        grant = self._selected_grant()
        self._revoke_grant_button.setEnabled(
            bool(grant and grant.status == GrantStatus.ACTIVE and self._busy_work_item_id is None)
        )

    @staticmethod
    def _action_detail_text(proposal) -> str:
        capabilities = ", ".join(sorted(item.value for item in proposal.capabilities))
        arguments = json.dumps(
            proposal.arguments,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        return "\n".join(
            [
                f"工具：{proposal.tool_name}",
                f"风险：{proposal.risk}",
                f"能力：{capabilities or '未声明'}",
                f"原因：{proposal.reason}",
                f"影响：{proposal.impact}",
                f"可撤销：{'是' if proposal.reversible else '否'}",
                "",
                "参数：",
                arguments,
            ]
        )

    def _run_background(self, work_item_id: str, operation) -> None:
        if self._busy_work_item_id is not None:
            QMessageBox.information(self, "任务执行中", "已有任务操作正在进行。")
            return
        self._busy_work_item_id = work_item_id
        self._update_actions(self._items_by_id.get(work_item_id))

        def worker():
            try:
                operation()
            except Exception as exc:
                self._signals.operation_finished.emit(work_item_id, False, str(exc))
            else:
                self._signals.operation_finished.emit(work_item_id, True, "")

        threading.Thread(target=worker, name=f"work-item-{work_item_id}", daemon=True).start()

    def _on_operation_finished(self, work_item_id: str, succeeded: bool, message: str) -> None:
        self._busy_work_item_id = None
        self._selected_work_item_id = work_item_id
        self.refresh()
        if not succeeded:
            QMessageBox.critical(self, "任务操作失败", message)

    def _open_selected_artifact(self) -> None:
        selected = self._artifacts_table.selectedItems()
        if not selected and self._artifacts_table.rowCount():
            self._artifacts_table.selectRow(0)
            selected = self._artifacts_table.selectedItems()
        if selected:
            self._open_artifact(selected[0])

    def _open_artifact(self, item: QTableWidgetItem) -> None:
        row = item.row()
        artifact_id = self._artifacts_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        artifact = self._artifacts_by_id.get(artifact_id)
        if artifact is None:
            return
        if artifact.uri:
            url = (
                QUrl(artifact.uri)
                if artifact.uri.startswith(("http://", "https://"))
                else QUrl.fromLocalFile(artifact.uri)
            )
            QDesktopServices.openUrl(url)
            return
        QMessageBox.information(
            self,
            artifact.name,
            artifact.content or artifact.content_preview or "该产物没有可显示内容。",
        )

    def _open_execution_center(self) -> None:
        if self._execution_dialog is not None and self._execution_dialog.isVisible():
            self._execution_dialog.raise_()
            self._execution_dialog.activateWindow()
            return
        from llm_chat.frontends.execution_center import ExecutionCenterDialog

        self._execution_dialog = ExecutionCenterDialog(self._app, self)
        self._execution_dialog.show()

    def _update_actions(self, item: Optional[Any]) -> None:
        busy = self._busy_work_item_id is not None
        self._new_button.setEnabled(not busy)
        control_pending = bool(
            item
            and item.status
            in {
                WorkItemStatus.CANCELLING,
                WorkItemStatus.PAUSING,
            }
        )
        self._cancel_button.setEnabled(
            bool(item and not item.status.terminal and not busy and not control_pending)
        )
        can_retry = False
        can_resume = False
        can_pause = False
        if item and not busy:
            try:
                can_retry = self._app.can_retry_work_item(item.id)
                can_resume = self._app.can_resume_work_item(item.id)
                can_pause = self._app.can_pause_work_item(item.id)
            except Exception:
                can_retry = False
                can_resume = False
                can_pause = False
        self._retry_button.setEnabled(can_retry)
        self._resume_button.setEnabled(can_resume)
        self._pause_button.setEnabled(can_pause)
        self._open_artifact_button.setEnabled(bool(self._artifacts_by_id))
        self._add_grant_button.setEnabled(bool(item and not busy))
        self._approve_plan_button.setEnabled(
            bool(self._current_plan and self._current_plan.status == PlanStatus.DRAFT and not busy)
        )
        self._update_grant_actions()
        self._update_approval_actions()

    def _clear_detail(self) -> None:
        self._detail_title.setText("选择一个任务")
        self._overview.clear()
        self._runs_table.setRowCount(0)
        self._approvals_table.setRowCount(0)
        self._artifacts_table.setRowCount(0)
        self._plan_table.setRowCount(0)
        self._grants_table.setRowCount(0)
        self._plan_summary.setText("暂无计划")
        self._actions_by_id = {}
        self._artifacts_by_id = {}
        self._grants_by_id = {}
        self._current_plan = None
        self._update_actions(None)

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.astimezone().strftime("%Y-%m-%d %H:%M")

    def closeEvent(self, event) -> None:
        self._timer.stop()
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._execution_dialog is not None:
            self._execution_dialog.close()
        super().closeEvent(event)
