"""用户任务与交付物中心。"""

from __future__ import annotations

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
from llm_chat.work import WorkItemKind, WorkItemStatus


_STATUS_LABELS: Dict[WorkItemStatus, str] = {
    WorkItemStatus.DRAFT: "草稿",
    WorkItemStatus.READY: "待执行",
    WorkItemStatus.RUNNING: "执行中",
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
        title.setStyleSheet(
            f"font-size: 20px; font-weight: 700; color: {Colors.TEXT_PRIMARY};"
        )
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
        self._tabs.addTab(self._overview, "概览")
        self._tabs.addTab(self._runs_table, "执行")
        self._tabs.addTab(self._artifacts_table, "产物")
        detail_layout.addWidget(self._tabs, 1)

        actions = QHBoxLayout()
        self._cancel_button = QPushButton("取消任务")
        self._cancel_button.clicked.connect(self._cancel_selected)
        self._retry_button = QPushButton("重试")
        self._retry_button.clicked.connect(self._retry_selected)
        self._open_artifact_button = QPushButton("打开产物")
        self._open_artifact_button.clicked.connect(self._open_selected_artifact)
        actions.addWidget(self._cancel_button)
        actions.addWidget(self._retry_button)
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
        work_item_id = self._table.item(selected[0].row(), 0).data(
            Qt.ItemDataRole.UserRole
        )
        self._selected_work_item_id = work_item_id
        self._load_detail(work_item_id)

    def _load_detail(self, work_item_id: str) -> None:
        try:
            detail = self._app.get_work_item_detail(work_item_id)
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

        self._artifacts_by_id = {artifact.id: artifact for artifact in detail.artifacts}
        self._artifacts_table.setRowCount(len(detail.artifacts))
        for row, artifact in enumerate(detail.artifacts):
            name_item = QTableWidgetItem(artifact.name)
            name_item.setData(Qt.ItemDataRole.UserRole, artifact.id)
            self._artifacts_table.setItem(row, 0, name_item)
            self._artifacts_table.setItem(row, 1, QTableWidgetItem(artifact.kind.value))
            location = artifact.uri or ("内嵌内容" if artifact.content else "")
            self._artifacts_table.setItem(row, 2, QTableWidgetItem(location))
        self._tabs.setTabText(2, f"产物 ({len(detail.artifacts)})")
        self._update_actions(item)

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
        if QMessageBox.question(self, "取消任务", "确定取消当前任务吗？") != (
            QMessageBox.StandardButton.Yes
        ):
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
        self._cancel_button.setEnabled(bool(item and not item.status.terminal and not busy))
        self._retry_button.setEnabled(
            bool(item and item.status == WorkItemStatus.FAILED and not busy)
        )
        self._open_artifact_button.setEnabled(bool(self._artifacts_by_id))

    def _clear_detail(self) -> None:
        self._detail_title.setText("选择一个任务")
        self._overview.clear()
        self._runs_table.setRowCount(0)
        self._artifacts_table.setRowCount(0)
        self._artifacts_by_id = {}
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
