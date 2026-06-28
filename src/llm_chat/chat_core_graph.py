"""ChatCoreGraph — ChatCore pipeline using ember StateGraph.

Replaces the linear PipelineRunner with a StateGraph that supports:
    - Conditional routing: greeting → skip LLM, tool calls → loop
    - Async execution via compiled.ainvoke()
    - Interrupt points for human-in-the-loop (future)

Usage:
    # Drop-in replacement for ChatCore:
    core = ChatCoreGraph(client, conversation_manager, config)
    response = core.send_message(conversation_id, "hello")
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from ember_core.graph import StateGraph, AppendReducer
from ember_agent.consensus import init_card_context, get_pending_card, clear_card_context

from llm_chat.config import Config
from llm_chat.client import LLMClient
from llm_chat.conversation import ConversationManager
from llm_chat.pipeline.chat_state import ChatRoutingState
from llm_chat.pipeline.stage import PipelineContext
from llm_chat.pipeline.stages import (
    IntentStage, ShortcutStage,
    PersistUserStage, SystemContextStage, HistoryStage,
    PersistAssistantStage, MemoryExtractStage, KnowledgeExtractStage,
    TokenRecordStage,
)
from llm_chat.pipeline import MutableStrHolder
from llm_chat.utils.observability import observe

logger = logging.getLogger(__name__)

StreamCallback = Callable[[str], None]
ToolCallStartCallback = Callable[[str, str], None]
ToolCallEndCallback = Callable[[str, str, str], None]
CardCallback = Callable[[Any], None]


# ── Graph state ───────────────────────────────────────────────────


class ChatGraphState(BaseModel):
    """State flowing through the ChatCore StateGraph.

    routing:  Minimal routing state for conditional edges.
    ctx:      Full PipelineContext (carried alongside for stage compatibility).
    """

    routing: ChatRoutingState = Field(default_factory=ChatRoutingState)
    # PipelineContext is carried as a non-Pydantic field via model_config
    # (it contains non-serializable objects like threading.Event, callbacks)
    _ctx: Optional[PipelineContext] = None

    model_config = {"arbitrary_types_allowed": True}


# ── Node functions ────────────────────────────────────────────────


async def _intent_node(state: ChatGraphState) -> dict:
    """Intent classification node."""
    from llm_chat.intent import IntentClassifier
    classifier = state._ctx._extra.get("intent_classifier")
    decision = classifier.classify(state._ctx.user_message)
    state._ctx.routing_decision = decision
    if decision.override_message:
        state._ctx.effective_message = decision.override_message

    return {
        "routing": ChatRoutingState(
            intent=decision.intent.value,
            skip_llm=decision.skip_llm,
        ),
    }


async def _shortcut_node(state: ChatGraphState) -> dict:
    """Shortcut handling node."""
    cm = state._ctx._extra.get("conversation_manager")
    style_holder = state._ctx._extra.get("style_holder")
    stage = ShortcutStage(cm, style_holder)
    await stage.setup(state._ctx)
    await stage.process(state._ctx)
    await stage.teardown(state._ctx)

    return {
        "routing": ChatRoutingState(
            should_short_circuit=state._ctx.should_short_circuit,
            skip_llm=state._ctx.routing_decision.skip_llm if state._ctx.routing_decision else False,
        ),
    }


async def _persist_user_node(state: ChatGraphState) -> dict:
    """Persist user message to storage."""
    cm = state._ctx._extra.get("conversation_manager")
    stage = PersistUserStage(cm)
    await stage.setup(state._ctx)
    await stage.process(state._ctx)
    await stage.teardown(state._ctx)
    return {}


async def _system_context_node(state: ChatGraphState) -> dict:
    """Build system context (memory + prompts + style)."""
    cm = state._ctx._extra.get("conversation_manager")
    prompt_holder = state._ctx._extra.get("prompt_skills_holder")
    style_holder = state._ctx._extra.get("style_holder")
    stage = SystemContextStage(cm, prompt_holder, style_holder)
    await stage.setup(state._ctx)
    await stage.process(state._ctx)
    await stage.teardown(state._ctx)
    return {}


async def _history_node(state: ChatGraphState) -> dict:
    """Load and process conversation history."""
    cm = state._ctx._extra.get("conversation_manager")
    stage = HistoryStage(cm)
    await stage.setup(state._ctx)
    await stage.process(state._ctx)
    await stage.teardown(state._ctx)
    return {}


async def _model_route_node(state: ChatGraphState) -> dict:
    """Route to appropriate model based on intent."""
    config = state._ctx._extra.get("config")
    stage = ModelRouteStage(config)
    await stage.setup(state._ctx)
    await stage.process(state._ctx)
    await stage.teardown(state._ctx)
    return {}


async def _compress_node(state: ChatGraphState) -> dict:
    """Compress conversation context if needed."""
    cm = state._ctx._extra.get("conversation_manager")
    stage = CompressStage(cm)
    await stage.setup(state._ctx)
    await stage.process(state._ctx)
    await stage.teardown(state._ctx)
    return {}


async def _llm_call_node(state: ChatGraphState) -> dict:
    """Call LLM with tool support (single iteration — no internal loop).

    Uses client.chat_single_with_tools() which makes one LLM call and returns
    raw result with tool_calls if present. The graph handles the loop.
    """
    client = state._ctx._extra.get("client")
    config = state._ctx._extra.get("config")

    # Card context
    init_card_context()

    # Build messages — first call or re-entrant after tool execution
    if state._ctx._extra.get("_tool_messages"):
        messages_override = state._ctx._extra["_tool_messages"]
        result = client.chat_single_with_tools(
            "", [], messages_override=messages_override,
            **state._ctx.params,
        )
    else:
        result = client.chat_single_with_tools(
            state._ctx.processed_message,
            client.get_builtin_tools() if client.has_builtin_tools() else [],
            history=state._ctx.processed_history,
            system_context=state._ctx.system_context,
            **state._ctx.params,
        )

    # Handle card
    state._ctx.pending_card = get_pending_card()
    clear_card_context()

    tool_calls = result.get("tool_calls")
    if tool_calls:
        # Store for tool execution node
        state._ctx._extra["_pending_tool_calls"] = tool_calls
        if "assistant_message" in result:
            state._ctx._extra["_tool_messages"] = (
                state._ctx._extra.get("_tool_messages", []) +
                [result["assistant_message"]]
            )
        return {
            "routing": ChatRoutingState(
                has_tool_calls=True,
                tool_call_count=state.routing.tool_call_count + 1,
            ),
        }
    else:
        # Text response
        state._ctx.response = result.get("text", "")
        state._ctx._extra.pop("_tool_messages", None)
        return {
            "routing": ChatRoutingState(has_response=True),
        }


async def _execute_tools_node(state: ChatGraphState) -> dict:
    """Execute pending tool calls and append results to messages."""
    from llm_chat.tools import get_tool_registry

    registry = get_tool_registry()
    tool_calls = state._ctx._extra.get("_pending_tool_calls", [])

    # Build tool call dicts in the format ToolExecutor expects
    tool_call_dicts = []
    for tc in tool_calls:
        tc_id = tc.id if hasattr(tc, 'id') else f"tc_{tc.name}"
        args = tc.arguments if isinstance(tc.arguments, dict) else {}
        tool_call_dicts.append({
            "id": tc_id,
            "function": {"name": tc.name, "arguments": json.dumps(args)},
        })

    # Execute tools via ToolExecutor (handles parallel execution + retry)
    results = registry.execute_tools_parallel(tool_call_dicts) if hasattr(registry, 'execute_tools_parallel') else []

    # Append tool results to messages for re-entrant LLM call
    for tc, result in zip(tool_calls, results):
        tc_id = tc.id if hasattr(tc, 'id') else f"tc_{tc.name}"
        state._ctx._extra.setdefault("_tool_messages", []).append({
            "role": "tool",
            "tool_call_id": tc_id,
            "content": result.get("content", ""),
        })

    state._ctx._extra.pop("_pending_tool_calls", None)

    return {
        "routing": ChatRoutingState(has_tool_calls=False),
    }



async def _persist_assistant_node(state: ChatGraphState) -> dict:
    """Persist assistant response to storage."""
    cm = state._ctx._extra.get("conversation_manager")
    stage = PersistAssistantStage(cm)
    await stage.setup(state._ctx)
    await stage.process(state._ctx)
    await stage.teardown(state._ctx)
    return {}


async def _memory_extract_node(state: ChatGraphState) -> dict:
    """Extract memories from conversation."""
    cm = state._ctx._extra.get("conversation_manager")
    stage = MemoryExtractStage(cm)
    await stage.setup(state._ctx)
    await stage.process(state._ctx)
    await stage.teardown(state._ctx)
    return {}


async def _knowledge_extract_node(state: ChatGraphState) -> dict:
    """Extract knowledge from conversation."""
    cm = state._ctx._extra.get("conversation_manager")
    stage = KnowledgeExtractStage(cm)
    await stage.setup(state._ctx)
    await stage.process(state._ctx)
    await stage.teardown(state._ctx)
    return {}


async def _token_record_node(state: ChatGraphState) -> dict:
    """Record token usage."""
    config = state._ctx._extra.get("config")
    stage = TokenRecordStage(config)
    await stage.setup(state._ctx)
    await stage.process(state._ctx)
    await stage.teardown(state._ctx)
    return {}


# ── Router functions ─────────────────────────────────────────────


def _post_shortcut_router(state: ChatGraphState) -> str:
    """After shortcut: route based on short_circuit flag.

    should_short_circuit = True: shortcut handled the request (e.g. /style, /help).
    response is already set → skip to persist_assistant.

    Otherwise: proceed through the full pipeline (greetings go through LLM normally).
    """
    if state.routing.should_short_circuit:
        return "persist_assistant"
    return "persist_user"


def _post_llm_router(state: ChatGraphState) -> str:
    """After LLM call: route to tool execution or persist."""
    if state.routing.needs_tool_execution():
        return "execute_tools"
    return "persist_assistant"


# ── Graph construction ───────────────────────────────────────────


def build_chat_graph() -> StateGraph[ChatGraphState]:
    """Build the ChatCore StateGraph with conditional routing.

    Topology:
        intent → shortcut
            ├─ greeting/short_circuit? → skip to persist_assistant (or finish)
            └─ normal → persist_user → system_context → history
                → model_route → compress → llm_call
                    ├─ tool_calls? → loop llm_call
                    └─ text response → persist_assistant
                        → memory_extract → knowledge_extract → token_record → finish
    """
    g = StateGraph(ChatGraphState)

    # Register all nodes
    g.add_node("intent", _intent_node)
    g.add_node("shortcut", _shortcut_node)
    g.add_node("persist_user", _persist_user_node)
    g.add_node("system_context", _system_context_node)
    g.add_node("history", _history_node)
    g.add_node("model_route", _model_route_node)
    g.add_node("compress", _compress_node)
    g.add_node("llm_call", _llm_call_node)
    g.add_node("execute_tools", _execute_tools_node)
    g.add_node("persist_assistant", _persist_assistant_node)
    g.add_node("memory_extract", _memory_extract_node)
    g.add_node("knowledge_extract", _knowledge_extract_node)
    g.add_node("token_record", _token_record_node)

    # Entry
    g.set_entry_point("intent")

    # Linear edges for the main path
    g.add_edge("intent", "shortcut")

    # Conditional: shortcut may skip the rest
    g.add_conditional_edge(
        "shortcut", _post_shortcut_router,
        {
            "persist_user": "persist_user",
            "persist_assistant": "persist_assistant",
            "__finish__": "__finish__",
        },
    )

    g.add_edge("persist_user", "system_context")
    g.add_edge("system_context", "history")
    g.add_edge("history", "model_route")
    g.add_edge("model_route", "compress")
    g.add_edge("compress", "llm_call")

    # Conditional: LLM may have tool calls → loop, or proceed
    g.add_conditional_edge(
        "llm_call", _post_llm_router,
        {
            "execute_tools": "execute_tools",
            "persist_assistant": "persist_assistant",
        },
    )
    # After tool execution, always go back to LLM
    g.add_edge("execute_tools", "llm_call")

    g.add_edge("persist_assistant", "memory_extract")
    g.add_edge("memory_extract", "knowledge_extract")
    g.add_edge("knowledge_extract", "token_record")
    g.add_edge("token_record", "__finish__")

    return g


# ── ChatCoreGraph — drop-in replacement for ChatCore ─────────────


class ChatCoreGraph:
    """ChatCore using StateGraph for conditional routing.

    Drop-in replacement for ChatCore. Same public API.
    """

    def __init__(
        self,
        client: LLMClient,
        conversation_manager: ConversationManager,
        config: Config,
    ):
        self.client = client
        self.conversation_manager = conversation_manager
        self.config = config
        self._cancel_event: Optional[threading.Event] = None
        self._prompt_skills_holder = MutableStrHolder("")
        self._style_holder = MutableStrHolder("default")

        from llm_chat.intent import IntentClassifier
        self.intent_classifier = IntentClassifier(
            enable_layer1=config.tools.enable_intent
            if hasattr(config.tools, 'enable_intent') else True
        )

        self._graph = build_chat_graph()
        self._compiled = self._graph.compile()
        logger.info("ChatCoreGraph initialized (StateGraph, 12 nodes)")

    # ── Public API ────────────────────────────────────────────

    @observe("chat_core.send_message")
    def send_message(
        self,
        conversation_id: str,
        message: str,
        on_card: Optional[CardCallback] = None,
        **model_params,
    ) -> str:
        """Synchronous send_message — uses async graph internally."""
        ctx = PipelineContext(
            conversation_id=conversation_id,
            user_message=message,
            on_card=on_card,
            params=model_params,
        )
        # Attach extras for node functions
        ctx._extra = {
            "intent_classifier": self.intent_classifier,
            "conversation_manager": self.conversation_manager,
            "prompt_skills_holder": self._prompt_skills_holder,
            "style_holder": self._style_holder,
            "client": self.client,
            "config": self.config,
        }

        state = ChatGraphState(_ctx=ctx)

        try:
            result_state = asyncio.run(self._compiled.ainvoke(state))
        except Exception as e:
            logger.error(f"send_message graph failed: {e}", exc_info=True)
            return f"处理消息时发生错误: {str(e)}"

        # Handle pending card
        card = result_state._ctx.pending_card
        if card and on_card:
            on_card(card)

        return result_state._ctx.response

    @observe("chat_core.send_message_stream")
    def send_message_stream(
        self,
        conversation_id: str,
        message: str,
        on_chunk: Optional[StreamCallback] = None,
        on_tool_start: Optional[ToolCallStartCallback] = None,
        on_tool_end: Optional[ToolCallEndCallback] = None,
        on_context_update: Optional[Callable[[int, int], None]] = None,
        on_card: Optional[CardCallback] = None,
        **model_params,
    ) -> str:
        """Streaming send_message."""
        self._cancel_event = threading.Event()
        ctx = PipelineContext(
            conversation_id=conversation_id,
            user_message=message,
            on_chunk=on_chunk,
            on_tool_start=on_tool_start,
            on_tool_end=on_tool_end,
            on_context_update=on_context_update,
            on_card=on_card,
            cancel_event=self._cancel_event,
            params=model_params,
        )
        ctx._extra = {
            "intent_classifier": self.intent_classifier,
            "conversation_manager": self.conversation_manager,
            "prompt_skills_holder": self._prompt_skills_holder,
            "style_holder": self._style_holder,
            "client": self.client,
            "config": self.config,
        }

        state = ChatGraphState(_ctx=ctx)

        try:
            result_state = asyncio.run(self._compiled.ainvoke(state))
        except Exception as e:
            logger.error(f"send_message_stream graph failed: {e}", exc_info=True)
            return f"处理消息时发生错误: {str(e)}"

        card = result_state._ctx.pending_card
        if card and on_card:
            on_card(card)

        return result_state._ctx.response

    def cancel_generation(self) -> None:
        """Cancel ongoing stream generation."""
        if self._cancel_event:
            self._cancel_event.set()

    # ── Convenience ───────────────────────────────────────────

    def get_system_context(self, conversation_id: str) -> Optional[str]:
        """Get system context for a conversation (for preview)."""
        stage = SystemContextStage(
            self.conversation_manager,
            self._prompt_skills_holder,
            self._style_holder,
        )
        ctx = PipelineContext(
            conversation_id=conversation_id, user_message="", effective_message=""
        )
        asyncio.run(stage.process(ctx))
        return ctx.system_context

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Get all available tools (built-in + MCP)."""
        from llm_chat.tools import get_tool_registry
        registry = get_tool_registry()
        return registry.get_tools_for_openai()
