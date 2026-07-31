import sqlite3

import pytest

from llm_chat.product_events import ProductEventService, ProductEventType
from llm_chat.runtime import RunManager
from llm_chat.storage import Storage
from llm_chat.work import ArtifactFeedbackDecision, ArtifactKind, WorkItemService
from llm_chat.workflows import WorkflowService


@pytest.fixture
def product_services(tmp_path):
    Storage.set_instance(None)
    storage = Storage(str(tmp_path / "product-events.db"))
    events = ProductEventService(storage)
    runs = RunManager(repository=storage)
    work_items = WorkItemService(
        repository=storage,
        runs=runs,
        product_events=events,
    )
    yield storage, events, runs, work_items
    work_items.close()
    Storage.set_instance(None)


def test_product_events_are_local_deduplicated_and_content_free(product_services):
    storage, events, _, _ = product_services

    first = events.record(
        ProductEventType.WORK_ITEM_CREATED,
        subject_type="work_item",
        subject_id="work_test",
        properties={"kind": "task", "source": "gui"},
        deduplication_key="work-test-created",
    )
    duplicate = events.record(
        ProductEventType.WORK_ITEM_CREATED,
        subject_type="work_item",
        subject_id="work_test",
        properties={"kind": "task", "source": "gui"},
        deduplication_key="work-test-created",
    )

    restored = events.list(event_type=ProductEventType.WORK_ITEM_CREATED)
    assert len(restored) == 1
    assert duplicate.id == first.id
    assert restored[0].id == first.id
    assert restored[0].properties == {"kind": "task", "source": "gui"}
    assert storage.count_product_events() == 1

    with pytest.raises(ValueError, match="unsafe product event properties"):
        events.record(
            ProductEventType.WORK_ITEM_CREATED,
            subject_type="work_item",
            subject_id="work_unsafe",
            properties={"objective": "private user content"},
        )


def test_work_item_artifact_and_feedback_emit_funnel_events(product_services, tmp_path):
    _, events, runs, work_items = product_services
    item = work_items.create(
        objective="生成可验收报告",
        metadata={"source": "gui"},
    )
    run = work_items.start(item.id)
    artifact = work_items.add_artifact(
        item.id,
        run_id=run.id,
        name="report.md",
        kind=ArtifactKind.REPORT,
        content="# Report",
    )
    feedback = work_items.submit_artifact_feedback(
        item.id,
        artifact.id,
        decision=ArtifactFeedbackDecision.ACCEPTED,
        note="contains private feedback that must not enter product events",
    )
    work_items.record_artifact_viewed(artifact.id)
    destination = work_items.export_artifact(artifact.id, str(tmp_path / "export.md"))
    runs.complete(run.id, {"artifact_id": artifact.id})

    assert destination.endswith("export.md")
    assert feedback.note.startswith("contains private feedback")
    event_types = [event.type for event in events.list(work_item_id=item.id)]
    assert set(event_types) == {
        ProductEventType.WORK_ITEM_CREATED,
        ProductEventType.WORK_ITEM_STARTED,
        ProductEventType.WORK_ITEM_TERMINAL,
        ProductEventType.ARTIFACT_CREATED,
        ProductEventType.ARTIFACT_VIEWED,
        ProductEventType.ARTIFACT_FEEDBACK,
        ProductEventType.ARTIFACT_EXPORTED,
    }
    serialized = " ".join(
        str(event.model_dump(mode="json")) for event in events.list(work_item_id=item.id)
    )
    assert "private feedback" not in serialized
    assert "生成可验收报告" not in serialized


def test_v8_database_is_upgraded_with_product_event_schema(tmp_path):
    db_path = tmp_path / "v8.db"
    storage = Storage(str(db_path))
    Storage.set_instance(None)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE product_events")
        conn.execute("DELETE FROM schema_migrations WHERE version = 9")
        conn.execute("PRAGMA user_version=8")

    restored = Storage(str(db_path))

    assert restored.get_schema_info()["current_version"] == Storage.CURRENT_SCHEMA_VERSION
    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(product_events)").fetchall()
        }
    assert {
        "event_type",
        "subject_type",
        "subject_id",
        "properties_json",
        "occurred_at",
    } <= columns


def test_workflow_creation_and_revision_emit_versioned_events(product_services):
    storage, events, runs, work_items = product_services
    item = work_items.create(objective="形成可复用报告")
    run = work_items.start(item.id)
    artifact = work_items.add_artifact(
        item.id,
        run_id=run.id,
        name="report.md",
        kind=ArtifactKind.REPORT,
        content="# Reusable report",
    )
    work_items.submit_artifact_feedback(
        item.id,
        artifact.id,
        decision=ArtifactFeedbackDecision.ACCEPTED,
    )
    runs.complete(run.id, "done")
    workflows = WorkflowService(
        repository=storage,
        work_items=work_items,
        product_events=events,
    )

    definition, _ = workflows.create_from_work_item(item.id)
    workflows.revise(definition.id, change_summary="improve delivery")

    workflow_events = events.list(subject_id=definition.id)
    assert [event.type for event in workflow_events] == [
        ProductEventType.WORKFLOW_REVISED,
        ProductEventType.WORKFLOW_CREATED,
    ]
    assert [event.properties["workflow_version"] for event in workflow_events] == [2, 1]
