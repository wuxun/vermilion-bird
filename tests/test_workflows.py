import pytest

from llm_chat.runtime import RunManager
from llm_chat.storage import Storage
from llm_chat.work import ArtifactFeedbackDecision, ArtifactKind, WorkItemService
from llm_chat.workflows import WorkflowParameter, WorkflowService


@pytest.fixture
def services(tmp_path):
    Storage.set_instance(None)
    storage = Storage(str(tmp_path / "workflows.db"))
    work_items = WorkItemService(
        repository=storage,
        runs=RunManager(repository=storage),
    )
    workflows = WorkflowService(
        repository=storage,
        work_items=work_items,
    )
    yield storage, work_items, workflows
    Storage.set_instance(None)


def _completed_source(work_items):
    item = work_items.create(objective="调研 {topic} 并形成报告")
    plan = work_items.create_plan_revision(
        item.id,
        summary="调研并交付",
        steps=[
            {"id": "research", "title": "调研"},
            {
                "id": "deliver",
                "title": "交付",
                "depends_on": ["research"],
                "expected_artifact_kind": "report",
            },
        ],
        approve=True,
    )
    run = work_items.start(item.id)
    artifact = work_items.add_artifact(
        item.id,
        run_id=run.id,
        name="report.md",
        kind=ArtifactKind.REPORT,
        content="# report",
    )
    work_items.runs.complete(run.id, "done")
    work_items.submit_artifact_feedback(
        item.id,
        artifact.id,
        decision=ArtifactFeedbackDecision.ACCEPTED,
    )
    return item, plan


def test_successful_task_becomes_immutable_workflow_v1(services):
    storage, work_items, workflows = services
    item, plan = _completed_source(work_items)

    definition, version = workflows.create_from_work_item(
        item.id,
        name="主题调研",
        objective_template="调研 {topic} 并形成报告",
        parameters=[WorkflowParameter(name="topic")],
    )

    restored = storage.get_workflow_version(definition.id, 1)
    assert definition.latest_version == 1
    assert version.source_work_item_id == item.id
    assert version.expected_artifact_kinds == [ArtifactKind.REPORT]
    assert len(version.plan_steps) == len(plan.steps)
    assert restored == version


def test_workflow_render_validates_inputs_and_pins_version(services):
    _, work_items, workflows = services
    item, _ = _completed_source(work_items)
    definition, version = workflows.create_from_work_item(
        item.id,
        objective_template="调研 {topic}，读者为 {audience}",
        parameters=[
            WorkflowParameter(name="topic"),
            WorkflowParameter(
                name="audience",
                required=False,
                default="架构师",
            ),
        ],
    )

    rendered_version, objective = workflows.render(
        definition.id,
        version=1,
        inputs={"topic": "LangGraph"},
    )

    assert rendered_version.id == version.id
    assert objective == "调研 LangGraph，读者为 架构师"
    with pytest.raises(ValueError, match="missing workflow input"):
        workflows.render(definition.id, version=1)
    with pytest.raises(ValueError, match="missing workflow input"):
        workflows.render(definition.id, version=1, inputs={"topic": ""})
    with pytest.raises(ValueError, match="unknown workflow inputs"):
        workflows.render(
            definition.id,
            inputs={"topic": "x", "extra": "y"},
        )


def test_workflow_rejects_undeclared_template_parameter(services):
    _, work_items, workflows = services
    item, _ = _completed_source(work_items)

    with pytest.raises(ValueError, match="undeclared parameters"):
        workflows.create_from_work_item(
            item.id,
            objective_template="调研 {topic}",
        )


def test_workflow_revision_preserves_v1_and_advances_latest_pointer(services):
    storage, work_items, workflows = services
    item, _ = _completed_source(work_items)
    definition, first = workflows.create_from_work_item(
        item.id,
        objective_template="调研 {topic}",
        parameters=[WorkflowParameter(name="topic")],
    )

    second = workflows.revise(
        definition.id,
        change_summary="增加受众参数",
        objective_template="调研 {topic}，面向 {audience}",
        parameters=[
            WorkflowParameter(name="topic"),
            WorkflowParameter(name="audience"),
        ],
    )

    assert second.version == 2
    assert storage.get_workflow(definition.id).latest_version == 2
    assert storage.get_workflow_version(definition.id, 1) == first
    assert storage.get_workflow_version(definition.id, 2) == second
    assert [item.version for item in workflows.list_versions(definition.id)] == [2, 1]


def test_incomplete_or_artifactless_task_cannot_be_reused(services):
    _, work_items, workflows = services
    incomplete = work_items.create(objective="尚未完成")

    with pytest.raises(ValueError, match="only a completed"):
        workflows.create_from_work_item(incomplete.id)

    run = work_items.start(incomplete.id)
    work_items.runs.complete(run.id, "done")
    with pytest.raises(ValueError, match="at least one artifact"):
        workflows.create_from_work_item(incomplete.id)


def test_unreviewed_workflow_source_must_be_accepted(services):
    _, work_items, workflows = services
    item = work_items.create(objective="生成报告")
    run = work_items.start(item.id)
    work_items.add_artifact(item.id, run_id=run.id, name="report.md", content="draft")
    work_items.runs.complete(run.id, "done")

    with pytest.raises(ValueError, match="accepted current artifact"):
        workflows.create_from_work_item(item.id)
