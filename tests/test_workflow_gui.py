from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PyQt6")

from llm_chat.frontends.scheduler_dialog import TaskEditDialog  # noqa: E402
from llm_chat.frontends.workflow_library import (  # noqa: E402
    SaveWorkflowDialog,
    WorkflowLibraryDialog,
)
from llm_chat.workflows import (  # noqa: E402
    WorkflowDefinition,
    WorkflowParameter,
    WorkflowVersion,
)


def test_workflow_library_pins_version_and_builds_parameter_form(qt_app):
    definition = WorkflowDefinition(
        id="workflow_gui",
        name="研究报告",
        description="生成固定结构的研究报告",
        latest_version=2,
    )
    first = WorkflowVersion(
        workflow_id=definition.id,
        version=1,
        objective_template="研究 {topic}",
        parameters=[WorkflowParameter(name="topic")],
    )
    second = WorkflowVersion(
        workflow_id=definition.id,
        version=2,
        objective_template="为 {audience} 研究 {topic}",
        parameters=[
            WorkflowParameter(name="topic"),
            WorkflowParameter(name="audience", default="技术负责人"),
        ],
        change_summary="增加受众参数",
    )
    app = SimpleNamespace(
        list_workflows=lambda **_kwargs: [definition],
        list_workflow_versions=lambda _workflow_id, **_kwargs: [second, first],
        run_workflow=MagicMock(),
    )

    dialog = WorkflowLibraryDialog(app)
    qt_app.processEvents()

    assert dialog.workflow_list.count() == 1
    assert dialog.version_combo.currentData() == 2
    assert set(dialog._parameter_inputs) == {"topic", "audience"}
    assert dialog._parameter_inputs["audience"].text() == "技术负责人"
    assert "为 {audience} 研究 {topic}" in dialog.objective_preview.toPlainText()
    assert "增加受众参数" in dialog.version_combo.currentText()
    assert "objective_template" in dialog.version_summary.toPlainText()

    dialog.close()
    qt_app.processEvents()


def test_scheduler_editor_selects_exact_workflow_version(qt_app):
    definition = WorkflowDefinition(
        id="workflow_scheduled_gui",
        name="每周研究",
        latest_version=2,
    )
    version = WorkflowVersion(
        workflow_id=definition.id,
        version=2,
        objective_template="研究 {topic}",
        parameters=[WorkflowParameter(name="topic", default="AI")],
        change_summary="稳定版",
    )
    app = SimpleNamespace(
        list_workflows=lambda **_kwargs: [definition],
        list_workflow_versions=lambda _workflow_id, **_kwargs: [version],
        get_workflow=lambda _workflow_id, **_kwargs: (definition, version),
        workflows=SimpleNamespace(render=MagicMock(return_value=(version, "研究 AI"))),
    )
    scheduler = SimpleNamespace(_app=app)

    dialog = TaskEditDialog(scheduler=scheduler)
    dialog._type_combo.setCurrentText("工作流")
    qt_app.processEvents()

    assert not dialog._workflow_group.isHidden()
    assert dialog._workflow_combo.currentData() == definition.id
    assert dialog._workflow_version_combo.currentData() == 2
    assert dialog._workflow_parameter_inputs["topic"].text() == "AI"

    dialog.close()
    qt_app.processEvents()


def test_save_workflow_dialog_turns_template_fields_into_parameters(qt_app):
    dialog = SaveWorkflowDialog(
        title="主题研究",
        objective="为 {audience} 研究 {topic}",
    )
    qt_app.processEvents()

    assert set(dialog._parameter_rows) == {"audience", "topic"}
    dialog._parameter_rows["audience"][2].setText("技术负责人")
    parameters = {parameter.name: parameter for parameter in dialog.parameters}
    assert parameters["audience"].default == "技术负责人"
    assert parameters["topic"].required is True

    dialog.close()
    qt_app.processEvents()
