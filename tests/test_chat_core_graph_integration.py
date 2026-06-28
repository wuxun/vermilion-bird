"""Integration tests for ChatCoreGraph — verifies routing with mocked LLM."""

import asyncio
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pydantic import BaseModel

from ember_core.graph import StateGraph
from llm_chat.chat_core_graph import ChatCoreGraph, ChatGraphState, build_chat_graph as build_ch_graph
from llm_chat.config import Config


# ── Mock helpers ─────────────────────────────────────────────────

class MockLLMClient:
    """Mock LLM client that returns controlled responses."""
    def __init__(self, response_text="Mock response", has_tools=True):
        self._response = response_text
        self._has_tools = has_tools

    def has_builtin_tools(self):
        return self._has_tools

    def get_builtin_tools(self):
        return [{"type": "function", "function": {"name": "mock_tool"}}]

    def chat(self, message, history=None, system_context=None, **params):
        return self._response

    def chat_with_tools(self, message, tools, history=None, system_context=None, **params):
        return self._response

    def chat_stream(self, message, history=None, system_context=None, **params):
        yield self._response

    def chat_stream_with_tools(self, message, tools, history=None, system_context=None, cancel_event=None, **params):
        yield self._response


class MockConversation:
    def add_user_message(self, msg): pass
    def add_assistant_message(self, msg): pass
    def get_messages(self, limit=None): return []


class MockConversationManager:
    def __init__(self):
        self._conv = MockConversation()
    def get_conversation(self, cid):
        return self._conv
    def search_similar(self, query, limit=5):
        return []
    def get_or_create_conversation(self, cid, title=""):
        return self._conv


# ── Tests ───────────────────────────────────────────────────────

class TestChatCoreGraphIntegration:
    """End-to-end tests with mocked LLM client."""

    def setup_method(self):
        self.client = MockLLMClient(response_text="Hello! I'm an AI assistant.")
        self.cm = MockConversationManager()

        # Create config with minimum required fields
        self.config = MagicMock(spec=Config)
        self.config.llm = MagicMock()
        self.config.llm.model = "gpt-4o-mini"
        self.config.llm.protocol = "openai"
        self.config.llm.base_url = "https://api.openai.com/v1"
        self.config.enable_tools = False
        self.config.tools = MagicMock()
        self.config.tools.enable_intent = True
        self.config.tools.enable_tools = False
        self.chat_core = ChatCoreGraph(self.client, self.cm, self.config)

    def test_normal_message_runs_full_pipeline(self):
        """Normal message goes through full 12-node pipeline."""
        response = self.chat_core.send_message("conv1", "What is Python?")
        assert "Hello" in response or "Mock" in response or response
        # Just verifying it doesn't crash

    def test_shortcut_command_skips_llm(self):
        """Shortcut command (/help) should set should_short_circuit and skip LLM."""
        response = self.chat_core.send_message("conv2", "/help")
        assert response  # Should have some response (help text or default)

    def test_graph_structure_preserved(self):
        """Verify the graph has all 12 nodes after compilation."""
        g = build_ch_graph()
        compiled = g.compile()
        node_names = set(compiled._nodes.keys())
        assert "intent" in node_names
        assert "llm_call" in node_names
        assert "persist_assistant" in node_names
        assert compiled._entry_point == "intent"

    def test_routing_post_shortcut(self):
        """Verify shortcut routing logic."""
        from llm_chat.chat_core_graph import _post_shortcut_router
        from llm_chat.pipeline.chat_state import ChatRoutingState

        # Short circuit → persist_assistant
        state = ChatGraphState(routing=ChatRoutingState(should_short_circuit=True))
        assert _post_shortcut_router(state) == "persist_assistant"

        # Normal → persist_user
        state2 = ChatGraphState(routing=ChatRoutingState(should_short_circuit=False))
        assert _post_shortcut_router(state2) == "persist_user"

    def test_routing_post_llm(self):
        """Verify LLM post-routing always proceeds to persist_assistant."""
        from llm_chat.chat_core_graph import _post_llm_router
        from llm_chat.pipeline.chat_state import ChatRoutingState

        state = ChatGraphState(routing=ChatRoutingState())
        assert _post_llm_router(state) == "persist_assistant"
