"""Tests for ChatCoreGraph routing logic.

Verifies that the StateGraph routes correctly for:
    - Greeting messages (skip LLM)
    - Normal messages (full pipeline)
    - Tool call loops (conditional routing)
"""

import asyncio
import pytest
from pydantic import BaseModel
from types import SimpleNamespace
from unittest.mock import MagicMock

from ember_core.graph import StateGraph
from llm_chat.pipeline.chat_state import ChatRoutingState
from llm_chat.chat_core_graph import (
    ChatGraphState,
    build_chat_graph,
    _post_shortcut_router,
    _post_llm_router,
    _llm_call_node,
    _routing_update,
    _set_ctx,
    _clear_ctx,
)
from llm_chat.pipeline.stage import PipelineContext


# ── Router function tests ───────────────────────────────────────


class TestRouting:
    def test_short_circuit_skips_to_persist(self):
        """Shortcuts persist inside ShortcutStage and must not be written twice."""
        state = ChatGraphState(
            routing=ChatRoutingState(should_short_circuit=True),
        )
        result = _post_shortcut_router(state)
        assert result == "__finish__"

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
            routing=ChatRoutingState(has_tool_calls=True, tool_call_count=1),
        )
        result = _post_llm_router(state)
        assert result == "execute_tools"

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

    def test_routing_patch_preserves_tool_budget(self):
        state = ChatGraphState(
            routing=ChatRoutingState(
                tool_call_count=3,
                max_tool_iterations=7,
                has_tool_calls=True,
            )
        )

        updated = _routing_update(state, has_tool_calls=False)

        assert updated.tool_call_count == 3
        assert updated.max_tool_iterations == 7
        assert updated.has_tool_calls is False

    def test_disabled_tools_use_plain_chat(self):
        client = MagicMock()
        client.has_builtin_tools.return_value = True
        client.get_builtin_tools.return_value = [
            {"type": "function", "function": {"name": "unsafe"}}
        ]
        client.chat.return_value = "plain response"
        ctx = PipelineContext(
            conversation_id="conv-disabled",
            user_message="hello",
            processed_message="hello",
        )
        ctx._extra = {
            "client": client,
            "config": SimpleNamespace(enable_tools=False),
        }
        _set_ctx(ctx)
        try:
            update = asyncio.run(_llm_call_node(ChatGraphState()))
        finally:
            _clear_ctx()

        client.chat.assert_called_once()
        client.chat_single_with_tools.assert_not_called()
        assert update["routing"].has_response is True


# ── Graph structure test ────────────────────────────────────────


class TestGraphStructure:
    def test_graph_compiles(self):
        """The full graph should compile without errors."""
        g = build_chat_graph()
        compiled = g.compile()
        graph = compiled.get_graph()
        assert any(edge.source == "__start__" and edge.target == "intent" for edge in graph.edges)
        expected = {
            "intent",
            "shortcut",
            "persist_user",
            "system_context",
            "history",
            "model_route",
            "compress",
            "llm_call",
            "execute_tools",
            "persist_assistant",
            "memory_extract",
            "knowledge_extract",
            "token_record",
        }
        assert set(graph.nodes) - {"__start__", "__end__"} == expected

    def test_conditional_edges_exist(self):
        """The graph should have conditional edge at shortcut."""
        g = build_chat_graph()
        graph = g.compile().get_graph()
        assert any(edge.source == "shortcut" and edge.conditional for edge in graph.edges)
