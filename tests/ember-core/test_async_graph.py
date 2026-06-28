"""Tests for async StateGraph support — ainvoke, astream, and ChatCore migration demo."""

import asyncio
import pytest
from pydantic import BaseModel, Field
from ember_core.graph import StateGraph, AppendReducer


class ChatState(BaseModel):
    """Demo: ChatCore pipeline state."""
    user_input: str = ""
    intent: str = ""  # "greeting" | "question" | "command"
    response: str = ""
    tool_calls: list = Field(default_factory=list, json_schema_extra={"reducer": AppendReducer()})
    tool_loop_count: int = 0


# ── Async node functions ────────────────────────────────────────

async def classify_intent(state: ChatState) -> dict:
    """Simulate async intent classification."""
    await asyncio.sleep(0.01)
    text = state.user_input.lower()
    if any(w in text for w in ("hi", "hello", "hey", "你好")):
        return {"intent": "greeting", "response": "Hello! How can I help?"}
    return {"intent": "question"}


async def call_llm(state: ChatState) -> dict:
    """Simulate async LLM call with possible tool calls."""
    await asyncio.sleep(0.01)
    # First call: return tool_calls. Second call: return text response.
    if state.tool_loop_count == 0:
        return {
            "tool_calls": [{"name": "search", "args": {"q": state.user_input}}],
            "tool_loop_count": state.tool_loop_count + 1,
        }
    return {
        "response": f"Answer to: {state.user_input}",
        "tool_loop_count": state.tool_loop_count + 1,
    }


async def execute_tools(state: ChatState) -> dict:
    """Simulate tool execution."""
    await asyncio.sleep(0.01)
    results = [f"Tool result for: {tc['name']}" for tc in state.tool_calls]
    return {"tool_calls": [{"result": r} for r in results]}


# ── Tests ───────────────────────────────────────────────────────

class TestAsyncGraph:
    def test_ainvoke_linear(self):
        """Basic async invoke with sync node."""
        class S(BaseModel):
            cnt: int = 0

        g = StateGraph(S)
        g.add_node("inc", lambda s: {"cnt": s.cnt + 1})
        g.add_node("inc2", lambda s: {"cnt": s.cnt + 1})
        g.add_edge("inc", "inc2")
        g.set_entry_point("inc")

        result = asyncio.run(g.compile().ainvoke(S()))
        assert result.cnt == 2

    def test_ainvoke_async_node(self):
        """Async node function should work."""

        async def async_inc(s):
            await asyncio.sleep(0.01)
            return {"cnt": s.cnt + 1}

        class S(BaseModel):
            cnt: int = 0

        g = StateGraph(S)
        g.add_node("inc", async_inc)
        g.add_node("inc2", async_inc)
        g.add_edge("inc", "inc2")
        g.set_entry_point("inc")

        result = asyncio.run(g.compile().ainvoke(S()))
        assert result.cnt == 2

    def test_ainvoke_mixed_nodes(self):
        """Mix of sync and async nodes."""

        async def async_inc(s):
            await asyncio.sleep(0.01)
            return {"cnt": s.cnt + 1}

        class S(BaseModel):
            cnt: int = 0

        g = StateGraph(S)
        g.add_node("a", async_inc)          # async
        g.add_node("b", lambda s: {"cnt": s.cnt + 1})  # sync
        g.add_edge("a", "b")
        g.set_entry_point("a")

        result = asyncio.run(g.compile().ainvoke(S()))
        assert result.cnt == 2

    def test_chatcore_demo_full_pipeline(self):
        """Full pipeline: greeting → intent → LLM (normal flow, LLM always called)."""
        g = StateGraph(ChatState)
        g.add_node("intent", classify_intent)
        g.add_node("call_llm", call_llm)
        g.add_edge("intent", "call_llm")  # Always go to LLM
        g.set_entry_point("intent")

        # Greeting → intent classifies, LLM responds (tools may trigger)
        result = asyncio.run(g.compile().ainvoke(ChatState(user_input="hello")))
        assert result.intent == "greeting"

    def test_chatcore_demo_tool_loop(self):
        """Simulate ChatCore pipeline: question → LLM → tools → LLM → response."""
        g = StateGraph(ChatState)
        g.add_node("intent", classify_intent)
        g.add_node("call_llm", call_llm)
        g.add_node("execute_tools", execute_tools)

        # Intent → LLM (direct edge, no greeting shortcut)
        g.add_edge("intent", "call_llm")
        # LLM → tools (if tool_calls returned on first pass) or finish
        def llm_router(s):
            # After tools, the LLM is called again. If it produces a response text,
            # tool_loop_count will be 2 (incremented twice). Finish then.
            if s.tool_loop_count == 1:
                return "execute_tools"
            return "__finish__"

        g.add_conditional_edge(
            "call_llm", llm_router,
            {"execute_tools": "execute_tools", "__finish__": "__finish__"},
        )
        # Tools → always loop back to LLM
        g.add_edge("execute_tools", "call_llm")
        g.set_entry_point("intent")

        result = asyncio.run(g.compile().ainvoke(ChatState(user_input="what is pi?")))
        assert result.intent == "question"
        assert "Answer to:" in result.response
        assert result.tool_loop_count == 2  # LLM called twice (tools + text)

    def test_astream(self):
        """Async stream should yield updates."""

        async def node_a(s):
            await asyncio.sleep(0.01)
            return {"cnt": s.cnt + 1}

        class S(BaseModel):
            cnt: int = 0

        g = StateGraph(S)
        g.add_node("a", node_a)
        g.add_node("b", node_a)
        g.add_edge("a", "b")
        g.set_entry_point("a")

        async def collect():
            updates = []
            async for u in g.compile().astream(S()):
                updates.append(u)
            return updates

        updates = asyncio.run(collect())
        assert len(updates) == 2
        assert updates[0].node_name == "a"
        assert updates[1].node_name == "b"
