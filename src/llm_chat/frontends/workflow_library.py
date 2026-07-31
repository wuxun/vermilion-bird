"""Workflow Library: discover, pin, parameterize and run reusable work."""

from __future__ import annotations

import difflib
import json
import threading
from string import Formatter
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from llm_chat.frontends.theme import Colors
from llm_chat.workflows import WorkflowParameter


class _WorkflowSignals(QObject):
    finished = pyqtSignal(bool, str)


class SaveWorkflowDialog(QDialog):
    """Describe a reusable template without exposing raw JSON configuration."""

    def __init__(
        self,
        *,
        title: str,
        objective: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._parameter_rows: Dict[str, tuple] = {}
        self.setWindowTitle("保存为工作流")
        self.resize(620, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)
        heading = QLabel("保存为工作流")
        heading.setStyleSheet("font-size: 17px; font-weight: 700;")
        root.addWidget(heading)
        hint = QLabel(
            "把会变化的部分写成 {参数名}，运行时会自动生成填写表单。"
        )
        hint.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        root.addWidget(hint)

        form = QFormLayout()
        self.name_input = QLineEdit(title)
        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText(
            "说明这个工作流适合在什么情况下使用"
        )
        self.objective_input = QTextEdit()
        self.objective_input.setPlainText(objective)
        self.objective_input.setMinimumHeight(130)
        self.objective_input.textChanged.connect(self._refresh_parameters)
        form.addRow("名称 *", self.name_input)
        form.addRow("说明", self.description_input)
        form.addRow("目标模板 *", self.objective_input)
        root.addLayout(form)

        self.parameters_widget = QWidget()
        self.parameters_form = QFormLayout(self.parameters_widget)
        root.addWidget(QLabel("模板参数"))
        root.addWidget(self.parameters_widget, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存工作流")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._refresh_parameters()

    @property
    def workflow_name(self) -> str:
        return self.name_input.text().strip()

    @property
    def description(self) -> str:
        return self.description_input.text().strip()

    @property
    def objective_template(self) -> str:
        return self.objective_input.toPlainText().strip()

    @property
    def parameters(self):
        values = []
        for name, (description, required, default) in self._parameter_rows.items():
            default_value = default.text().strip() or None
            values.append(
                WorkflowParameter(
                    name=name,
                    description=description.text().strip(),
                    required=required.isChecked(),
                    default=default_value,
                )
            )
        return values

    def _refresh_parameters(self) -> None:
        existing = self._parameter_rows
        try:
            names = self._template_parameter_names(self.objective_input.toPlainText())
        except ValueError:
            return
        while self.parameters_form.rowCount():
            self.parameters_form.removeRow(0)
        self._parameter_rows = {}
        for name in names:
            previous = existing.get(name)
            description = QLineEdit(previous[0].text() if previous else "")
            description.setPlaceholderText("参数说明")
            required = QCheckBox("必填")
            required.setChecked(previous[1].isChecked() if previous else True)
            default = QLineEdit(previous[2].text() if previous else "")
            default.setPlaceholderText("默认值（可选）")
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(description, 2)
            layout.addWidget(required)
            layout.addWidget(default, 1)
            self.parameters_form.addRow(name, row)
            self._parameter_rows[name] = (description, required, default)
        if not names:
            empty = QLabel("当前模板没有参数，将按固定目标重复运行。")
            empty.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
            self.parameters_form.addRow(empty)

    @staticmethod
    def _template_parameter_names(template: str):
        names = []
        for _, name, _, _ in Formatter().parse(template):
            if name and name not in names:
                if not name.isidentifier():
                    raise ValueError(f"参数名必须是简单标识符：{name}")
                names.append(name)
        return names

    def accept(self) -> None:
        if not self.workflow_name:
            QMessageBox.warning(self, "名称不能为空", "请填写工作流名称。")
            return
        if not self.objective_template:
            QMessageBox.warning(self, "目标不能为空", "请填写目标模板。")
            return
        try:
            names = self._template_parameter_names(self.objective_template)
            if set(names) != set(self._parameter_rows):
                self._refresh_parameters()
                names = self._template_parameter_names(self.objective_template)
            if set(names) != set(self._parameter_rows):
                raise ValueError("请修正模板参数后重试")
            self.parameters
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "模板无效", str(exc))
            return
        super().accept()


class WorkflowLibraryDialog(QDialog):
    """Run one explicit immutable Workflow version from a parameter form."""

    def __init__(self, app: Any, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._app = app
        self._definitions: Dict[str, Any] = {}
        self._versions: Dict[int, Any] = {}
        self._parameter_inputs: Dict[str, QLineEdit] = {}
        self._running = False
        self._signals = _WorkflowSignals()
        self._signals.finished.connect(self._on_run_finished)

        self.setWindowTitle("工作流库")
        self.resize(940, 650)
        self.setMinimumSize(720, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel("工作流库")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(title)
        subtitle = QLabel(
            "选择一个固定版本，填写参数后运行；后续修订不会改变本次执行。"
        )
        subtitle.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        root.addWidget(subtitle)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workflow_list = QListWidget()
        self.workflow_list.setMinimumWidth(220)
        self.workflow_list.currentItemChanged.connect(self._on_workflow_selected)
        splitter.addWidget(self.workflow_list)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(14, 0, 0, 0)
        self.name_label = QLabel("选择一个工作流")
        self.name_label.setStyleSheet("font-size: 16px; font-weight: 650;")
        detail_layout.addWidget(self.name_label)
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        detail_layout.addWidget(self.description_label)

        version_row = QHBoxLayout()
        version_row.addWidget(QLabel("固定版本"))
        self.version_combo = QComboBox()
        self.version_combo.currentIndexChanged.connect(self._on_version_selected)
        version_row.addWidget(self.version_combo)
        version_row.addStretch(1)
        detail_layout.addLayout(version_row)

        self.tabs = QTabWidget()
        run_page = QWidget()
        run_layout = QVBoxLayout(run_page)
        run_layout.setContentsMargins(8, 10, 8, 8)
        run_layout.addWidget(QLabel("目标模板"))
        self.objective_preview = QTextBrowser()
        self.objective_preview.setMaximumHeight(120)
        run_layout.addWidget(self.objective_preview)
        self.parameters_form = QFormLayout()
        run_layout.addLayout(self.parameters_form)
        workspace_row = QHBoxLayout()
        workspace_row.addWidget(QLabel("工作目录"))
        self.workspace_input = QLineEdit()
        self.workspace_input.setPlaceholderText("可选：为本次运行指定工作目录")
        workspace_row.addWidget(self.workspace_input, 1)
        choose_workspace = QPushButton("选择…")
        choose_workspace.clicked.connect(self._choose_workspace)
        workspace_row.addWidget(choose_workspace)
        run_layout.addLayout(workspace_row)
        run_layout.addStretch(1)
        self.tabs.addTab(run_page, "运行")

        version_page = QWidget()
        version_layout = QVBoxLayout(version_page)
        version_layout.setContentsMargins(8, 10, 8, 8)
        self.version_summary = QTextBrowser()
        self.version_summary.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        version_layout.addWidget(self.version_summary)
        self.tabs.addTab(version_page, "版本差异")
        detail_layout.addWidget(self.tabs, 1)

        actions = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        actions.addWidget(self.status_label)
        actions.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.reject)
        actions.addWidget(close_button)
        self.run_button = QPushButton("运行此版本")
        self.run_button.clicked.connect(self._run_selected)
        self.run_button.setEnabled(False)
        actions.addWidget(self.run_button)
        detail_layout.addLayout(actions)

        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self.refresh()

    def refresh(self) -> None:
        self.workflow_list.clear()
        self._definitions = {
            definition.id: definition for definition in self._app.list_workflows(limit=200)
        }
        for definition in self._definitions.values():
            item = QListWidgetItem(
                f"{definition.name}\n最新 v{definition.latest_version}"
            )
            item.setData(Qt.ItemDataRole.UserRole, definition.id)
            self.workflow_list.addItem(item)
        if self.workflow_list.count():
            self.workflow_list.setCurrentRow(0)
            self.status_label.setText(f"共 {self.workflow_list.count()} 个工作流")
        else:
            self.status_label.setText(
                "还没有可复用工作流。请先接受一个任务结果并保存为工作流。"
            )

    def _on_workflow_selected(self, current, _previous=None) -> None:
        if current is None:
            return
        workflow_id = current.data(Qt.ItemDataRole.UserRole)
        definition = self._definitions.get(workflow_id)
        if definition is None:
            return
        self.name_label.setText(definition.name)
        self.description_label.setText(definition.description or "暂无说明")
        versions = self._app.list_workflow_versions(workflow_id, limit=100)
        self._versions = {version.version: version for version in versions}
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        for version in versions:
            label = f"v{version.version}"
            if version.change_summary:
                label += f" · {version.change_summary}"
            self.version_combo.addItem(label, version.version)
        self.version_combo.blockSignals(False)
        if self.version_combo.count():
            self.version_combo.setCurrentIndex(0)
            self._on_version_selected()

    def _on_version_selected(self) -> None:
        version = self._versions.get(self.version_combo.currentData())
        self._clear_parameter_form()
        if version is None:
            self.run_button.setEnabled(False)
            return
        self.objective_preview.setPlainText(version.objective_template)
        for parameter in version.parameters:
            field = QLineEdit()
            field.setText(parameter.default or "")
            field.setPlaceholderText(parameter.description)
            label = parameter.name + (" *" if parameter.required else "")
            self.parameters_form.addRow(label, field)
            self._parameter_inputs[parameter.name] = field
        if not version.parameters:
            no_parameters = QLabel("此版本无需参数。")
            no_parameters.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
            self.parameters_form.addRow(no_parameters)
        self._render_version_diff(version)
        self.run_button.setEnabled(not self._running)

    def _clear_parameter_form(self) -> None:
        self._parameter_inputs = {}
        while self.parameters_form.rowCount():
            self.parameters_form.removeRow(0)

    def _render_version_diff(self, version: Any) -> None:
        previous = self._versions.get(version.version - 1)
        current_text = self._version_text(version)
        if previous is None:
            self.version_summary.setPlainText(
                f"这是初始版本。\n\n{current_text}"
            )
            return
        lines = difflib.unified_diff(
            self._version_text(previous).splitlines(),
            current_text.splitlines(),
            fromfile=f"v{previous.version}",
            tofile=f"v{version.version}",
            lineterm="",
        )
        self.version_summary.setPlainText("\n".join(lines) or "两个版本没有结构差异。")

    @staticmethod
    def _version_text(version: Any) -> str:
        payload = {
            "objective_template": version.objective_template,
            "parameters": [item.model_dump(mode="json") for item in version.parameters],
            "plan_steps": version.plan_steps,
            "expected_artifact_kinds": [
                item.value for item in version.expected_artifact_kinds
            ],
            "required_resources": version.required_resources,
            "budget": version.budget,
            "approval_policy": version.approval_policy,
            "failure_policy": version.failure_policy,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)

    def _choose_workspace(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择本次运行的工作目录")
        if path:
            self.workspace_input.setText(path)

    def _run_selected(self) -> None:
        current = self.workflow_list.currentItem()
        version = self._versions.get(self.version_combo.currentData())
        if current is None or version is None or self._running:
            return
        inputs = {
            name: field.text()
            for name, field in self._parameter_inputs.items()
            if field.text() or name in {item.name for item in version.parameters if item.required}
        }
        workflow_id = current.data(Qt.ItemDataRole.UserRole)
        workspace = self.workspace_input.text().strip() or None
        self._running = True
        self.run_button.setEnabled(False)
        self.status_label.setText(f"正在运行 v{version.version}…")

        def worker():
            try:
                detail = self._app.run_workflow(
                    workflow_id,
                    version=version.version,
                    inputs=inputs,
                    workspace=workspace,
                    entrypoint="gui",
                )
                work_item_id = detail.work_item.id
            except Exception as exc:
                self._signals.finished.emit(False, str(exc))
            else:
                self._signals.finished.emit(True, work_item_id)

        threading.Thread(target=worker, name="workflow-library-run", daemon=True).start()

    def _on_run_finished(self, succeeded: bool, message: str) -> None:
        self._running = False
        self.run_button.setEnabled(True)
        if succeeded:
            self.status_label.setText(f"运行已完成 · {message}")
            QMessageBox.information(self, "工作流运行完成", f"任务：{message}")
        else:
            self.status_label.setText("运行失败")
            QMessageBox.critical(self, "工作流运行失败", message)
