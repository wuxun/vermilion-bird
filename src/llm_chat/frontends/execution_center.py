"""GUI 执行与审批中心。"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from llm_chat.frontends.theme import Colors
from llm_chat.runtime import (
    ActionStatus,
    EffectResolution,
    EffectStatus,
    RunStatus,
    RunType,
)


_RUN_STATUS_LABELS: Dict[RunStatus, str] = {
    RunStatus.PENDING: "等待",
    RunStatus.RUNNING: "执行中",
    RunStatus.CANCEL_REQUESTED: "正在取消",
    RunStatus.PAUSE_REQUESTED: "正在暂停",
    RunStatus.WAITING_APPROVAL: "待审批",
    RunStatus.PAUSED: "已暂停",
    RunStatus.COMPLETED: "已完成",
    RunStatus.FAILED: "失败",
    RunStatus.CANCELLED: "已取消",
}

_ACTION_STATUS_LABELS: Dict[ActionStatus, str] = {
    ActionStatus.PENDING: "待审批",
    ActionStatus.APPROVED: "已批准",
    ActionStatus.REJECTED: "已拒绝",
    ActionStatus.EXECUTING: "执行中",
    ActionStatus.COMPLETED: "已完成",
    ActionStatus.FAILED: "失败",
}

_EFFECT_STATUS_LABELS: Dict[EffectStatus, str] = {
    EffectStatus.PENDING: "等待执行",
    EffectStatus.EXECUTING: "执行中",
    EffectStatus.COMPLETED: "已完成",
    EffectStatus.FAILED: "失败",
    EffectStatus.UNCERTAIN: "待对账",
}


class ExecutionCenterSignals(QObject):
    """将任意后台线程的运行状态变化送回 GUI 线程。"""

    run_changed = pyqtSignal()
    action_changed = pyqtSignal()
    operation_finished = pyqtSignal(bool, str)


class ExecutionCenterDialog(QDialog):
    """查看运行历史，并处理持久化动作审批。"""

    def __init__(self, app: Any, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._app = app
        self._signals = ExecutionCenterSignals()
        self._run_by_id: Dict[str, Any] = {}
        self._proposal_by_id: Dict[str, Any] = {}
        self._effect_by_key: Dict[str, Any] = {}
        self._unsubscribe_run = None
        self._unsubscribe_action = None
        self._busy_action_id: Optional[str] = None
        self._busy_run_id: Optional[str] = None
        self._busy_effect_key: Optional[str] = None

        self.setWindowTitle("执行与审批中心")
        self.resize(1080, 720)
        self.setMinimumSize(860, 560)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._build_ui()
        self._connect_runtime()

        self._signals.run_changed.connect(self.refresh_runs)
        self._signals.action_changed.connect(self.refresh_actions)
        self._signals.operation_finished.connect(self._on_operation_finished)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_all)
        self._refresh_timer.start(3000)
        self.refresh_all()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("执行与审批中心")
        title.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {Colors.TEXT_PRIMARY};")
        subtitle = QLabel("跨会话查看聊天、工具和工作流运行；高风险动作仅在批准后执行。")
        subtitle.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        root.addWidget(title)
        root.addWidget(subtitle)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_runs_tab(), "运行记录")
        self._tabs.addTab(self._build_approvals_tab(), "审批")
        self._tabs.addTab(self._build_effects_tab(), "副作用对账")
        root.addWidget(self._tabs, 1)

        self.setStyleSheet(
            f"""
            QDialog, QWidget {{
                background-color: {Colors.CHAT_BG};
                color: {Colors.TEXT_PRIMARY};
            }}
            QTabWidget::pane {{
                border: 1px solid {Colors.CHAT_BORDER};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                padding: 9px 18px;
                color: {Colors.TEXT_SECONDARY};
            }}
            QTabBar::tab:selected {{
                color: {Colors.TEXT_PRIMARY};
                font-weight: 700;
            }}
            QTableWidget {{
                border: 1px solid {Colors.CHAT_BORDER};
                border-radius: 6px;
                gridline-color: {Colors.CHAT_BORDER};
                background: {Colors.CHAT_BG};
                alternate-background-color: {Colors.CHAT_BG_ALT};
            }}
            QTableWidget::item {{ padding: 6px; }}
            QTableWidget::item:selected {{
                background: {Colors.CHAT_ACCENT};
                color: {Colors.TEXT_PRIMARY};
            }}
            QHeaderView::section {{
                background: {Colors.SURFACE};
                color: {Colors.TEXT_SECONDARY};
                border: none;
                border-bottom: 1px solid {Colors.CHAT_BORDER};
                padding: 7px;
                font-weight: 600;
            }}
            QComboBox {{
                border: 1px solid {Colors.CHAT_BORDER};
                border-radius: 8px;
                padding: 5px 9px;
                background: {Colors.SURFACE_RAISED};
            }}
            QTextBrowser {{
                border: 1px solid {Colors.CHAT_BORDER};
                border-radius: 6px;
                padding: 8px;
                background: {Colors.CHAT_BG};
            }}
            """
        )

    def _build_runs_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)

        toolbar = QHBoxLayout()
        self._run_summary_label = QLabel()
        toolbar.addWidget(self._run_summary_label)
        toolbar.addStretch()
        toolbar.addWidget(QLabel("状态"))
        self._run_status_filter = QComboBox()
        self._run_status_filter.addItem("全部", None)
        for status, label in _RUN_STATUS_LABELS.items():
            self._run_status_filter.addItem(label, status)
        self._run_status_filter.currentIndexChanged.connect(self.refresh_runs)
        toolbar.addWidget(self._run_status_filter)
        toolbar.addWidget(QLabel("类型"))
        self._run_type_filter = QComboBox()
        self._run_type_filter.addItem("全部", None)
        for run_type in RunType:
            self._run_type_filter.addItem(run_type.value, run_type)
        self._run_type_filter.currentIndexChanged.connect(self.refresh_runs)
        toolbar.addWidget(self._run_type_filter)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_runs)
        toolbar.addWidget(refresh)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self._runs_table = QTableWidget(0, 6)
        self._runs_table.setHorizontalHeaderLabels(["开始时间", "类型", "状态", "摘要", "耗时", "Run ID"])
        self._configure_table(self._runs_table)
        self._runs_table.itemSelectionChanged.connect(self._show_selected_run)
        self._runs_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._runs_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents
        )
        splitter.addWidget(self._runs_table)

        detail_container = QFrame()
        detail_layout = QVBoxLayout(detail_container)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self._run_detail = QTextBrowser()
        self._run_detail.setPlaceholderText("选择一条运行记录查看输入、输出和事件时间线。")
        detail_layout.addWidget(self._run_detail, 1)
        run_buttons = QHBoxLayout()
        run_buttons.addStretch()
        self._retry_run_button = QPushButton("重试")
        self._retry_run_button.clicked.connect(self._retry_selected_run)
        run_buttons.addWidget(self._retry_run_button)
        self._replay_run_button = QPushButton("重放")
        self._replay_run_button.clicked.connect(self._replay_selected_run)
        run_buttons.addWidget(self._replay_run_button)
        self._resume_run_button = QPushButton("恢复执行")
        self._resume_run_button.clicked.connect(self._resume_selected_run)
        self._resume_run_button.setStyleSheet(
            f"""
            QPushButton {{
                background: {Colors.ACTION_BG};
                color: {Colors.ACTION_TEXT};
                border: none;
                border-radius: 6px;
                padding: 7px 16px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {Colors.ACTION_HOVER}; }}
            QPushButton:disabled {{ background: {Colors.SURFACE_SELECTED}; color:{Colors.TEXT_MUTED}; }}
            """
        )
        run_buttons.addWidget(self._resume_run_button)
        detail_layout.addLayout(run_buttons)
        splitter.addWidget(detail_container)
        splitter.setSizes([390, 230])
        layout.addWidget(splitter, 1)
        return tab

    def _build_approvals_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)

        toolbar = QHBoxLayout()
        self._approval_summary_label = QLabel()
        toolbar.addWidget(self._approval_summary_label)
        toolbar.addStretch()
        toolbar.addWidget(QLabel("状态"))
        self._action_status_filter = QComboBox()
        self._action_status_filter.addItem("待审批", ActionStatus.PENDING)
        self._action_status_filter.addItem("全部", None)
        for status, label in _ACTION_STATUS_LABELS.items():
            if status != ActionStatus.PENDING:
                self._action_status_filter.addItem(label, status)
        self._action_status_filter.currentIndexChanged.connect(self.refresh_actions)
        toolbar.addWidget(self._action_status_filter)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_actions)
        toolbar.addWidget(refresh)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self._actions_table = QTableWidget(0, 6)
        self._actions_table.setHorizontalHeaderLabels(["创建时间", "工具", "风险", "能力", "状态", "Action ID"])
        self._configure_table(self._actions_table)
        self._actions_table.itemSelectionChanged.connect(self._show_selected_action)
        self._actions_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self._actions_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents
        )
        splitter.addWidget(self._actions_table)

        detail_container = QFrame()
        detail_layout = QVBoxLayout(detail_container)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self._action_detail = QTextBrowser()
        self._action_detail.setPlaceholderText("选择一条审批查看原因、影响和完整参数。")
        detail_layout.addWidget(self._action_detail, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self._reject_button = QPushButton("拒绝")
        self._reject_button.clicked.connect(self._reject_selected)
        self._reject_button.setEnabled(False)
        buttons.addWidget(self._reject_button)
        self._approve_button = QPushButton("批准并执行")
        self._approve_button.clicked.connect(self._approve_selected)
        self._approve_button.setEnabled(False)
        self._approve_button.setStyleSheet(
            f"""
            QPushButton {{
                background: {Colors.ACTION_BG};
                color: {Colors.ACTION_TEXT};
                border: none;
                border-radius: 6px;
                padding: 7px 16px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {Colors.ACTION_HOVER}; }}
            QPushButton:disabled {{ background: {Colors.SURFACE_SELECTED}; color:{Colors.TEXT_MUTED}; }}
            """
        )
        buttons.addWidget(self._approve_button)
        detail_layout.addLayout(buttons)
        splitter.addWidget(detail_container)
        splitter.setSizes([360, 260])
        layout.addWidget(splitter, 1)
        return tab

    def _build_effects_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)

        toolbar = QHBoxLayout()
        self._effect_summary_label = QLabel()
        toolbar.addWidget(self._effect_summary_label)
        toolbar.addStretch()
        toolbar.addWidget(QLabel("状态"))
        self._effect_status_filter = QComboBox()
        self._effect_status_filter.addItem("待对账", EffectStatus.UNCERTAIN)
        self._effect_status_filter.addItem("全部", None)
        for status, label in _EFFECT_STATUS_LABELS.items():
            if status != EffectStatus.UNCERTAIN:
                self._effect_status_filter.addItem(label, status)
        self._effect_status_filter.currentIndexChanged.connect(self.refresh_effects)
        toolbar.addWidget(self._effect_status_filter)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_effects)
        toolbar.addWidget(refresh)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self._effects_table = QTableWidget(0, 6)
        self._effects_table.setHorizontalHeaderLabels(
            ["更新时间", "类型", "状态", "重试安全", "尝试", "Effect Key"]
        )
        self._configure_table(self._effects_table)
        self._effects_table.itemSelectionChanged.connect(self._show_selected_effect)
        self._effects_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        splitter.addWidget(self._effects_table)

        detail_container = QFrame()
        detail_layout = QVBoxLayout(detail_container)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self._effect_detail = QTextBrowser()
        self._effect_detail.setPlaceholderText("选择待对账记录，核对外部系统、文件或命令实际结果后再做结论。")
        detail_layout.addWidget(self._effect_detail, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self._effect_failed_button = QPushButton("确认未生效")
        self._effect_failed_button.clicked.connect(self._resolve_effect_not_applied)
        buttons.addWidget(self._effect_failed_button)
        self._effect_retry_button = QPushButton("允许安全重试")
        self._effect_retry_button.clicked.connect(self._resolve_effect_retry)
        buttons.addWidget(self._effect_retry_button)
        self._effect_success_button = QPushButton("确认已成功")
        self._effect_success_button.clicked.connect(self._resolve_effect_succeeded)
        self._effect_success_button.setStyleSheet(
            f"""
            QPushButton {{
                background: {Colors.ACTION_BG};
                color: {Colors.ACTION_TEXT};
                border: none;
                border-radius: 6px;
                padding: 7px 16px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {Colors.ACTION_HOVER}; }}
            QPushButton:disabled {{ background: {Colors.SURFACE_SELECTED}; color:{Colors.TEXT_MUTED}; }}
            """
        )
        buttons.addWidget(self._effect_success_button)
        detail_layout.addLayout(buttons)
        splitter.addWidget(detail_container)
        splitter.setSizes([360, 260])
        layout.addWidget(splitter, 1)
        return tab

    @staticmethod
    def _configure_table(table: QTableWidget) -> None:
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(False)

    def _connect_runtime(self) -> None:
        self._unsubscribe_run = self._app.run_manager.subscribe(
            lambda _run, _event: self._safe_emit(self._signals.run_changed)
        )
        self._unsubscribe_action = self._app.action_proposals.subscribe(
            lambda _proposal: self._safe_emit(self._signals.action_changed)
        )

    @staticmethod
    def _safe_emit(signal: Any, *args: Any) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    def refresh_all(self) -> None:
        self.refresh_runs()
        self.refresh_actions()
        self.refresh_effects()

    def refresh_runs(self) -> None:
        selected_id = self._selected_id(self._runs_table)
        status = self._run_status_filter.currentData()
        run_type = self._run_type_filter.currentData()
        runs = self._app.run_manager.list(
            limit=500,
            status=status,
            run_type=run_type,
        )
        self._run_by_id = {run.id: run for run in runs}
        self._runs_table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            values = [
                self._format_time(run.started_at or run.created_at),
                run.type.value,
                _RUN_STATUS_LABELS.get(run.status, run.status.value),
                self._run_summary(run),
                self._duration(run),
                run.id,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, run.id)
                if run.status == RunStatus.FAILED:
                    item.setForeground(QColor(Colors.DANGER))
                elif run.status == RunStatus.RUNNING:
                    item.setForeground(QColor(Colors.INFO))
                self._runs_table.setItem(row, column, item)
        self._restore_selection(self._runs_table, selected_id)
        self._run_summary_label.setText(f"显示 {len(runs)} 条运行")
        if not runs:
            self._run_detail.clear()
            self._set_run_buttons(None)

    def refresh_actions(self) -> None:
        selected_id = self._selected_id(self._actions_table)
        status = self._action_status_filter.currentData()
        proposals = self._app.action_proposals.list(limit=500, status=status)
        pending = self._app.action_proposals.list(
            limit=500,
            status=ActionStatus.PENDING,
        )
        self._proposal_by_id = {proposal.id: proposal for proposal in proposals}
        self._actions_table.setRowCount(len(proposals))
        for row, proposal in enumerate(proposals):
            capabilities = ", ".join(sorted(item.value for item in proposal.capabilities))
            values = [
                self._format_time(proposal.created_at),
                proposal.tool_name,
                proposal.risk,
                capabilities,
                _ACTION_STATUS_LABELS.get(
                    proposal.status,
                    proposal.status.value,
                ),
                proposal.id,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, proposal.id)
                if proposal.risk == "high":
                    item.setForeground(QColor(Colors.DANGER))
                elif proposal.status == ActionStatus.COMPLETED:
                    item.setForeground(QColor(Colors.SUCCESS))
                self._actions_table.setItem(row, column, item)
        self._restore_selection(self._actions_table, selected_id)
        self._approval_summary_label.setText(f"待审批 {len(pending)} 项 · 当前显示 {len(proposals)} 项")
        self._tabs.setTabText(1, f"审批 ({len(pending)})" if pending else "审批")
        if not proposals:
            self._action_detail.clear()
            self._set_action_buttons(False)

    def refresh_effects(self) -> None:
        selected_key = self._selected_id(self._effects_table)
        status = self._effect_status_filter.currentData()
        effects = (
            self._app.list_effects(status=status, limit=500)
            if hasattr(self._app, "list_effects")
            else []
        )
        uncertain = (
            self._app.list_effects(status=EffectStatus.UNCERTAIN, limit=500)
            if hasattr(self._app, "list_effects")
            else []
        )
        self._effect_by_key = {effect.effect_key: effect for effect in effects}
        self._effects_table.setRowCount(len(effects))
        for row, effect in enumerate(effects):
            values = [
                self._format_time(effect.updated_at),
                effect.kind,
                _EFFECT_STATUS_LABELS.get(effect.status, effect.status.value),
                "是" if effect.retry_safe else "否",
                str(effect.attempts),
                effect.effect_key,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, effect.effect_key)
                if effect.status == EffectStatus.UNCERTAIN:
                    item.setForeground(QColor(Colors.DANGER))
                elif effect.status == EffectStatus.COMPLETED:
                    item.setForeground(QColor(Colors.SUCCESS))
                self._effects_table.setItem(row, column, item)
        self._restore_selection(self._effects_table, selected_key)
        self._effect_summary_label.setText(f"待对账 {len(uncertain)} 项 · 当前显示 {len(effects)} 项")
        self._tabs.setTabText(
            2,
            f"副作用对账 ({len(uncertain)})" if uncertain else "副作用对账",
        )
        if not effects:
            self._effect_detail.clear()
            self._set_effect_buttons(None)

    def _show_selected_run(self) -> None:
        run = self._run_by_id.get(self._selected_id(self._runs_table) or "")
        if run is None:
            self._run_detail.clear()
            self._set_run_buttons(None)
            return
        self._run_detail.setPlainText(self._format_run_detail(run))
        self._set_run_buttons(run)

    def _resume_selected_run(self) -> None:
        run = self._selected_run()
        if run is None or not run.can_resume:
            return
        is_tool_approval = run.metadata.get("approval_kind") == "tool"
        title = "批准并恢复" if is_tool_approval else "恢复执行"
        message = "恢复后将执行已提议的工具副作用，是否批准？" if is_tool_approval else "是否从最近的持久化检查点继续执行？"
        answer = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_run_operation("resume_run", run.id, "恢复")

    def _retry_selected_run(self) -> None:
        run = self._selected_run()
        if run is None or not run.can_retry:
            return
        self._start_run_operation("retry_run", run.id, "重试")

    def _replay_selected_run(self) -> None:
        run = self._selected_run()
        if run is None:
            return
        answer = QMessageBox.question(
            self,
            "确认重放",
            "重放会以相同输入创建新的 Run，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_run_operation("replay_run", run.id, "重放")

    def _start_run_operation(
        self,
        method_name: str,
        run_id: str,
        label: str,
    ) -> None:
        self._busy_run_id = run_id
        self._set_run_buttons(self._run_by_id.get(run_id))
        threading.Thread(
            target=self._execute_run_operation,
            args=(method_name, run_id, label),
            daemon=True,
            name=f"{method_name}-{run_id[-8:]}",
        ).start()

    def _execute_run_operation(
        self,
        method_name: str,
        run_id: str,
        label: str,
    ) -> None:
        try:
            method = getattr(self._app, method_name)
            result = method(run_id)
        except Exception as exc:
            self._safe_emit(
                self._signals.operation_finished,
                False,
                f"{label}失败：{exc}",
            )
            return
        self._safe_emit(
            self._signals.operation_finished,
            True,
            f"Run {result.id} {label}操作已完成。",
        )

    def _show_selected_action(self) -> None:
        proposal = self._selected_proposal()
        if proposal is None:
            self._action_detail.clear()
            self._set_action_buttons(False)
            return
        self._action_detail.setPlainText(self._format_action_detail(proposal))
        self._set_action_buttons(
            proposal.status == ActionStatus.PENDING and proposal.id != self._busy_action_id
        )

    def _show_selected_effect(self) -> None:
        effect = self._selected_effect()
        if effect is None:
            self._effect_detail.clear()
            self._set_effect_buttons(None)
            return
        self._effect_detail.setPlainText(self._format_effect_detail(effect))
        self._set_effect_buttons(effect)

    def _resolve_effect_succeeded(self) -> None:
        effect = self._selected_effect()
        if effect is None or effect.status != EffectStatus.UNCERTAIN:
            return
        note = self._ask_reconciliation_note(
            "确认副作用已成功",
            "请填写在目标系统中核对成功的证据或依据：",
        )
        if note is None:
            return
        result, accepted = QInputDialog.getMultiLineText(
            self,
            "记录实际结果",
            "可选：填写外部 ID、文件摘要或其他实际结果：",
        )
        if not accepted:
            return
        self._resolve_effect(
            effect,
            EffectResolution.SUCCEEDED,
            note,
            result=result.strip() or None,
        )

    def _resolve_effect_not_applied(self) -> None:
        effect = self._selected_effect()
        if effect is None or effect.status != EffectStatus.UNCERTAIN:
            return
        note = self._ask_reconciliation_note(
            "确认副作用未生效",
            "请填写确认目标系统未发生该副作用的证据或依据：",
        )
        if note is None:
            return
        self._resolve_effect(effect, EffectResolution.NOT_APPLIED, note)

    def _resolve_effect_retry(self) -> None:
        effect = self._selected_effect()
        if effect is None or effect.status != EffectStatus.UNCERTAIN or not effect.retry_safe:
            return
        note = self._ask_reconciliation_note(
            "允许安全重试",
            "请填写确认该操作具备幂等性、可以安全重试的依据：",
        )
        if note is None:
            return
        self._resolve_effect(effect, EffectResolution.RETRY_APPROVED, note)

    def _resolve_effect(
        self,
        effect: Any,
        resolution: EffectResolution,
        note: str,
        *,
        result: Any = None,
    ) -> None:
        try:
            self._busy_effect_key = effect.effect_key
            self._set_effect_buttons(effect)
            self._app.resolve_effect(
                effect.effect_key,
                resolution=resolution,
                note=note,
                result=result,
            )
        except Exception as exc:
            QMessageBox.warning(self, "对账失败", str(exc))
        finally:
            self._busy_effect_key = None
        self.refresh_all()

    def _ask_reconciliation_note(self, title: str, prompt: str) -> Optional[str]:
        note, accepted = QInputDialog.getMultiLineText(self, title, prompt)
        note = note.strip()
        if not accepted:
            return None
        if not note:
            QMessageBox.warning(self, "缺少依据", "必须填写人工核对依据。")
            return None
        return note

    def _approve_selected(self) -> None:
        proposal = self._selected_proposal()
        if proposal is None or proposal.status != ActionStatus.PENDING:
            return
        answer = QMessageBox.question(
            self,
            "确认执行",
            f"批准后将执行工具 “{proposal.tool_name}”。\n\n"
            f"影响：{proposal.impact}\n"
            f"风险：{proposal.risk}\n\n"
            "是否批准并立即执行？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._busy_action_id = proposal.id
        self._set_action_buttons(False)
        threading.Thread(
            target=self._execute_approval,
            args=(proposal.id, proposal.conversation_id),
            daemon=True,
            name=f"approve-{proposal.id[-8:]}",
        ).start()

    def _execute_approval(
        self,
        proposal_id: str,
        conversation_id: Optional[str],
    ) -> None:
        try:
            proposal = self._app.approve_action(
                proposal_id,
                conversation_id=conversation_id,
            )
        except Exception as exc:
            self._safe_emit(
                self._signals.operation_finished,
                False,
                f"动作执行失败：{exc}",
            )
            return
        ok = proposal.status == ActionStatus.COMPLETED
        message = f"动作 {proposal.id} 执行完成。" if ok else f"动作执行失败：{proposal.error or '未知错误'}"
        self._safe_emit(self._signals.operation_finished, ok, message)

    def _reject_selected(self) -> None:
        proposal = self._selected_proposal()
        if proposal is None or proposal.status != ActionStatus.PENDING:
            return
        answer = QMessageBox.question(
            self,
            "确认拒绝",
            f"确定拒绝动作 “{proposal.tool_name}” 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._app.reject_action(
                proposal.id,
                conversation_id=proposal.conversation_id,
            )
        except Exception as exc:
            QMessageBox.warning(self, "拒绝失败", str(exc))
            return
        self.refresh_all()

    def _on_operation_finished(self, success: bool, message: str) -> None:
        self._busy_action_id = None
        self._busy_run_id = None
        self.refresh_all()
        if success:
            QMessageBox.information(self, "执行完成", message)
        else:
            QMessageBox.warning(self, "执行失败", message)

    def _selected_proposal(self) -> Optional[Any]:
        return self._proposal_by_id.get(self._selected_id(self._actions_table) or "")

    def _selected_run(self) -> Optional[Any]:
        return self._run_by_id.get(self._selected_id(self._runs_table) or "")

    def _selected_effect(self) -> Optional[Any]:
        return self._effect_by_key.get(self._selected_id(self._effects_table) or "")

    def _set_run_buttons(self, run: Optional[Any]) -> None:
        busy = run is None or run.id == self._busy_run_id
        can_resume = bool(run and run.can_resume)
        can_retry = bool(run and run.can_retry)
        can_replay = bool(
            run
            and run.metadata.get("graph_runtime")
            and run.status.terminal
            and run.metadata.get("approval_kind") != "tool"
        )
        if run and hasattr(self._app, "can_resume_run"):
            can_resume = self._app.can_resume_run(run.id)
        if run and hasattr(self._app, "can_retry_run"):
            can_retry = self._app.can_retry_run(run.id)
        if run and hasattr(self._app, "can_replay_run"):
            can_replay = self._app.can_replay_run(run.id)
        self._resume_run_button.setEnabled(
            bool(not busy and hasattr(self._app, "resume_run") and can_resume)
        )
        self._retry_run_button.setEnabled(
            bool(not busy and hasattr(self._app, "retry_run") and can_retry)
        )
        self._replay_run_button.setEnabled(
            bool(not busy and hasattr(self._app, "replay_run") and can_replay)
        )

    def _set_action_buttons(self, enabled: bool) -> None:
        self._approve_button.setEnabled(enabled)
        self._reject_button.setEnabled(enabled)

    def _set_effect_buttons(self, effect: Optional[Any]) -> None:
        enabled = bool(
            effect
            and effect.status == EffectStatus.UNCERTAIN
            and effect.effect_key != self._busy_effect_key
            and hasattr(self._app, "resolve_effect")
        )
        self._effect_success_button.setEnabled(enabled)
        self._effect_failed_button.setEnabled(enabled)
        self._effect_retry_button.setEnabled(bool(enabled and effect.retry_safe))

    @staticmethod
    def _selected_id(table: QTableWidget) -> Optional[str]:
        selected = table.selectedItems()
        if not selected:
            return None
        return selected[0].data(Qt.ItemDataRole.UserRole)

    @staticmethod
    def _restore_selection(table: QTableWidget, selected_id: Optional[str]) -> None:
        if table.rowCount() == 0:
            return
        target_row = 0
        if selected_id:
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item and item.data(Qt.ItemDataRole.UserRole) == selected_id:
                    target_row = row
                    break
        table.selectRow(target_row)

    @staticmethod
    def _format_time(value: Optional[datetime]) -> str:
        if value is None:
            return "-"
        return value.astimezone().strftime("%m-%d %H:%M:%S")

    @staticmethod
    def _duration(run: Any) -> str:
        if run.started_at is None:
            return "-"
        end = run.finished_at or datetime.now(run.started_at.tzinfo)
        seconds = max(0.0, (end - run.started_at).total_seconds())
        if seconds < 1:
            return f"{seconds * 1000:.0f} ms"
        if seconds < 60:
            return f"{seconds:.1f} s"
        return f"{seconds / 60:.1f} min"

    @staticmethod
    def _run_summary(run: Any) -> str:
        source = run.input or {}
        for key in ("message", "task", "tool", "name", "topic"):
            value = source.get(key)
            if value:
                text = str(value).replace("\n", " ")
                return text[:96] + ("…" if len(text) > 96 else "")
        if run.error:
            return run.error[:96]
        return "-"

    @classmethod
    def _format_run_detail(cls, run: Any) -> str:
        lines = [
            f"Run ID: {run.id}",
            f"类型 / 状态: {run.type.value} / {_RUN_STATUS_LABELS.get(run.status, run.status.value)}",
            f"父 Run: {run.parent_run_id or '-'}",
            f"会话: {run.conversation_id or '-'}",
            f"创建: {cls._format_time(run.created_at)}",
            f"耗时: {cls._duration(run)}",
            f"尝试次数: {run.attempt} / {run.max_attempts}",
            f"恢复策略: {run.recovery_policy.value}",
            f"恢复处理器: {run.metadata.get('run_handler', '-')}",
            f"恢复动作: {run.metadata.get('recovery_action', '-')}",
            f"租约持有者: {run.lease_owner or '-'}",
            f"租约到期: {cls._format_time(run.lease_expires_at)}",
            f"最后心跳: {cls._format_time(run.heartbeat_at)}",
            "",
            "输入",
            json.dumps(run.input, ensure_ascii=False, indent=2, default=str),
            "",
            "输出",
            json.dumps(run.result, ensure_ascii=False, indent=2, default=str),
        ]
        if run.error:
            lines.extend(["", "错误", run.error])
        if run.checkpoint:
            lines.extend(
                [
                    "",
                    "恢复点",
                    json.dumps(
                        run.checkpoint.model_dump(mode="json"),
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    ),
                ]
            )
        if run.metadata:
            lines.extend(
                [
                    "",
                    "元数据",
                    json.dumps(run.metadata, ensure_ascii=False, indent=2, default=str),
                ]
            )
        lines.extend(["", "事件时间线"])
        if not run.events:
            lines.append("（无事件）")
        for event in run.events:
            data = (
                " " + json.dumps(event.data, ensure_ascii=False, default=str) if event.data else ""
            )
            lines.append(
                f"{event.sequence:03d}  {cls._format_time(event.timestamp)}  " f"{event.type}{data}"
            )
        return "\n".join(lines)

    @classmethod
    def _format_action_detail(cls, proposal: Any) -> str:
        capabilities = ", ".join(sorted(item.value for item in proposal.capabilities))
        lines = [
            f"Action ID: {proposal.id}",
            f"来源 Run: {proposal.run_id}",
            f"会话: {proposal.conversation_id or '-'}",
            f"工具: {proposal.tool_name}",
            f"状态: {_ACTION_STATUS_LABELS.get(proposal.status, proposal.status.value)}",
            f"风险: {proposal.risk}",
            f"能力: {capabilities or '-'}",
            f"可逆: {'是' if proposal.reversible else '否'}",
            "",
            "申请原因",
            proposal.reason,
            "",
            "预期影响",
            proposal.impact,
            "",
            "执行参数",
            json.dumps(proposal.arguments, ensure_ascii=False, indent=2, default=str),
        ]
        if proposal.result is not None:
            lines.extend(["", "执行结果", str(proposal.result)])
        if proposal.error:
            lines.extend(["", "错误", proposal.error])
        return "\n".join(lines)

    @classmethod
    def _format_effect_detail(cls, effect: Any) -> str:
        lines = [
            f"Effect Key: {effect.effect_key}",
            f"Effect ID: {effect.id}",
            f"来源 Run: {effect.run_id or '-'}",
            f"类型 / 状态: {effect.kind} / "
            f"{_EFFECT_STATUS_LABELS.get(effect.status, effect.status.value)}",
            f"重试安全: {'是' if effect.retry_safe else '否'}",
            f"尝试次数: {effect.attempts}",
            f"创建: {cls._format_time(effect.created_at)}",
            f"更新: {cls._format_time(effect.updated_at)}",
            "",
            "副作用参数",
            json.dumps(effect.payload, ensure_ascii=False, indent=2, default=str),
        ]
        if effect.result is not None:
            lines.extend(
                [
                    "",
                    "实际结果",
                    json.dumps(effect.result, ensure_ascii=False, indent=2, default=str),
                ]
            )
        if effect.error:
            lines.extend(["", "错误 / 未知原因", effect.error])
        if effect.resolution:
            lines.extend(
                [
                    "",
                    "人工对账",
                    f"结论: {effect.resolution.value}",
                    f"操作人: {effect.reconciled_by or '-'}",
                    f"时间: {cls._format_time(effect.reconciled_at)}",
                    f"依据: {effect.reconciliation_note or '-'}",
                ]
            )
        return "\n".join(lines)

    def closeEvent(self, event: Any) -> None:
        self._refresh_timer.stop()
        if self._unsubscribe_run is not None:
            self._unsubscribe_run()
            self._unsubscribe_run = None
        if self._unsubscribe_action is not None:
            self._unsubscribe_action()
            self._unsubscribe_action = None
        super().closeEvent(event)
