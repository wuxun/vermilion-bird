"""用户任务与交付物中心。"""

from __future__ import annotations

import html
import json
import threading
from datetime import datetime
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from llm_chat.frontends.theme import Colors
from llm_chat.runtime import ActionStatus, Capability
from llm_chat.work import (
    ArtifactFeedbackDecision,
    ArtifactReviewPolicy,
    AttentionKind,
    GrantScope,
    GrantStatus,
    PlanStatus,
    ResourceType,
    TaskWorkspaceProjector,
    TaskWorkspaceScope,
    TimelineKind,
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

_RUN_STATUS_LABELS = {
    "pending": "待执行",
    "running": "执行中",
    "cancel_requested": "正在取消",
    "pause_requested": "正在暂停",
    "waiting_approval": "待审批",
    "paused": "已暂停",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}

_RUN_TYPE_LABELS = {
    "chat": "对话",
    "tool": "工具",
    "workflow": "任务执行",
    "scheduled": "定时任务",
    "webhook": "事件任务",
    "proactive": "主动任务",
}

_PLAN_STATUS_LABELS = {
    "draft": "待确认",
    "approved": "已批准",
    "superseded": "已取代",
}

_STEP_STATUS_LABELS = {
    "pending": "待执行",
    "running": "执行中",
    "blocked": "受阻",
    "completed": "已完成",
    "failed": "失败",
    "skipped": "已跳过",
}

_ARTIFACT_KIND_LABELS = {
    "text": "文本",
    "file": "文件",
    "report": "报告",
    "code": "代码",
    "link": "链接",
    "message": "消息",
    "other": "其他",
}

_FEEDBACK_LABELS = {
    "accepted": "已接受",
    "needs_revision": "需修改",
    "rejected": "已拒绝",
}

_REVIEW_POLICY_LABELS = {
    ArtifactReviewPolicy.REQUIRED: "需要验收",
    ArtifactReviewPolicy.OPTIONAL: "只提醒",
    ArtifactReviewPolicy.NONE: "无需反馈",
}


class NewTaskDialog(QDialog):
    """以目标为主，按需展开命名和交付细节。"""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        initial_objective: str = "",
        initial_title: str = "",
        conversation_goal: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle("设为目标" if conversation_goal else "新建目标")
        self.resize(560, 360)
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        title = QLabel("设为目标" if conversation_goal else "新建目标")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(title)
        subtitle = QLabel(
            "保留当前对话上下文，并开始跟踪进展和交付结果。"
            if conversation_goal
            else "描述最终目标，系统会持续保留进展和交付结果。"
        )
        subtitle.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        root.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(10)
        self.objective_input = QTextEdit()
        self.objective_input.setPlaceholderText("描述希望完成的目标、必要约束和验收标准")
        self.objective_input.setMinimumHeight(126)
        self.objective_input.setPlainText(initial_objective)
        form.addRow("目标 *", self.objective_input)

        workspace_row = QHBoxLayout()
        self.workspace_input = QLineEdit()
        self.workspace_input.setPlaceholderText("可选：选择任务工作目录")
        workspace_row.addWidget(self.workspace_input, 1)
        browse = QPushButton("选择…")
        browse.clicked.connect(self._choose_workspace)
        workspace_row.addWidget(browse)
        form.addRow("工作目录", workspace_row)
        root.addLayout(form)

        self._more_options_button = QToolButton()
        self._more_options_button.setText("更多选项  ›")
        self._more_options_button.setCheckable(True)
        self._more_options_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self._more_options_button.toggled.connect(self._toggle_more_options)
        root.addWidget(self._more_options_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self._optional_fields = QFrame()
        optional_form = QFormLayout(self._optional_fields)
        optional_form.setContentsMargins(0, 0, 0, 0)
        optional_form.setSpacing(10)
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("可留空，将根据目标自动生成")
        self.title_input.setText(initial_title)
        optional_form.addRow("标题", self.title_input)
        self.deliverable_input = QLineEdit()
        self.deliverable_input.setPlaceholderText("例如：Markdown 报告、代码变更、数据表")
        optional_form.addRow("预期交付", self.deliverable_input)
        self._optional_fields.hide()
        root.addWidget(self._optional_fields)

        self.start_immediately = QCheckBox("设定后立即开始执行")
        self.start_immediately.setChecked(True)
        self.start_immediately.setToolTip("高风险操作仍会在执行过程中请求审批")
        root.addWidget(self.start_immediately)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "设定并继续" if conversation_goal else "创建并继续"
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _toggle_more_options(self, expanded: bool) -> None:
        self._optional_fields.setVisible(expanded)
        self._more_options_button.setText("更多选项  ⌄" if expanded else "更多选项  ›")
        QTimer.singleShot(0, self.adjustSize)

    def _choose_workspace(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择任务工作目录",
            self.workspace_input.text().strip(),
        )
        if selected:
            self.workspace_input.setText(selected)

    def _accept_if_valid(self) -> None:
        if not self.objective:
            QMessageBox.warning(self, "目标不能为空", "请描述希望完成的任务目标。")
            self.objective_input.setFocus()
            return
        self.accept()

    @property
    def objective(self) -> str:
        return self.objective_input.toPlainText().strip()

    @property
    def title(self) -> str:
        return self.title_input.text().strip()

    @property
    def workspace(self) -> str:
        return self.workspace_input.text().strip()

    @property
    def expected_deliverable(self) -> str:
        return self.deliverable_input.text().strip()


class TaskCenterSignals(QObject):
    changed = pyqtSignal()
    operation_finished = pyqtSignal(str, bool, str)


class TaskCenterDialog(QDialog):
    """跨对话工作概览；Run 细节保留在高级执行中心。"""

    def __init__(
        self,
        app: Any,
        parent: Optional[QWidget] = None,
        *,
        embedded: bool = False,
    ):
        super().__init__(parent)
        self._app = app
        self._embedded = embedded
        self._signals = TaskCenterSignals()
        self._items_by_id: Dict[str, Any] = {}
        self._artifacts_by_id: Dict[str, Any] = {}
        self._artifact_feedback_by_id: Dict[str, Any] = {}
        self._actions_by_id: Dict[str, Any] = {}
        self._grants_by_id: Dict[str, Any] = {}
        self._workspace_views_by_id: Dict[str, Any] = {}
        self._projector = TaskWorkspaceProjector()
        self._current_plan = None
        self._current_detail = None
        self._current_workspace_view = None
        self._primary_action: Optional[str] = None
        self._selected_work_item_id: Optional[str] = None
        self._busy_work_item_id: Optional[str] = None
        self._unsubscribe = None
        self._execution_dialog = None

        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        else:
            self.setWindowTitle("工作概览")
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
        root.setContentsMargins(20, 14, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel("工作概览")
        title.setStyleSheet(f"font-size: 17px; font-weight: 650; color: {Colors.TEXT_PRIMARY};")
        heading.addWidget(title)
        if not self._embedded:
            subtitle = QLabel("跨对话查看目标、执行、审批和最终交付物。")
            subtitle.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
            heading.addWidget(subtitle)
        header.addLayout(heading)
        header.addStretch()

        self._new_button = QPushButton("＋ 新建目标")
        self._new_button.setObjectName("taskPrimaryAction")
        self._new_button.clicked.connect(self._new_task)
        header.addWidget(self._new_button)
        self._header_menu_button = QToolButton()
        self._header_menu_button.setText("⋯")
        self._header_menu_button.setFixedSize(32, 32)
        self._header_menu_button.setToolTip("更多")
        self._header_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._header_menu_button.setStyleSheet(
            "QToolButton { border: none; border-radius: 6px; font-size: 18px; }"
            f"QToolButton:hover {{ background: {Colors.SURFACE_HOVER}; }}"
            "QToolButton::menu-indicator { image: none; }"
        )
        header_menu = QMenu(self._header_menu_button)
        header_menu.addAction("刷新", self.refresh)
        header_menu.addAction("高级执行记录", self._open_execution_center)
        self._header_menu_button.setMenu(header_menu)
        header.addWidget(self._header_menu_button)
        root.addLayout(header)

        self._empty_state = QFrame()
        self._empty_state.setObjectName("taskEmptyState")
        empty_layout = QVBoxLayout(self._empty_state)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(8)
        empty_layout.addStretch()
        empty_icon = QLabel("✓")
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon.setStyleSheet(
            f"font-size: 28px; color: {Colors.PRIMARY}; background: transparent;"
        )
        empty_layout.addWidget(empty_icon)
        self._empty_title = QLabel("还没有持续工作")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_title.setStyleSheet("font-size: 18px; font-weight: 700;")
        empty_layout.addWidget(self._empty_title)
        self._empty_description = QLabel("把一个需要持续推进的目标交给这里。")
        self._empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_description.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        empty_layout.addWidget(self._empty_description)
        self._empty_action = QPushButton("新建第一个目标")
        self._empty_action.setObjectName("taskPrimaryAction")
        self._empty_action.clicked.connect(self._on_empty_action)
        empty_layout.addWidget(self._empty_action, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch()
        root.addWidget(self._empty_state, 1)

        self._filters_bar = QWidget()
        filters = QHBoxLayout(self._filters_bar)
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(8)
        self._task_search_input = QLineEdit()
        self._task_search_input.setPlaceholderText("搜索工作…")
        self._task_search_input.setClearButtonEnabled(True)
        self._task_search_input.textChanged.connect(self.refresh)
        filters.addWidget(self._task_search_input, 1)
        self._scope_filter = QComboBox()
        self._scope_filter.addItem("全部工作", TaskWorkspaceScope.ALL)
        self._scope_filter.addItem("进行中", TaskWorkspaceScope.ACTIVE)
        self._scope_filter.addItem("待你处理", TaskWorkspaceScope.ATTENTION)
        self._scope_filter.addItem("新结果", TaskWorkspaceScope.UPDATES)
        self._scope_filter.addItem("已结束", TaskWorkspaceScope.FINISHED)
        self._scope_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self._scope_filter)
        filters.addStretch()
        root.addWidget(self._filters_bar)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._table = QTableWidget(0, 1)
        self._table.horizontalHeader().hide()
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._splitter.addWidget(self._table)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        self._detail_title = QLabel("选择一项工作")
        self._detail_title.setStyleSheet("font-size: 16px; font-weight: 650;")
        detail_layout.addWidget(self._detail_title)
        self._detail_meta = QLabel("从左侧选择一项，查看当前进展和下一步。")
        self._detail_meta.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        detail_layout.addWidget(self._detail_meta)

        self._tabs = QTabWidget()
        self._timeline = QTextBrowser()
        self._timeline.setOpenExternalLinks(False)
        self._timeline.setPlaceholderText("选择工作后，这里会显示目标、计划、执行进度和交付结果。")
        self._overview = QTextBrowser()
        self._runs_table = QTableWidget(0, 4)
        self._runs_table.setHorizontalHeaderLabels(["开始时间", "类型", "状态", "尝试"])
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
        self._artifacts_table = QTableWidget(0, 4)
        self._artifacts_table.setHorizontalHeaderLabels(["名称", "类型", "反馈", "位置"])
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
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._artifacts_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
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

        progress_panel = QWidget()
        progress_layout = QVBoxLayout(progress_panel)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(10)

        self._attention_panel = QGroupBox("待你处理")
        attention_layout = QVBoxLayout(self._attention_panel)
        self._attention_summary = QLabel()
        self._attention_summary.setWordWrap(True)
        attention_layout.addWidget(self._attention_summary)
        attention_layout.addWidget(self._approvals_table)
        approval_actions = QHBoxLayout()
        self._reject_button = QPushButton("拒绝")
        self._reject_button.clicked.connect(self._reject_selected_action)
        self._approve_button = QPushButton("仅允许此次")
        self._approve_button.clicked.connect(self._approve_selected_action)
        approval_actions.addWidget(self._reject_button)
        approval_actions.addWidget(self._approve_button)
        self._approve_plan_button = QPushButton("批准当前计划")
        self._approve_plan_button.clicked.connect(self._approve_current_plan)
        approval_actions.addWidget(self._approve_plan_button)
        approval_actions.addStretch()
        attention_layout.addLayout(approval_actions)
        progress_layout.addWidget(self._attention_panel)
        progress_layout.addWidget(self._timeline, 1)
        self._tabs.addTab(progress_panel, "进展")

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

        artifacts_panel = QWidget()
        artifacts_layout = QVBoxLayout(artifacts_panel)
        artifacts_layout.setContentsMargins(0, 0, 0, 0)
        artifacts_layout.addWidget(self._artifacts_table, 1)
        artifact_actions = QHBoxLayout()
        self._open_artifact_button = QPushButton("打开")
        self._open_artifact_button.clicked.connect(self._open_selected_artifact)
        self._export_artifact_button = QPushButton("导出")
        self._export_artifact_button.clicked.connect(self._export_selected_artifact)
        self._accept_artifact_button = QPushButton("接受")
        self._accept_artifact_button.clicked.connect(
            lambda: self._feedback_selected_artifact(ArtifactFeedbackDecision.ACCEPTED)
        )
        self._revise_artifact_button = QPushButton("需修改")
        self._revise_artifact_button.clicked.connect(
            lambda: self._feedback_selected_artifact(ArtifactFeedbackDecision.NEEDS_REVISION)
        )
        self._reject_artifact_button = QPushButton("拒绝")
        self._reject_artifact_button.clicked.connect(
            lambda: self._feedback_selected_artifact(ArtifactFeedbackDecision.REJECTED)
        )
        artifact_actions.addWidget(self._open_artifact_button)
        artifact_actions.addWidget(self._export_artifact_button)
        artifact_actions.addStretch()
        artifact_actions.addWidget(self._reject_artifact_button)
        artifact_actions.addWidget(self._revise_artifact_button)
        artifact_actions.addWidget(self._accept_artifact_button)
        artifacts_layout.addLayout(artifact_actions)
        self._tabs.addTab(artifacts_panel, "交付物")

        details_panel = QWidget()
        details_layout = QVBoxLayout(details_panel)
        details_layout.setContentsMargins(0, 0, 0, 0)
        self._detail_tabs = QTabWidget()
        self._detail_tabs.addTab(self._overview, "上下文")
        self._detail_tabs.addTab(plan_panel, "计划")
        self._detail_tabs.addTab(grants_panel, "权限")
        self._detail_tabs.addTab(self._runs_table, "运行记录")
        details_layout.addWidget(self._detail_tabs)
        self._tabs.addTab(details_panel, "详细信息")
        detail_layout.addWidget(self._tabs, 1)

        self._follow_up_panel = QFrame()
        self._follow_up_panel.setObjectName("taskComposer")
        follow_up_layout = QHBoxLayout(self._follow_up_panel)
        follow_up_layout.setContentsMargins(8, 8, 8, 8)
        self._follow_up_input = QTextEdit()
        self._follow_up_input.setPlaceholderText("补充要求、提出修改意见，或让任务基于当前结果继续…")
        self._follow_up_input.setMaximumHeight(72)
        self._follow_up_input.textChanged.connect(self._update_continue_action)
        follow_up_layout.addWidget(self._follow_up_input, 1)
        self._continue_button = QPushButton("继续推进")
        self._continue_button.clicked.connect(self._continue_selected)
        follow_up_layout.addWidget(self._continue_button)
        detail_layout.addWidget(self._follow_up_panel)

        actions = QHBoxLayout()
        self._more_button = QToolButton()
        self._more_button.setText("更多")
        self._more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(self._more_button)
        self._pause_action = more_menu.addAction("暂停", self._pause_selected)
        self._resume_action = more_menu.addAction("恢复", self._resume_selected)
        self._retry_action = more_menu.addAction("重试", self._retry_selected)
        self._cancel_action = more_menu.addAction("取消工作", self._cancel_selected)
        more_menu.addSeparator()
        more_menu.addAction("高级执行记录", self._open_execution_center)
        self._more_button.setMenu(more_menu)
        actions.addWidget(self._more_button)
        actions.addStretch()
        self._primary_button = QPushButton("选择一项工作")
        self._primary_button.clicked.connect(self._run_primary_action)
        self._primary_button.setStyleSheet(
            f"""
            QPushButton {{
                background: {Colors.ACTION_BG};
                color: {Colors.ACTION_TEXT};
                border: none;
                border-radius: 8px;
                padding: 8px 18px;
                font-weight: 700;
            }}
            QPushButton:hover {{ background: {Colors.ACTION_HOVER}; }}
            QPushButton:disabled {{
                background: {Colors.SURFACE_SELECTED};
                color: {Colors.TEXT_MUTED};
            }}
            """
        )
        actions.addWidget(self._primary_button)
        detail_layout.addLayout(actions)
        self._splitter.addWidget(detail_panel)
        self._splitter.setSizes([290, 910])
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        root.addWidget(self._splitter, 1)

        self.setStyleSheet(
            f"""
            QDialog, QWidget {{
                background-color: {Colors.CHAT_BG};
                color: {Colors.TEXT_PRIMARY};
            }}
            QTableWidget, QTextBrowser {{
                border: 1px solid {Colors.CHAT_BORDER};
                border-radius: 7px;
                background: {Colors.CHAT_BG};
                alternate-background-color: {Colors.CHAT_BG_ALT};
            }}
            QTableWidget::item {{ padding: 6px; }}
            QTableWidget::item:selected {{
                background: {Colors.SURFACE_SELECTED};
                color: {Colors.PRIMARY_DARK};
            }}
            QFrame#taskComposer {{
                border: 1px solid {Colors.CHAT_BORDER};
                border-radius: 14px;
                background: {Colors.SURFACE_RAISED};
            }}
            QFrame#taskEmptyState {{
                border: none;
                background: transparent;
            }}
            QHeaderView::section {{
                background: {Colors.SURFACE};
                border: none;
                border-bottom: 1px solid {Colors.CHAT_BORDER};
                padding: 7px;
                font-weight: 600;
            }}
            QComboBox, QPushButton {{
                border: 1px solid {Colors.CHAT_BORDER};
                border-radius: 8px;
                padding: 6px 10px;
                background: {Colors.SURFACE_RAISED};
                color: {Colors.TEXT_PRIMARY};
            }}
            QPushButton:hover {{ background: {Colors.SURFACE_HOVER}; }}
            QPushButton#taskPrimaryAction {{
                background: {Colors.ACTION_BG};
                color: {Colors.ACTION_TEXT};
                border: none;
                font-weight: 650;
            }}
            QPushButton#taskPrimaryAction:hover {{ background: {Colors.ACTION_HOVER}; }}
            """
        )
        self._update_actions(None)

    def _connect_service(self) -> None:
        service = getattr(self._app, "work_items", None)
        if service is not None and hasattr(service, "subscribe"):
            self._unsubscribe = service.subscribe(lambda _item: self._signals.changed.emit())

    def _on_empty_action(self) -> None:
        if (
            self._scope_filter.currentData() != TaskWorkspaceScope.ALL
            or self._task_search_input.text().strip()
        ):
            self._scope_filter.setCurrentIndex(0)
            self._task_search_input.clear()
            return
        self._new_task()

    def _update_content_state(self, has_items: bool) -> None:
        filtered = bool(
            self._scope_filter.currentData() != TaskWorkspaceScope.ALL
            or self._task_search_input.text().strip()
        )
        self._empty_state.setVisible(not has_items)
        self._filters_bar.setVisible(has_items or filtered)
        self._splitter.setVisible(has_items)
        self._new_button.setVisible(has_items or filtered)
        if has_items:
            return
        if filtered:
            self._empty_title.setText("没有匹配的工作")
            self._empty_description.setText("调整筛选条件后再试。")
            self._empty_action.setText("清除筛选")
        else:
            self._empty_title.setText("还没有持续工作")
            self._empty_description.setText("把一个需要持续推进的目标交给这里。")
            self._empty_action.setText("新建第一个目标")

    def refresh(self) -> None:
        scope = self._scope_filter.currentData() or TaskWorkspaceScope.ALL
        query = self._task_search_input.text().strip()
        try:
            items = self._app.list_work_items(limit=500)
            if hasattr(self._app, "list_task_workspace_views"):
                views = self._app.list_task_workspace_views(
                    scope=scope,
                    query=query,
                    limit=500,
                )
            else:
                views = self._fallback_workspace_views(items, scope=scope, query=query)
        except Exception as exc:
            QMessageBox.warning(self, "刷新失败", str(exc))
            return
        self._items_by_id = {item.id: item for item in items}
        self._workspace_views_by_id = {view.work_item_id: view for view in views}
        self._update_content_state(bool(views))
        selected_row = next(
            (
                row
                for row, view in enumerate(views)
                if view.work_item_id == self._selected_work_item_id
            ),
            0 if views else None,
        )
        self._table.blockSignals(True)
        try:
            self._table.setRowCount(len(views))
            for row, view in enumerate(views):
                badges = []
                if view.action_required_count:
                    badges.append(f"{view.action_required_count} 待处理")
                if view.notice_count:
                    badges.append(f"{view.notice_count} 新结果")
                attention = f" · {' · '.join(badges)}" if badges else ""
                list_item = QTableWidgetItem(
                    f"{view.title}\n"
                    f"{view.status_label} · {self._format_time(view.updated_at)}{attention}"
                )
                list_item.setData(Qt.ItemDataRole.UserRole, view.work_item_id)
                self._table.setItem(row, 0, list_item)
                self._table.setRowHeight(row, 58)
            if selected_row is not None:
                self._table.selectRow(selected_row)
            else:
                self._table.clearSelection()
        finally:
            self._table.blockSignals(False)

        if selected_row is None:
            self._selected_work_item_id = None
            self._clear_detail()
            return

        selected_work_item_id = views[selected_row].work_item_id
        self._selected_work_item_id = selected_work_item_id
        self._load_detail(selected_work_item_id)

    def focus_work_item(self, work_item_id: str) -> None:
        """从对话中的目标状态跳转到对应工作详情。"""

        self._selected_work_item_id = work_item_id
        self._scope_filter.blockSignals(True)
        self._task_search_input.blockSignals(True)
        try:
            self._scope_filter.setCurrentIndex(0)
            self._task_search_input.clear()
        finally:
            self._scope_filter.blockSignals(False)
            self._task_search_input.blockSignals(False)
        self.refresh()

    def start_work_item(self, work_item_id: str) -> None:
        """从统一对话入口启动目标，同时复用任务中心的线程与反馈机制。"""

        self.focus_work_item(work_item_id)
        self._run_background(
            work_item_id,
            lambda: self._app.execute_work_item(work_item_id),
        )

    def _fallback_workspace_views(self, items, *, scope, query: str):
        normalized_query = query.casefold()
        views = []
        for item in items:
            if normalized_query and normalized_query not in (
                f"{item.title}\n{item.objective}".casefold()
            ):
                continue
            detail = self._app.get_work_item_detail(item.id)
            proposals = (
                self._app.list_work_item_actions(item.id)
                if hasattr(self._app, "list_work_item_actions")
                else []
            )
            view = self._projector.project(detail, proposals)
            if scope == TaskWorkspaceScope.ATTENTION and not view.requires_attention:
                continue
            if scope == TaskWorkspaceScope.UPDATES and not view.has_updates:
                continue
            if scope == TaskWorkspaceScope.ACTIVE and view.status.terminal:
                continue
            if scope == TaskWorkspaceScope.FINISHED and not view.status.terminal:
                continue
            views.append(view)
        return views

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
        self._current_detail = detail
        workspace_view = self._workspace_views_by_id.get(work_item_id)
        if workspace_view is None:
            workspace_view = self._projector.project(detail, proposals)
            self._workspace_views_by_id[work_item_id] = workspace_view
        self._current_workspace_view = workspace_view
        self._detail_title.setText(item.title)
        badges = []
        if workspace_view.action_required_count:
            badges.append(f"{workspace_view.action_required_count} 项待处理")
        if workspace_view.notice_count:
            badges.append(f"{workspace_view.notice_count} 个新结果")
        attention_text = f" · {' · '.join(badges)}" if badges else ""
        self._detail_meta.setText(
            f"{workspace_view.status_label} · {workspace_view.kind_label}"
            f" · 更新于 {self._format_time(workspace_view.updated_at)}{attention_text}"
        )
        lines = [
            f"状态：{_STATUS_LABELS[item.status]}",
            f"类型：{_KIND_LABELS[item.kind]}",
            f"结果处理：{_REVIEW_POLICY_LABELS[item.artifact_review_policy]}",
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
            self._runs_table.setItem(
                row,
                0,
                QTableWidgetItem(self._format_time(run.created_at)),
            )
            self._runs_table.setItem(
                row,
                1,
                QTableWidgetItem(_RUN_TYPE_LABELS.get(run.type.value, run.type.value)),
            )
            self._runs_table.setItem(
                row,
                2,
                QTableWidgetItem(_RUN_STATUS_LABELS.get(run.status.value, run.status.value)),
            )
            self._runs_table.setItem(row, 3, QTableWidgetItem(str(run.attempt)))

        self._actions_by_id = {proposal.id: proposal for proposal in proposals}
        pending_proposals = [
            proposal for proposal in proposals if proposal.status == ActionStatus.PENDING
        ]
        self._approvals_table.setRowCount(len(pending_proposals))
        for row, proposal in enumerate(pending_proposals):
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
        pending_count = len(pending_proposals)
        if pending_proposals:
            self._approvals_table.selectRow(0)
        else:
            self._update_approval_actions()

        self._artifacts_by_id = {artifact.id: artifact for artifact in detail.artifacts}
        self._artifact_feedback_by_id = {}
        for feedback in detail.artifact_feedback:
            self._artifact_feedback_by_id.setdefault(feedback.artifact_id, feedback)
        self._artifacts_table.setRowCount(len(detail.artifacts))
        for row, artifact in enumerate(detail.artifacts):
            name_item = QTableWidgetItem(artifact.name)
            name_item.setData(Qt.ItemDataRole.UserRole, artifact.id)
            self._artifacts_table.setItem(row, 0, name_item)
            self._artifacts_table.setItem(
                row,
                1,
                QTableWidgetItem(
                    _ARTIFACT_KIND_LABELS.get(artifact.kind.value, artifact.kind.value)
                ),
            )
            feedback = self._artifact_feedback_by_id.get(artifact.id)
            feedback_label = (
                _FEEDBACK_LABELS.get(feedback.decision.value, feedback.decision.value)
                if feedback
                else self._unreviewed_artifact_label(item, artifact)
            )
            self._artifacts_table.setItem(
                row,
                2,
                QTableWidgetItem(feedback_label),
            )
            location = artifact.uri or ("内嵌内容" if artifact.content else "")
            self._artifacts_table.setItem(row, 3, QTableWidgetItem(location))
        self._tabs.setTabText(1, f"交付物 ({len(detail.artifacts)})")
        self._load_plan(detail.plan)
        self._load_grants(detail.grants)
        self._update_attention(workspace_view, pending_count)
        self._render_timeline(workspace_view)
        self._update_actions(item)

    def _load_plan(self, plan) -> None:
        self._current_plan = plan
        if plan is None:
            self._plan_summary.setText("暂无结构化计划。")
            self._plan_table.setRowCount(0)
            self._detail_tabs.setTabText(1, "计划")
            self._approve_plan_button.setEnabled(False)
            return
        change = f"\n变更：{plan.change_summary}" if plan.change_summary else ""
        self._plan_summary.setText(
            f"v{plan.version} · "
            f"{_PLAN_STATUS_LABELS.get(plan.status.value, plan.status.value)} · "
            f"{plan.summary}{change}"
        )
        self._plan_table.setRowCount(len(plan.steps))
        for row, step in enumerate(plan.steps):
            self._plan_table.setItem(row, 0, QTableWidgetItem(str(step.position)))
            self._plan_table.setItem(row, 1, QTableWidgetItem(step.title))
            self._plan_table.setItem(
                row,
                2,
                QTableWidgetItem(_STEP_STATUS_LABELS.get(step.status.value, step.status.value)),
            )
            expected = (
                _ARTIFACT_KIND_LABELS.get(
                    step.expected_artifact_kind.value,
                    step.expected_artifact_kind.value,
                )
                if step.expected_artifact_kind
                else ""
            )
            self._plan_table.setItem(row, 3, QTableWidgetItem(expected))
        self._detail_tabs.setTabText(1, f"计划 (v{plan.version})")
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
        self._detail_tabs.setTabText(2, f"权限 ({active_count})")
        if grants:
            self._grants_table.selectRow(0)
        else:
            self._update_grant_actions()

    def _update_attention(self, workspace_view, pending_count: int) -> None:
        draft_plan = any(
            item.kind == AttentionKind.PLAN for item in workspace_view.attention
        )
        self._attention_summary.setText(
            "\n".join(
                f"• {item.title} — {item.summary}"
                for item in workspace_view.attention
            )
        )
        self._approvals_table.setVisible(bool(pending_count))
        self._approve_button.setVisible(bool(pending_count))
        self._reject_button.setVisible(bool(pending_count))
        self._approve_plan_button.setVisible(draft_plan)
        self._attention_panel.setTitle(
            "待你处理" if workspace_view.requires_attention else "新结果"
        )
        self._attention_panel.setVisible(bool(workspace_view.attention))
        if workspace_view.requires_attention:
            tab_text = f"进展 · {workspace_view.action_required_count} 待处理"
        elif workspace_view.has_updates:
            tab_text = f"进展 · {workspace_view.notice_count} 新结果"
        else:
            tab_text = "进展"
        self._tabs.setTabText(0, tab_text)

    @staticmethod
    def _unreviewed_artifact_label(item, artifact) -> str:
        raw_policy = str(artifact.metadata.get("review_policy") or "").strip()
        try:
            policy = (
                ArtifactReviewPolicy(raw_policy)
                if raw_policy
                else item.artifact_review_policy
            )
        except ValueError:
            policy = item.artifact_review_policy
        return {
            ArtifactReviewPolicy.REQUIRED: "待验收",
            ArtifactReviewPolicy.OPTIONAL: "可选反馈",
            ArtifactReviewPolicy.NONE: "无需反馈",
        }[policy]

    def _render_timeline(self, workspace_view) -> None:
        def esc(value: Any) -> str:
            return html.escape(str(value or ""))

        def card(title: str, body: str, accent: str = Colors.CHAT_ACCENT) -> str:
            return (
                f'<div style="margin:0 0 12px 0;padding:13px 15px;'
                f'border:1px solid {accent};border-radius:9px;'
                f'background:{Colors.SURFACE_RAISED};">'
                f'<div style="font-size:14px;font-weight:700;margin-bottom:7px;">'
                f"{esc(title)}</div>{body}</div>"
            )

        accents = {
            TimelineKind.OBJECTIVE: Colors.PRIMARY,
            TimelineKind.APPROVAL: Colors.WARNING,
            TimelineKind.ARTIFACT: Colors.SUCCESS,
        }
        cards = []
        for entry in workspace_view.timeline:
            details = "".join(
                f'<div style="margin:5px 0;color:{Colors.TEXT_SECONDARY};">'
                f"{esc(line)}</div>"
                for line in entry.details
            )
            summary = (
                f'<div style="line-height:1.55;'
                f'color:{Colors.TEXT_PRIMARY};">{esc(entry.summary)}</div>'
            )
            cards.append(
                card(
                    entry.title,
                    summary + details,
                    accents.get(entry.kind, Colors.CHAT_ACCENT),
                )
            )

        self._timeline.setHtml(
            f"""
            <html><body style="font-family:'Helvetica Neue', 'Segoe UI', Arial, sans-serif;
            color:{Colors.TEXT_PRIMARY}; background:{Colors.CHAT_BG_ALT};">
            {''.join(cards)}
            </body></html>
            """
        )

    def _new_task(self) -> None:
        dialog = NewTaskDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        metadata = {"source": "gui"}
        if dialog.expected_deliverable:
            metadata["expected_deliverable"] = dialog.expected_deliverable
        try:
            if hasattr(self._app, "create_conversation_goal"):
                item = self._app.create_conversation_goal(
                    dialog.objective,
                    title=dialog.title or None,
                    workspace=dialog.workspace or None,
                    expected_deliverable=dialog.expected_deliverable or None,
                )
            else:
                item = self._app.create_work_item(
                    dialog.objective,
                    title=dialog.title or None,
                    kind=WorkItemKind.TASK,
                    workspace=dialog.workspace or None,
                    metadata=metadata,
                )
        except Exception as exc:
            QMessageBox.critical(self, "创建失败", str(exc))
            return
        self._selected_work_item_id = item.id
        self.refresh()
        if dialog.start_immediately.isChecked():
            self._run_background(
                item.id,
                lambda: self._app.execute_work_item(item.id),
            )

    def _start_selected(self) -> None:
        work_item_id = self._selected_work_item_id
        if not work_item_id:
            return
        self._run_background(
            work_item_id,
            lambda: self._app.execute_work_item(work_item_id),
        )

    def _continue_selected(self) -> None:
        work_item_id = self._selected_work_item_id
        instruction = self._follow_up_input.toPlainText().strip()
        if not work_item_id or not instruction:
            return
        self._follow_up_input.clear()
        self._run_background(
            work_item_id,
            lambda: self._app.continue_work_item(work_item_id, instruction),
        )

    def _update_continue_action(self) -> None:
        item = self._items_by_id.get(self._selected_work_item_id)
        can_continue = bool(
            item
            and item.status.terminal
            and self._busy_work_item_id is None
            and hasattr(self._app, "continue_work_item")
        )
        self._continue_button.setEnabled(
            can_continue and bool(self._follow_up_input.toPlainText().strip())
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
            QMessageBox.information(self, "工作执行中", "已有工作正在进行。")
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
        artifact = self._selected_artifact()
        if artifact is None:
            return
        self._open_artifact_by_value(artifact)

    def _selected_artifact(self):
        selected = self._artifacts_table.selectedItems()
        if not selected and self._artifacts_table.rowCount():
            self._artifacts_table.selectRow(0)
            selected = self._artifacts_table.selectedItems()
        if not selected:
            return None
        artifact_id = self._artifacts_table.item(selected[0].row(), 0).data(
            Qt.ItemDataRole.UserRole
        )
        return self._artifacts_by_id.get(artifact_id)

    def _open_artifact(self, item: QTableWidgetItem) -> None:
        row = item.row()
        artifact_id = self._artifacts_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        artifact = self._artifacts_by_id.get(artifact_id)
        if artifact is None:
            return
        self._open_artifact_by_value(artifact)

    def _open_artifact_by_value(self, artifact) -> None:
        record_view = getattr(self._app, "record_artifact_viewed", None)
        if callable(record_view):
            record_view(artifact.id, entrypoint="gui")
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

    def _export_selected_artifact(self) -> None:
        artifact = self._selected_artifact()
        if artifact is None:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "导出交付物",
            artifact.name,
        )
        if not destination:
            return
        try:
            exported = self._app.export_artifact(
                artifact.id,
                destination,
                overwrite=True,
            )
            QMessageBox.information(self, "导出完成", exported)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _feedback_selected_artifact(
        self,
        decision: ArtifactFeedbackDecision,
    ) -> None:
        artifact = self._selected_artifact()
        work_item_id = self._selected_work_item_id
        if artifact is None or work_item_id is None:
            return
        note = ""
        if decision in {
            ArtifactFeedbackDecision.NEEDS_REVISION,
            ArtifactFeedbackDecision.REJECTED,
        }:
            title = "交付物需要修改" if decision == ArtifactFeedbackDecision.NEEDS_REVISION else "拒绝交付物"
            prompt = (
                "请说明需要修改的内容：" if decision == ArtifactFeedbackDecision.NEEDS_REVISION else "请说明拒绝原因："
            )
            note, ok = QInputDialog.getMultiLineText(
                self,
                title,
                prompt,
            )
            if not ok:
                return
            note = note.strip()
        try:
            self._app.submit_artifact_feedback(
                work_item_id,
                artifact.id,
                decision=decision,
                note=note,
            )
            self._load_detail(work_item_id)
        except Exception as exc:
            QMessageBox.critical(self, "反馈失败", str(exc))

    def _open_execution_center(self) -> None:
        if self._execution_dialog is not None and self._execution_dialog.isVisible():
            self._execution_dialog.raise_()
            self._execution_dialog.activateWindow()
            return
        from llm_chat.frontends.execution_center import ExecutionCenterDialog

        self._execution_dialog = ExecutionCenterDialog(self._app, self)
        self._execution_dialog.show()

    def _run_primary_action(self) -> None:
        action = self._primary_action
        if action == "start":
            self._start_selected()
        elif action == "retry":
            self._retry_selected()
        elif action == "resume":
            self._resume_selected()
        elif action == "approval":
            self._tabs.setCurrentIndex(0)
            if self._approvals_table.rowCount():
                self._approvals_table.selectRow(0)
                self._approvals_table.setFocus()
        elif action == "plan":
            self._tabs.setCurrentIndex(0)
            self._approve_plan_button.setFocus()
        elif action == "artifacts":
            self._tabs.setCurrentIndex(1)
            if self._artifacts_table.rowCount():
                self._artifacts_table.selectRow(0)
                self._artifacts_table.setFocus()

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

        self._retry_action.setEnabled(can_retry)
        self._resume_action.setEnabled(can_resume)
        self._pause_action.setEnabled(can_pause)
        self._cancel_action.setEnabled(
            bool(item and not item.status.terminal and not busy and not control_pending)
        )
        self._more_button.setEnabled(bool(item))

        has_artifacts = bool(self._artifacts_by_id)
        can_continue = bool(
            item and item.status.terminal and not busy and hasattr(self._app, "continue_work_item")
        )
        self._follow_up_panel.setVisible(can_continue)
        self._follow_up_input.setEnabled(can_continue)
        self._continue_button.setEnabled(
            can_continue and bool(self._follow_up_input.toPlainText().strip())
        )
        if can_continue:
            self._follow_up_input.setPlaceholderText("补充要求、提出修改意见，或让任务基于当前结果继续…")
        else:
            self._follow_up_input.setPlaceholderText("任务结束后可在这里继续提出要求")
        self._open_artifact_button.setEnabled(has_artifacts)
        self._export_artifact_button.setEnabled(has_artifacts and not busy)
        self._accept_artifact_button.setEnabled(has_artifacts and not busy)
        self._revise_artifact_button.setEnabled(has_artifacts and not busy)
        self._reject_artifact_button.setEnabled(has_artifacts and not busy)
        self._add_grant_button.setEnabled(bool(item and not busy))
        self._approve_plan_button.setEnabled(
            bool(self._current_plan and self._current_plan.status == PlanStatus.DRAFT and not busy)
        )

        self._primary_action = None
        primary_text = "选择一项工作"
        primary_enabled = False
        if item is not None:
            pending_approval = any(
                proposal.status == ActionStatus.PENDING for proposal in self._actions_by_id.values()
            )
            draft_plan = bool(
                self._current_plan is not None and self._current_plan.status == PlanStatus.DRAFT
            )
            if busy:
                primary_text = "正在处理…"
            elif pending_approval:
                primary_text = "处理审批"
                self._primary_action = "approval"
                primary_enabled = True
            elif draft_plan:
                primary_text = "确认执行计划"
                self._primary_action = "plan"
                primary_enabled = True
            elif item.status in {WorkItemStatus.DRAFT, WorkItemStatus.READY}:
                primary_text = "开始执行"
                self._primary_action = "start"
                primary_enabled = True
            elif can_resume:
                primary_text = "继续执行"
                self._primary_action = "resume"
                primary_enabled = True
            elif can_retry:
                primary_text = "重试"
                self._primary_action = "retry"
                primary_enabled = True
            elif item.status == WorkItemStatus.COMPLETED and has_artifacts:
                primary_text = "查看交付物"
                self._primary_action = "artifacts"
                primary_enabled = True
            elif item.status == WorkItemStatus.COMPLETED:
                primary_text = "已完成"
            elif item.status == WorkItemStatus.RUNNING:
                primary_text = "执行中"
            elif item.status == WorkItemStatus.PAUSING:
                primary_text = "正在暂停…"
            elif item.status == WorkItemStatus.CANCELLING:
                primary_text = "正在取消…"
            else:
                primary_text = _STATUS_LABELS[item.status]
        self._primary_button.setText(primary_text)
        self._primary_button.setEnabled(primary_enabled)
        self._update_grant_actions()
        self._update_approval_actions()

    def _clear_detail(self) -> None:
        self._detail_title.setText("选择一项工作")
        self._detail_meta.setText("从左侧选择一项，查看当前进展和下一步。")
        self._timeline.clear()
        self._follow_up_input.clear()
        self._overview.clear()
        self._runs_table.setRowCount(0)
        self._approvals_table.setRowCount(0)
        self._artifacts_table.setRowCount(0)
        self._plan_table.setRowCount(0)
        self._grants_table.setRowCount(0)
        self._plan_summary.setText("暂无计划")
        self._actions_by_id = {}
        self._artifacts_by_id = {}
        self._artifact_feedback_by_id = {}
        self._grants_by_id = {}
        self._current_plan = None
        self._current_detail = None
        self._current_workspace_view = None
        self._attention_panel.hide()
        self._tabs.setTabText(0, "进展")
        self._tabs.setTabText(1, "交付物")
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
