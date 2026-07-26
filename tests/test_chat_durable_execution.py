"""Chat graph SQLite checkpoint and recovery regressions."""

from llm_chat.chat_core_graph import ChatCoreGraph
from llm_chat.config import Config
from llm_chat.runtime import (
    ActionProposalManager,
    LangGraphRuntime,
    RunManager,
    RunStatus,
    RunType,
)
from llm_chat.storage import Storage


class RecoveringClient:
    def __init__(self, *, fail: bool):
        self.fail = fail

    def has_builtin_tools(self):
        return False

    def get_builtin_tools(self):
        return []

    def chat(self, *_args, **_kwargs):
        if self.fail:
            raise RuntimeError("transient")
        return "recovered"


class EmptyConversation:
    def add_user_message(self, *_args, **_kwargs):
        pass

    def add_assistant_message(self, *_args, **_kwargs):
        pass

    def get_messages(self, *_args, **_kwargs):
        return []

    def get_history(self, *_args, **_kwargs):
        return []


class EmptyConversationManager:
    memory_manager = None
    knowledge_manager = None

    def __init__(self):
        self.conversation = EmptyConversation()

    def get_conversation(self, *_args, **_kwargs):
        return self.conversation

    def get_or_create_conversation(self, *_args, **_kwargs):
        return self.conversation

    def search_similar(self, *_args, **_kwargs):
        return []

    def search_messages(self, *_args, **_kwargs):
        return []


def _build_core(db_path, storage, client):
    runs = RunManager(repository=storage)
    runtime = LangGraphRuntime(str(db_path))
    core = ChatCoreGraph(
        client,
        EmptyConversationManager(),
        Config(enable_tools=False),
        run_manager=runs,
        action_proposals=ActionProposalManager(repository=storage),
        graph_runtime=runtime,
    )
    return runs, runtime, core


def test_failed_chat_retries_from_sqlite_checkpoint_after_restart(tmp_path):
    db_path = tmp_path / "chat-recovery.db"
    Storage.set_instance(None)
    storage = Storage(str(db_path))

    first_runs, first_runtime, first = _build_core(
        db_path,
        storage,
        RecoveringClient(fail=True),
    )
    first.send_message("conv", "hello")
    failed = first_runs.list()[0]

    assert failed.status == RunStatus.FAILED
    assert failed.checkpoint is not None
    assert failed.checkpoint.cursor == "llm_call"
    assert failed.checkpoint.state["schema_version"] == 1
    first_runtime.close()

    restored_runs, restored_runtime, restored = _build_core(
        db_path,
        storage,
        RecoveringClient(fail=False),
    )
    completed = restored.retry(failed.id)

    assert completed.status == RunStatus.COMPLETED
    assert completed.result == "recovered"
    assert completed.attempt == 2
    assert restored_runtime.get_state("chat", thread_id=failed.id).checkpoint_id

    restored_runtime.close()
    Storage.set_instance(None)


def test_chat_run_keeps_product_work_item_identity(tmp_path):
    db_path = tmp_path / "chat-work-item.db"
    Storage.set_instance(None)
    storage = Storage(str(db_path))
    runs, runtime, core = _build_core(
        db_path,
        storage,
        RecoveringClient(fail=False),
    )

    result = core.send_message(
        "conv",
        "hello",
        work_item_id="work_product_task",
        run_type=RunType.WORKFLOW,
    )
    run = runs.list()[0]

    assert result == "recovered"
    assert run.work_item_id == "work_product_task"
    assert run.type == RunType.WORKFLOW

    runtime.close()
    Storage.set_instance(None)
