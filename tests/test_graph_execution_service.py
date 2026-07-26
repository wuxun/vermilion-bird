from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph

from llm_chat.runtime import (
    GraphExecutionService,
    LangGraphRuntime,
    RunManager,
    RunStatus,
    RunType,
)


class WorkState(TypedDict, total=False):
    value: str
    result: str


def _build_work_graph(operation):
    builder = StateGraph(WorkState)
    builder.add_node("work", operation)
    builder.add_edge(START, "work")
    builder.add_edge("work", END)
    return builder


def test_failed_graph_retries_from_framework_checkpoint(tmp_path):
    attempts = []

    def flaky(state):
        attempts.append(state["value"])
        if len(attempts) == 1:
            raise RuntimeError("transient")
        return {"result": f"done:{state['value']}"}

    runtime = LangGraphRuntime(str(tmp_path / "retry.db"))
    runtime.register_builder("work", _build_work_graph(flaky))
    runs = RunManager()
    service = GraphExecutionService(
        run_manager=runs,
        graph_runtime=runtime,
    )

    failed = service.start(
        "work",
        run_type=RunType.WORKFLOW,
        inputs={"value": "A"},
        max_attempts=2,
    )
    completed = service.retry(failed.id)

    assert failed.status == RunStatus.FAILED
    assert completed.status == RunStatus.COMPLETED
    assert completed.attempt == 2
    assert completed.result["result"] == "done:A"
    assert attempts == ["A", "A"]
    assert completed.checkpoint.state["schema_version"] == 1
    runtime.close()


def test_completed_graph_replay_gets_new_run_and_thread(tmp_path):
    runtime = LangGraphRuntime(str(tmp_path / "replay.db"))
    runtime.register_builder(
        "work",
        _build_work_graph(
            lambda state: {"result": f"done:{state['value']}"},
        ),
    )
    runs = RunManager()
    service = GraphExecutionService(
        run_manager=runs,
        graph_runtime=runtime,
    )
    original = service.start(
        "work",
        run_type=RunType.WORKFLOW,
        inputs={"value": "B"},
    )

    replay = service.replay(original.id)

    assert original.status == RunStatus.COMPLETED
    assert replay.status == RunStatus.COMPLETED
    assert replay.id != original.id
    assert replay.parent_run_id == original.id
    assert replay.metadata["replay_of_run_id"] == original.id
    assert replay.result == original.result
    assert runtime.get_state("work", thread_id=original.id).checkpoint_id
    assert runtime.get_state("work", thread_id=replay.id).checkpoint_id
    runtime.close()
