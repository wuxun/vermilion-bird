"""Storage integrity regressions for FTS synchronization and foreign keys."""

import pytest

from llm_chat.storage import Storage


@pytest.fixture
def storage(tmp_path):
    Storage.set_instance(None)
    instance = Storage(str(tmp_path / "integrity.db"))
    yield instance
    Storage.set_instance(None)


def test_fts_tracks_insert_update_and_delete(storage):
    storage.create_conversation("conv-fts")
    message_id = storage.add_message("conv-fts", "user", "vermilion phoenix")

    assert [row["id"] for row in storage.search_messages("phoenix")] == [message_id]

    with storage._get_connection() as conn:
        conn.execute(
            "UPDATE messages SET content = ? WHERE id = ?",
            ("ember runtime", message_id),
        )

    assert storage.search_messages("phoenix") == []
    assert [row["id"] for row in storage.search_messages("ember")] == [message_id]

    storage.clear_messages("conv-fts")
    assert storage.search_messages("ember") == []


def test_foreign_keys_are_enabled_on_every_connection(storage):
    storage.create_conversation("conv-cascade")
    storage.add_message("conv-cascade", "user", "orphan guard")

    with storage._get_connection() as conn:
        enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]

    assert enabled == 1
    storage.delete_conversation("conv-cascade")

    with storage._get_connection() as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
            ("conv-cascade",),
        ).fetchone()[0]

    assert remaining == 0


def test_message_execution_key_makes_recovery_write_idempotent(storage):
    storage.create_conversation("conv-idempotent")

    first = storage.add_message(
        "conv-idempotent",
        "assistant",
        "first result",
        execution_key="chat-message:run-1:assistant",
    )
    repeated = storage.add_message(
        "conv-idempotent",
        "assistant",
        "would be duplicated",
        execution_key="chat-message:run-1:assistant",
    )

    messages = storage.get_messages("conv-idempotent")
    assert repeated == first
    assert len(messages) == 1
    assert messages[0]["content"] == "first result"
