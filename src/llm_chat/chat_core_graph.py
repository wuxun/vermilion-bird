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
    ModelRouteStage, CompressStage,
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
    """

    routing: ChatRoutingState = Field(default_factory=ChatRoutingState)

    model_config = {"arbitrary_types_allowed": True}


# PipelineContext is stored in thread-local storage because it contains
# non-serializable objects (threading.Event, callbacks) and cannot be part
# of the Pydantic state that gets reconstructed during graph state merges.
# Thread-local ensures isolation when multiple requests run concurrently
# (e.g., scheduler + user message in parallel).
import threading
_chat_ctx_local = threading.local()


def _ctx() -> PipelineContext:
    """Get the current PipelineContext. Raises if not set."""
    ctx = getattr(_chat_ctx_local, 'ctx', None)
    assert ctx is not None, "PipelineContext not initialized"
    return ctx


def _set_ctx(ctx: PipelineContext) -> None:
    _chat_ctx_local.ctx = ctx


# ── Node functions ────────────────────────────────────────────────


async def _intent_node(state: ChatGraphState) -> dict:
    """Intent classification node."""
    from llm_chat.intent import IntentClassifier
    classifier = _ctx()._extra.get("intent_classifier")
    decision = classifier.classify(_ctx().user_message)
    _ctx().routing_decision = decision
    if decision.override_message:
        _ctx().effective_message = decision.override_message

    return {
        "routing": ChatRoutingState(
            intent=decision.intent.value,
            skip_llm=decision.skip_llm,
        ),
    }


async def _shortcut_node(state: ChatGraphState) -> dict:
    """Shortcut handling node."""
    cm = _ctx()._extra.get("conversation_manager")
    style_holder = _ctx()._extra.get("style_holder")
    stage = ShortcutStage(cm, style_holder)
    await stage.setup(_ctx())
    await stage.process(_ctx())
    await stage.teardown(_ctx())

    return {
        "routing": ChatRoutingState(
            should_short_circuit=_ctx().should_short_circuit,
            skip_llm=_ctx().routing_decision.skip_llm if _ctx().routing_decision else False,
        ),
    }


async def _persist_user_node(state: ChatGraphState) -> dict:
    """Persist user message to storage."""
    cm = _ctx()._extra.get("conversation_manager")
    stage = PersistUserStage(cm)
    await stage.setup(_ctx())
    await stage.process(_ctx())
    await stage.teardown(_ctx())
    return {}


async def _system_context_node(state: ChatGraphState) -> dict:
    """Build system context (memory + prompts + style)."""
    cm = _ctx()._extra.get("conversation_manager")
    prompt_holder = _ctx()._extra.get("prompt_skills_holder")
    style_holder = _ctx()._extra.get("style_holder")
    stage = SystemContextStage(cm, prompt_holder, style_holder)
    await stage.setup(_ctx())
    await stage.process(_ctx())
    await stage.teardown(_ctx())
    return {}


async def _history_node(state: ChatGraphState) -> dict:
    """Load and process conversation history."""
    cm = _ctx()._extra.get("conversation_manager")
    stage = HistoryStage(cm)
    await stage.setup(_ctx())
    await stage.process(_ctx())
    await stage.teardown(_ctx())
    return {}


async def _model_route_node(state: ChatGraphState) -> dict:
    """Route to appropriate model based on intent."""
    config = _ctx()._extra.get("config")
    stage = ModelRouteStage(config)
    await stage.setup(_ctx())
    await stage.process(_ctx())
    await stage.teardown(_ctx())
    return {}


async def _compress_node(state: ChatGraphState) -> dict:
    """Compress conversation context if needed."""
    cm = _ctx()._extra.get("conversation_manager")
    stage = CompressStage(cm)
    await stage.setup(_ctx())
    await stage.process(_ctx())
    await stage.teardown(_ctx())
    return {}


async def _llm_call_node(state: ChatGraphState) -> dict:
    """Call LLM — single iteration. Graph-level tool loop.

    Streaming: uses chat_stream_single_with_tools with on_chunk callback.
    Sync: uses chat_single_with_tools.
    """
    client = _ctx()._extra.get("client")
    tools = client.get_builtin_tools() if client.has_builtin_tools() else []

    # Build/accumulate messages
    msgs = _ctx()._extra.get("_tool_messages")
    if msgs is None:
        msgs = []
        if _ctx().system_context:
            msgs.append({"role": "system", "content": _ctx().system_context})
        msgs.extend(_ctx().processed_history or [])
        msgs.append({"role": "user", "content": _ctx().processed_message})
        _ctx()._extra["_tool_messages"] = msgs

    if not tools:
        text = client.chat(
            _ctx().processed_message,
            history=_ctx().processed_history,
            system_context=_ctx().system_context,
            **_ctx().params,
        )
        if _ctx().on_chunk:
            _ctx().on_chunk(text)
        _ctx().response = text
        return {"routing": ChatRoutingState(has_response=True)}

    # Streaming: use streaming single-call for token-by-token output
    if _ctx().on_chunk:
        result = client.chat_stream_single_with_tools(
            tools, msgs, chunk_callback=_ctx().on_chunk, **_ctx().params,
        )
    else:
        result = client.chat_single_with_tools("", tools, messages_override=msgs, **_ctx().params)

    tool_calls = result.get("tool_calls")
    if tool_calls and state.routing.tool_call_count < state.routing.max_tool_iterations:
        # Fire tool_call_start callbacks for GUI
        for tc in tool_calls:
            args_json = json.dumps(tc.arguments if isinstance(tc.arguments, dict) else {}, ensure_ascii=False)
            if _ctx().on_tool_start:
                _ctx().on_tool_start(tc.name, args_json)

        _ctx()._extra["_pending_tool_calls"] = tool_calls
        if "assistant_message" in result:
            _ctx()._extra["_tool_messages"] = msgs + [result["assistant_message"]]
        return {
            "routing": ChatRoutingState(
                has_tool_calls=True,
                tool_call_count=state.routing.tool_call_count + 1,
            ),
        }
    else:
        text = result.get("text", "")
        if not _ctx().on_chunk and text:
            _ctx().on_chunk(text) if _ctx().on_chunk else None
        _ctx().response = text
        return {"routing": ChatRoutingState(has_response=True)}


async def _execute_tools_node(state: ChatGraphState) -> dict:
    """Execute pending tool calls, fire GUI callbacks, append results."""
    from llm_chat.tools import get_tool_registry, ToolExecutor

    registry = get_tool_registry()
    tool_calls = _ctx()._extra.get("_pending_tool_calls", [])

    tool_call_dicts = []
    for tc in tool_calls:
        tc_id = tc.id if hasattr(tc, 'id') else f"tc_{tc.name}"
        args = tc.arguments if isinstance(tc.arguments, dict) else {}
        tool_call_dicts.append({
            "id": tc_id,
            "function": {"name": tc.name, "arguments": json.dumps(args)},
        })

    executor = ToolExecutor(registry, max_workers=5)
    results = executor.execute_tools_parallel(tool_call_dicts)

    for tc, result in zip(tool_calls, results):
        tc_id = tc.id if hasattr(tc, 'id') else f"tc_{tc.name}"
        content = result.get("content", "")
        # Fire tool_call_end callback for GUI
        if _ctx().on_tool_end:
            args_str = json.dumps(tc.arguments if isinstance(tc.arguments, dict) else {}, ensure_ascii=False)
            _ctx().on_tool_end(tc.name, args_str, content[:200])
        # Append tool result to messages
        _ctx()._extra.setdefault("_tool_messages", []).append({
            "role": "tool",
            "tool_call_id": tc_id,
            "content": content,
        })

    _ctx()._extra.pop("_pending_tool_calls", None)
    return {"routing": ChatRoutingState(has_tool_calls=False)}



async def _persist_assistant_node(state: ChatGraphState) -> dict:
    """Persist assistant response to storage."""
    cm = _ctx()._extra.get("conversation_manager")
    stage = PersistAssistantStage(cm)
    await stage.setup(_ctx())
    await stage.process(_ctx())
    await stage.teardown(_ctx())
    return {}


async def _memory_extract_node(state: ChatGraphState) -> dict:
    """Extract memories from conversation."""
    cm = _ctx()._extra.get("conversation_manager")
    stage = MemoryExtractStage(cm)
    await stage.setup(_ctx())
    await stage.process(_ctx())
    await stage.teardown(_ctx())
    return {}


async def _knowledge_extract_node(state: ChatGraphState) -> dict:
    """Extract knowledge from conversation."""
    cm = _ctx()._extra.get("conversation_manager")
    stage = KnowledgeExtractStage(cm)
    await stage.setup(_ctx())
    await stage.process(_ctx())
    await stage.teardown(_ctx())
    return {}


async def _token_record_node(state: ChatGraphState) -> dict:
    """Record token usage."""
    config = _ctx()._extra.get("config")
    stage = TokenRecordStage(config)
    await stage.setup(_ctx())
    await stage.process(_ctx())
    await stage.teardown(_ctx())
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

    # LLM → persist (tool loop handled internally by LLMCallStage/LLMClient)
    # Graph-level tool loop: llm_call → execute_tools → llm_call (or persist)
    g.add_conditional_edge(
        "llm_call", _post_llm_router,
        {"execute_tools": "execute_tools", "persist_assistant": "persist_assistant"},
    )
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

        _set_ctx(ctx)

        # Initialize decision card context for submit_decision_card tool
        init_card_context()

        state = ChatGraphState()

        try:
            result_state = asyncio.run(self._compiled.ainvoke(state))
        except Exception as e:
            logger.error(f"send_message graph failed: {e}", exc_info=True)
            return f"处理消息时发生错误: {str(e)}"

        # Extract pending card from submit_decision_card tool calls
        card = get_pending_card() or _ctx().pending_card
        clear_card_context()
        if card and on_card:
            on_card(card)

        return _ctx().response

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

        _set_ctx(ctx)

        init_card_context()

        state = ChatGraphState()

        try:
            result_state = asyncio.run(self._compiled.ainvoke(state))
        except Exception as e:
            logger.error(f"send_message_stream graph failed: {e}", exc_info=True)
            return f"处理消息时发生错误: {str(e)}"

        card = get_pending_card() or _ctx().pending_card
        clear_card_context()
        if card and on_card:
            on_card(card)

        return _ctx().response

    def cancel_generation(self) -> None:
        """Cancel ongoing stream generation."""
        if self._cancel_event:
            self._cancel_event.set()

    def set_prompt_skills_context(self, context: str) -> None:
        """Inject prompt skills context (called by App after SkillManager init)."""
        self._prompt_skills_holder.set(context)

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
