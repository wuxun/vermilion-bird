"""Tests for ember-core graph module — StateGraph, Checkpointer, Reducers."""

import pytest
from pydantic import BaseModel, Field
from ember_core.graph import (
    StateGraph, AppendReducer, MergeReducer, ReplaceReducer,
    MemoryCheckpointer, SQLiteCheckpointer,
)
from ember_core.storage import SQLiteStore
import tempfile, os


# ── Test state models ──────────────────────────────────────────

class CounterState(BaseModel):
    count: int = 0


class MessageState(BaseModel):
    messages: list = Field(default_factory=list, json_schema_extra={"reducer": AppendReducer()})
    data: dict = Field(default_factory=dict, json_schema_extra={"reducer": MergeReducer()})
    flag: bool = False


class LoopState(BaseModel):
    msgs: list = Field(default_factory=list, json_schema_extra={"reducer": AppendReducer()})
    cnt: int = 0


# ── StateGraph tests ───────────────────────────────────────────

class TestStateGraph:
    """Basic graph construction and execution."""

    def test_simple_linear(self):
        def inc(state: CounterState) -> dict:
            return {"count": state.count + 1}

        g = StateGraph(CounterState)
        g.add_node("a", inc)
        g.add_node("b", inc)
        g.add_edge("a", "b")
        g.set_entry_point("a")

        result = g.compile().invoke(CounterState(count=0))
        assert result.count == 2

    def test_conditional_loop(self):
        graph = StateGraph(LoopState)
        graph.add_node("step", lambda s: {"msgs": [f"s{s.cnt+1}"], "cnt": s.cnt + 1})
        graph.add_node("check", lambda s: {})
        graph.add_conditional_edge(
            "check",
            lambda s: "step" if s.cnt < 5 else "__finish__",
            {"step": "step", "__finish__": "__finish__"},
        )
        graph.add_edge("step", "check")
        graph.set_entry_point("step")

        result = graph.compile().invoke(LoopState())
        assert result.cnt == 5
        assert len(result.msgs) == 5
        assert result.msgs[0] == "s1"
        assert result.msgs[4] == "s5"

    def test_stream(self):
        graph = StateGraph(LoopState)
        graph.add_node("step", lambda s: {"msgs": [f"s{s.cnt+1}"], "cnt": s.cnt + 1})
        graph.add_node("check", lambda s: {})
        graph.add_conditional_edge(
            "check",
            lambda s: "step" if s.cnt < 3 else "__finish__",
            {"step": "step", "__finish__": "__finish__"},
        )
        graph.add_edge("step", "check")
        graph.set_entry_point("step")

        updates = list(graph.compile().stream(LoopState()))
        assert len(updates) == 6  # 3 step + 3 check
        assert updates[0].node_name == "step"
        assert updates[0].step == 1
        assert updates[-1].node_name == "check"
        assert not updates[-1].interrupt

    def test_append_reducer(self):
        graph = StateGraph(LoopState)
        graph.add_node("a", lambda s: {"msgs": ["hello"]})
        graph.add_node("b", lambda s: {"msgs": ["world"]})
        graph.add_edge("a", "b")
        graph.set_entry_point("a")

        result = graph.compile().invoke(LoopState())
        assert result.msgs == ["hello", "world"]

    def test_merge_reducer(self):
        graph = StateGraph(MessageState)
        graph.add_node("a", lambda s: {"data": {"x": 1}})
        graph.add_node("b", lambda s: {"data": {"y": 2}})
        graph.add_edge("a", "b")
        graph.set_entry_point("a")

        result = graph.compile().invoke(MessageState())
        assert result.data == {"x": 1, "y": 2}

    def test_reserved_node_name(self):
        g = StateGraph(CounterState)
        with pytest.raises(ValueError):
            g.add_node("__finish__", lambda s: s)

    def test_missing_entry_point(self):
        g = StateGraph(CounterState)
        g.add_node("a", lambda s: s)
        with pytest.raises(ValueError, match="No entry point"):
            g.compile()

    def test_node_returns_full_state(self):
        def replace(state: CounterState) -> CounterState:
            return CounterState(count=99)

        g = StateGraph(CounterState)
        g.add_node("a", replace)
        g.set_entry_point("a")

        result = g.compile().invoke(CounterState(count=1))
        assert result.count == 99


# ── Interrupt / Resume tests ───────────────────────────────────

class TestInterrupt:
    def test_interrupt_after(self):
        graph = StateGraph(LoopState)
        graph.add_node("step", lambda s: {"msgs": [f"s{s.cnt+1}"], "cnt": s.cnt + 1})
        graph.add_node("check", lambda s: {})
        graph.add_conditional_edge(
            "check",
            lambda s: "step" if s.cnt < 5 else "__finish__",
            {"step": "step", "__finish__": "__finish__"},
        )
        graph.add_edge("step", "check")
        graph.set_entry_point("step")

        compiled = graph.compile(interrupt_after=["step"])
        partial = compiled.invoke(LoopState(), thread_id="t1")
        assert partial.cnt == 1  # halted after first step

        final = compiled.resume("t1")
        assert final.cnt == 5  # ran to completion

    def test_interrupt_before(self):
        graph = StateGraph(LoopState)
        graph.add_node("step", lambda s: {"msgs": [f"s{s.cnt+1}"], "cnt": s.cnt + 1})
        graph.add_node("check", lambda s: {})
        graph.add_conditional_edge(
            "check",
            lambda s: "step" if s.cnt < 3 else "__finish__",
            {"step": "step", "__finish__": "__finish__"},
        )
        graph.add_edge("step", "check")
        graph.set_entry_point("step")

        compiled = graph.compile(interrupt_before=["check"])
        partial = compiled.invoke(LoopState(), thread_id="t2")
        assert partial.cnt == 1  # halted before check

        final = compiled.resume("t2")
        assert final.cnt == 3

    def test_resume_nonexistent(self):
        g = StateGraph(CounterState)
        g.add_node("a", lambda s: {"count": s.count + 1})
        g.set_entry_point("a")
        compiled = g.compile(interrupt_after=["a"])
        result = compiled.resume("no-such-thread")
        assert result is None

    def test_stream_interrupt(self):
        graph = StateGraph(LoopState)
        graph.add_node("step", lambda s: {"msgs": [f"s{s.cnt+1}"], "cnt": s.cnt + 1})
        graph.add_node("check", lambda s: {})
        graph.add_conditional_edge(
            "check",
            lambda s: "step" if s.cnt < 3 else "__finish__",
            {"step": "step", "__finish__": "__finish__"},
        )
        graph.add_edge("step", "check")
        graph.set_entry_point("step")

        compiled = graph.compile(interrupt_after=["step"])
        updates = list(compiled.stream(LoopState()))
        assert len(updates) == 1  # halted after first step
        assert updates[0].interrupt


# ── Checkpointer tests ─────────────────────────────────────────

class TestCheckpointer:
    def test_memory_checkpointer(self):
        ckpt = MemoryCheckpointer()
        ckpt.save("t1", 1, "node_a", {"count": 5})
        loaded = ckpt.load("t1")
        assert loaded == (1, "node_a", {"count": 5})
        ckpt.delete("t1")
        assert ckpt.load("t1") is None

    def test_sqlite_checkpointer(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.db")
            store = SQLiteStore(path)
            ckpt = SQLiteCheckpointer(store)
            ckpt.save("t1", 3, "node_b", {"count": 10})
            loaded = ckpt.load("t1")
            assert loaded == (3, "node_b", {"count": 10})
            ckpt.delete("t1")
            assert ckpt.load("t1") is None


# ── Reducer tests ──────────────────────────────────────────────

class TestReducers:
    def test_replace(self):
        r = ReplaceReducer()
        assert r.apply(1, 2) == 2
        assert r.apply("old", "new") == "new"

    def test_append_list(self):
        r = AppendReducer()
        assert r.apply([1], [2, 3]) == [1, 2, 3]
        assert r.apply(None, [1]) == [1]
        assert r.apply([1], "x") == [1, "x"]

    def test_merge_dict(self):
        r = MergeReducer()
        assert r.apply({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
        assert r.apply({"a": {"x": 1}}, {"a": {"y": 2}}) == {"a": {"x": 1, "y": 2}}
        assert r.apply(None, {"a": 1}) == {"a": 1}
