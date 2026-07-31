import sqlite3

import pytest

from llm_chat.context import (
    ContextKind,
    ContextQuery,
    ContextResourceService,
    ExternalTransferPolicy,
    ResourceContextProvider,
)
from llm_chat.product_events import ProductEventService, ProductEventType
from llm_chat.storage import Storage
from llm_chat.work import WorkItem


@pytest.fixture
def resource_services(tmp_path):
    Storage.set_instance(None)
    storage = Storage(str(tmp_path / "context-resources.db"))
    for index in range(1, 6):
        storage.create_conversation(f"conversation-{index}", f"Conversation {index}")
    events = ProductEventService(storage)
    resources = ContextResourceService(storage, product_events=events)
    yield storage, events, resources
    Storage.set_instance(None)


def test_file_resource_round_trip_deduplication_and_removal(resource_services, tmp_path):
    storage, events, resources = resource_services
    source = tmp_path / "brief.md"
    source.write_text("# Private brief\n\nImportant facts", encoding="utf-8")

    created = resources.attach_path("conversation-1", str(source))
    duplicate = resources.attach_path("conversation-1", str(source))

    assert duplicate.id == created.id
    assert created.display_name == "brief.md"
    assert created.snapshot_hash
    assert created.size_bytes == source.stat().st_size
    assert created.source_path == str(source.resolve())
    assert storage.get_context_resource(created.id) == created
    content, changed = resources.read_for_context(created)
    assert "Important facts" in content
    assert changed is False

    removed = resources.remove(created.id)
    assert removed.status.value == "removed"
    assert resources.list(conversation_id="conversation-1") == []
    assert [event.type for event in events.list(subject_id=created.id)] == [
        ProductEventType.CONTEXT_RESOURCE_REMOVED,
        ProductEventType.CONTEXT_RESOURCE_ATTACHED,
    ]


def test_resource_provider_injects_content_and_reports_source_change(
    resource_services,
    tmp_path,
):
    _, _, resources = resource_services
    source = tmp_path / "notes.txt"
    source.write_text("first version", encoding="utf-8")
    resource = resources.attach_path("conversation-2", str(source))
    provider = ResourceContextProvider(resources)

    initial = provider.retrieve(ContextQuery(conversation_id="conversation-2"))
    source.write_text("second version", encoding="utf-8")
    changed = provider.retrieve(ContextQuery(conversation_id="conversation-2"))

    assert len(initial) == 1
    assert initial[0].kind == ContextKind.RESOURCE
    assert "first version" in initial[0].content
    assert changed[0].metadata["changed_since_attachment"] is True
    assert "second version" in changed[0].content
    assert "已发生变化" in changed[0].content
    assert resource.source_path not in changed[0].content


def test_directory_context_skips_hidden_and_binary_files(resource_services, tmp_path):
    _, _, resources = resource_services
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("visible context", encoding="utf-8")
    (root / "image.png").write_bytes(b"\x89PNG")
    hidden = root / ".secret"
    hidden.mkdir()
    (hidden / "token.txt").write_text("must not be read", encoding="utf-8")

    resource = resources.attach_path("conversation-3", str(root))
    content, changed = resources.read_for_context(resource)

    assert changed is False
    assert "visible context" in content
    assert "must not be read" not in content
    assert "PNG" not in content


def test_local_only_resource_is_persisted_but_not_injected(resource_services, tmp_path):
    _, _, resources = resource_services
    source = tmp_path / "local.txt"
    source.write_text("never send this", encoding="utf-8")
    resource = resources.attach_path(
        "conversation-4",
        str(source),
        transfer_policy=ExternalTransferPolicy.LOCAL_ONLY,
    )

    content, changed = resources.read_for_context(resource)

    assert content == ""
    assert changed is False


def test_resources_bind_to_promoted_work_item(resource_services, tmp_path):
    storage, _, resources = resource_services
    source = tmp_path / "input.md"
    source.write_text("task input", encoding="utf-8")
    resource = resources.attach_path("conversation-5", str(source))
    item = WorkItem(title="Goal", objective="Use attachment")
    assert storage.create_work_item(item)

    updated = resources.bind_work_item("conversation-5", item.id)

    assert updated == 1
    assert storage.get_context_resource(resource.id).work_item_id == item.id


def test_v9_database_is_upgraded_with_context_resource_schema(tmp_path):
    db_path = tmp_path / "v9.db"
    Storage.set_instance(None)
    Storage(str(db_path))
    Storage.set_instance(None)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE context_resources")
        conn.execute("DELETE FROM schema_migrations WHERE version = 10")
        conn.execute("PRAGMA user_version=9")

    restored = Storage(str(db_path))

    assert restored.get_schema_info()["current_version"] == Storage.CURRENT_SCHEMA_VERSION
    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(context_resources)").fetchall()
        }
    assert {
        "conversation_id",
        "source_path",
        "snapshot_hash",
        "transfer_policy",
        "status",
    } <= columns
