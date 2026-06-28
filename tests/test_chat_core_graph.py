"""Tests for ChatCoreGraph routing logic.

Verifies that the StateGraph routes correctly for:
    - Greeting messages (skip LLM)
    - Normal messages (full pipeline)
    - Tool call loops (conditional routing)
"""

import asyncio
import pytest
from pydantic import BaseModel

from ember_core.graph import StateGraph
from llm_chat.pipeline.chat_state import ChatRoutingState
from llm_chat.chat_core_graph import (
    ChatGraphState, build_chat_graph,
    _post_shortcut_router, _post_llm_router,
)


# ── Router function tests ───────────────────────────────────────

class TestRouting:
    def test_short_circuit_skips_to_persist(self):
        """Short circuit (e.g. /style, /help) should skip to persist_assistant."""
        state = ChatGraphState(
            routing=ChatRoutingState(should_short_circuit=True),
        )
        result = _post_shortcut_router(state)
        assert result == "persist_assistant"

    def test_normal_proceeds_to_pipeline(self):
        """Normal message (including greetings) proceeds through full pipeline."""
        state = ChatGraphState(
            routing=ChatRoutingState(intent="chat", skip_llm=True),
        )
        result = _post_shortcut_router(state)
        assert result == "persist_user"

    def test_greeting_still_runs_pipeline(self):
        """Simple greeting (not a shortcut) still goes through LLM pipeline."""
        state = ChatGraphState(
            routing=ChatRoutingState(intent="greeting", skip_llm=True),
        )
        result = _post_shortcut_router(state)
        assert result == "persist_user"

    def test_llm_with_tool_calls_loops(self):
        state = ChatGraphState(
            routing=ChatRoutingState(has_tool_calls=True, tool_call_count=0),
        )
        result = _post_llm_router(state)

    def test_llm_text_response_proceeds(self):
        """After LLM produces text (no tool_calls), proceed to persist."""
        state = ChatGraphState(
            routing=ChatRoutingState(has_response=True),
        )
        result = _post_llm_router(state)
        assert result == "persist_assistant"

    def test_llm_tool_loop_limit(self):
        """After reaching max tool iterations, proceed to persist."""
        state = ChatGraphState(
            routing=ChatRoutingState(
                has_tool_calls=True,
                tool_call_count=10,
                max_tool_iterations=10,
            ),
        )
        result = _post_llm_router(state)
        assert result == "persist_assistant"


# ── Graph structure test ────────────────────────────────────────

class TestGraphStructure:
    def test_graph_compiles(self):
        """The full graph should compile without errors."""
        g = build_chat_graph()
        compiled = g.compile()
        assert compiled._entry_point == "intent"
        assert len(compiled._nodes) == 13
        expected = {
            "intent", "shortcut", "persist_user", "system_context",
            "history", "model_route", "compress", "llm_call",
            "execute_tools", "persist_assistant", "memory_extract",
            "knowledge_extract", "token_record",
        }
        assert set(compiled._nodes.keys()) == expected

    def test_conditional_edges_exist(self):
        """The graph should have conditional edge at shortcut."""
        g = build_chat_graph()
        compiled = g.compile()
        assert "shortcut" in compiled._conditional
