from pathlib import Path

import pytest

from llm_chat.evaluation import EvalRunner, load_core_scenarios
from llm_chat.runtime import RunManager
from llm_chat.storage import Storage
from llm_chat.work import (
    ArtifactFeedbackDecision,
    ArtifactKind,
    ArtifactRelation,
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


def test_artifact_revision_preserves_parent_and_feedback_lineage(services):
    storage, service = services
    item = service.create(objective="生成报告")
    original = service.add_artifact(
        item.id,
        name="report.md",
        kind=ArtifactKind.REPORT,
        content="# Version one",
    )
    feedback = service.submit_artifact_feedback(
        item.id,
        original.id,
        decision=ArtifactFeedbackDecision.NEEDS_REVISION,
        note="补充风险",
    )

    revision = service.revise_artifact(
        original.id,
        content="# Version two\n\nRisks",
        source_feedback_id=feedback.id,
    )

    assert revision.id != original.id
    assert revision.lineage_id == original.lineage_id
    assert revision.version == 2
    assert revision.parent_artifact_id == original.id
    assert revision.source_feedback_id == feedback.id
    assert revision.relation == ArtifactRelation.REVISION
    assert revision.checksum != original.checksum
    assert storage.get_artifact(original.id).content == "# Version one"
    assert [artifact.id for artifact in service.list_artifact_versions(revision.id)] == [
        revision.id,
        original.id,
    ]


def test_artifact_storage_rejects_in_place_mutation(services):
    storage, service = services
    item = service.create(objective="生成报告")
    artifact = service.add_artifact(item.id, name="report.md", content="original")

    mutated = artifact.model_copy(update={"content": "overwritten"})

    with pytest.raises(ValueError, match="immutable"):
        storage.save_artifact(mutated)
    assert storage.get_artifact(artifact.id).content == "original"


def test_artifact_revision_validates_parent_and_feedback_scope(services):
    _, service = services
    first = service.create(objective="任务一")
    second = service.create(objective="任务二")
    parent = service.add_artifact(first.id, name="first.md", content="first")
    other = service.add_artifact(second.id, name="second.md", content="second")
    feedback = service.submit_artifact_feedback(
        second.id,
        other.id,
        decision=ArtifactFeedbackDecision.NEEDS_REVISION,
    )

    with pytest.raises(KeyError, match="parent artifact"):
        service.add_artifact(
            second.id,
            name="invalid.md",
            content="invalid",
            parent_artifact_id=parent.id,
            relation=ArtifactRelation.REVISION,
        )
    with pytest.raises(KeyError, match="source feedback"):
        service.revise_artifact(parent.id, content="invalid", source_feedback_id=feedback.id)


def test_artifact_preview_and_diff_are_bounded_and_lineage_safe(services):
    _, service = services
    item = service.create(objective="生成报告")
    original = service.add_artifact(
        item.id,
        name="report.md",
        content="line one\nline two\n",
    )
    revision = service.revise_artifact(
        original.id,
        content="line one\nline changed\n",
    )

    preview = service.preview_artifact(revision.id, max_chars=8)
    diff = service.diff_artifact_versions(original.id, revision.id)

    assert preview.truncated is True
    assert "预览已按安全上限截断" in preview.content
    assert "-line two" in diff.content
    assert "+line changed" in diff.content
    assert diff.left_version == 1
    assert diff.right_version == 2

    other = service.add_artifact(item.id, name="other.md", content="other")
    with pytest.raises(ValueError, match="same lineage"):
        service.diff_artifact_versions(original.id, other.id)


def test_artifact_preview_reads_local_text_but_not_binary_payload(services, tmp_path):
    _, service = services
    item = service.create(objective="预览文件")
    text_path = tmp_path / "result.txt"
    text_path.write_text("local result", encoding="utf-8")
    binary_path = tmp_path / "result.bin"
    binary_path.write_bytes(b"\x00private-binary")
    text_artifact = service.add_artifact(
        item.id,
        name=text_path.name,
        kind=ArtifactKind.FILE,
        uri=str(text_path),
    )
    binary_artifact = service.add_artifact(
        item.id,
        name=binary_path.name,
        kind=ArtifactKind.FILE,
        uri=str(binary_path),
    )

    assert service.preview_artifact(text_artifact.id).content == "local result"
    binary_preview = service.preview_artifact(binary_artifact.id)
    assert "暂不支持内嵌预览" in binary_preview.content
    assert "private-binary" not in binary_preview.content


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


def test_eval_acceptance_uses_latest_version_in_each_lineage(services):
    _, service = services
    item = service.create(objective="生成报告")
    run = service.start(item.id)
    original = service.add_artifact(
        item.id,
        run_id=run.id,
        name="report.md",
        kind=ArtifactKind.REPORT,
        content="# Draft",
    )
    feedback = service.submit_artifact_feedback(
        item.id,
        original.id,
        decision=ArtifactFeedbackDecision.NEEDS_REVISION,
    )
    revision = service.revise_artifact(
        original.id,
        content="# Final",
        source_feedback_id=feedback.id,
    )
    service.submit_artifact_feedback(
        item.id,
        revision.id,
        decision=ArtifactFeedbackDecision.ACCEPTED,
    )
    service.runs.complete(run.id, "done")

    result = EvalRunner().evaluate(load_core_scenarios()[0], service.detail(item.id))

    assert result.artifact_count == 1
    assert result.reviewed_artifact_count == 1
    assert result.accepted_artifact_count == 1
