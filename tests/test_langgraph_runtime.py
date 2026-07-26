from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from llm_chat.runtime import LangGraphRuntime


class ApprovalState(TypedDict, total=False):
    request: str
    draft: str
    approved: bool
    result: str


def build_approval_graph():
    builder = StateGraph(ApprovalState)

    def prepare(state):
        return {"draft": f"prepared:{state['request']}"}

    def approve(state):
        approved = interrupt(
            {
                "kind": "approval",
                "draft": state["draft"],
            }
        )
        return {"approved": bool(approved)}

    def execute(state):
        return {
            "result": "executed" if state["approved"] else "rejected",
        }

    builder.add_node("prepare", prepare)
    builder.add_node("approve", approve)
    builder.add_node("execute", execute)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "approve")
    builder.add_edge("approve", "execute")
    builder.add_edge("execute", END)
    return builder


def test_langgraph_runtime_persists_interrupt_and_resumes_after_restart(tmp_path):
    db_path = str(tmp_path / "langgraph.db")
    first = LangGraphRuntime(db_path)
    first.register_builder("approval", build_approval_graph())

    interrupted = first.invoke(
        "approval",
        thread_id="run-1",
        inputs={"request": "write report"},
    )

    assert interrupted.interrupted is True
    assert interrupted.values["draft"] == "prepared:write report"
    assert interrupted.interrupts[0].value["kind"] == "approval"
    checkpoint_id = interrupted.snapshot.checkpoint_id
    first.close()

    second = LangGraphRuntime(db_path)
    second.register_builder("approval", build_approval_graph())
    restored = second.get_state("approval", thread_id="run-1")

    assert restored is not None
    assert restored.checkpoint_id == checkpoint_id
    assert restored.next_nodes == ("approve",)

    completed = second.resume(
        "approval",
        thread_id="run-1",
        value=True,
    )

    assert completed.completed is True
    assert completed.values["approved"] is True
    assert completed.values["result"] == "executed"
    assert len(second.get_history("approval", thread_id="run-1")) >= 3
    second.close()


def test_langgraph_runtime_rejects_unknown_graph_and_duplicate_registration(
    tmp_path,
):
    runtime = LangGraphRuntime(str(tmp_path / "langgraph.db"))
    runtime.register_builder("approval", build_approval_graph())

    try:
        runtime.register_builder("approval", build_approval_graph())
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("duplicate graph registration was accepted")

    try:
        runtime.get_state("missing", thread_id="run")
    except KeyError as exc:
        assert "Unknown graph" in str(exc)
    else:
        raise AssertionError("unknown graph lookup was accepted")
    runtime.close()
