from pathlib import Path

import pytest

from llm_chat.evaluation import EvalRunner, load_core_scenarios
from llm_chat.runtime import RunManager
from llm_chat.storage import Storage
from llm_chat.work import (
    ArtifactFeedbackDecision,
    ArtifactKind,
    WorkItemService,
)


@pytest.fixture
def services(tmp_path):
    Storage.set_instance(None)
    storage = Storage(str(tmp_path / "artifact-feedback.db"))
    service = WorkItemService(
        repository=storage,
        runs=RunManager(repository=storage),
    )
    yield storage, service
    Storage.set_instance(None)


def test_feedback_history_is_persisted_and_exposed_in_task_detail(services):
    _, service = services
    item = service.create(objective="生成报告")
    artifact = service.add_artifact(
        item.id,
        name="report.md",
        kind=ArtifactKind.REPORT,
        content="# Report",
    )

    revision = service.submit_artifact_feedback(
        item.id,
        artifact.id,
        decision=ArtifactFeedbackDecision.NEEDS_REVISION,
        note="补充风险说明",
    )
    accepted = service.submit_artifact_feedback(
        item.id,
        artifact.id,
        decision=ArtifactFeedbackDecision.ACCEPTED,
    )
    detail = service.detail(item.id)

    assert revision.note == "补充风险说明"
    assert [feedback.id for feedback in detail.artifact_feedback] == [
        accepted.id,
        revision.id,
    ]


def test_artifact_export_is_atomic_and_does_not_overwrite_by_default(
    services,
    tmp_path,
):
    _, service = services
    item = service.create(objective="生成报告")
    artifact = service.add_artifact(
        item.id,
        name="report.md",
        content="# Final report",
    )
    destination = tmp_path / "exports"

    exported = service.export_artifact(artifact.id, str(destination))

    path = Path(exported)
    assert path.name == "exports"
    assert path.read_text(encoding="utf-8") == "# Final report"
    with pytest.raises(FileExistsError):
        service.export_artifact(artifact.id, str(destination))
    assert not list(tmp_path.glob(".*.tmp"))


def test_artifact_export_copies_local_file_to_directory(services, tmp_path):
    _, service = services
    source = tmp_path / "source.txt"
    source.write_text("source payload", encoding="utf-8")
    destination = tmp_path / "delivery"
    destination.mkdir()
    item = service.create(objective="复制产物")
    artifact = service.add_artifact(
        item.id,
        name="copy.txt",
        kind=ArtifactKind.FILE,
        uri=str(source),
    )

    exported = service.export_artifact(artifact.id, str(destination))

    assert Path(exported) == destination / "copy.txt"
    assert Path(exported).read_text(encoding="utf-8") == "source payload"


def test_feedback_rejects_artifact_from_another_work_item(services):
    _, service = services
    first = service.create(objective="任务一")
    second = service.create(objective="任务二")
    artifact = service.add_artifact(first.id, name="result.txt", content="x")

    with pytest.raises(KeyError, match="Unknown artifact"):
        service.submit_artifact_feedback(
            second.id,
            artifact.id,
            decision=ArtifactFeedbackDecision.REJECTED,
        )


def test_eval_report_calculates_latest_artifact_acceptance_rate(services):
    _, service = services
    item = service.create(objective="生成报告")
    run = service.start(item.id)
    artifact = service.add_artifact(
        item.id,
        run_id=run.id,
        name="report.md",
        kind=ArtifactKind.REPORT,
        content="# Report",
    )
    service.runs.complete(run.id, "done")
    service.submit_artifact_feedback(
        item.id,
        artifact.id,
        decision=ArtifactFeedbackDecision.NEEDS_REVISION,
    )
    service.submit_artifact_feedback(
        item.id,
        artifact.id,
        decision=ArtifactFeedbackDecision.ACCEPTED,
    )

    result = EvalRunner().evaluate(
        load_core_scenarios()[0],
        service.detail(item.id),
    )
    report = EvalRunner().report([result])

    assert result.reviewed_artifact_count == 1
    assert result.accepted_artifact_count == 1
    assert report.artifact_acceptance_rate == 1.0
