"""ChatCoreGraph — ChatCore pipeline using LangGraph.

Replaces the linear PipelineRunner with a LangGraph StateGraph that supports:
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

from ember_agent.consensus import init_card_context, get_pending_card, clear_card_context
from langgraph.graph import END, StateGraph

from llm_chat.config import Config
from llm_chat.client import LLMClient
from llm_chat.conversation import ConversationManager
from llm_chat.context import ContextHub, build_default_context_hub
from llm_chat.pipeline.chat_state import ChatRoutingState
from llm_chat.pipeline.stage import PipelineContext
from llm_chat.pipeline.stages import (
    IntentStage,
    ShortcutStage,
    PersistUserStage,
    SystemContextStage,
    HistoryStage,
    ModelRouteStage,
    CompressStage,
    PersistAssistantStage,
    MemoryExtractStage,
    KnowledgeExtractStage,
    TokenRecordStage,
)
from llm_chat.pipeline import MutableStrHolder
from llm_chat.runtime import (
    ActionProposalManager,
    ActionStatus,
    CapabilityPolicy,
    PolicyDecision,
    RunManager,
    RunType,
)
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
    ctx = getattr(_chat_ctx_local, "ctx", None)
    assert ctx is not None, "PipelineContext not initialized"
    return ctx


def _set_ctx(ctx: PipelineContext) -> None:
    _chat_ctx_local.ctx = ctx


def _clear_ctx() -> None:
    """Remove request-local context after a graph invocation."""
    if hasattr(_chat_ctx_local, "ctx"):
        del _chat_ctx_local.ctx


def _routing_update(state: ChatGraphState, **changes) -> ChatRoutingState:
    """Patch routing fields without resetting counters and execution budgets."""
    return state.routing.model_copy(update=changes)


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
        "routing": _routing_update(
            state,
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
        "routing": _routing_update(
            state,
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
    context_hub = _ctx()._extra.get("context_hub")
    stage = SystemContextStage(cm, prompt_holder, style_holder, context_hub)
    await stage.setup(_ctx())
    await stage.process(_ctx())
    await stage.teardown(_ctx())
    run_manager = _ctx()._extra.get("run_manager")
    run_id = _ctx()._extra.get("run_id")
    context_items = _ctx().metadata.get("context_items", [])
    if run_manager and run_id:
        run_manager.emit(
            run_id,
            "context.selected",
            {
                "count": len(context_items),
                "items": [
                    {
                        "id": item["id"],
                        "kind": item["kind"],
                        "source": item["source"],
                        "priority": item["priority"],
                    }
                    for item in context_items
                ],
            },
        )
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
    config = _ctx()._extra.get("config")
    tools_enabled = getattr(config, "enable_tools", True)
    tools = client.get_builtin_tools() if tools_enabled and client.has_builtin_tools() else []

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
        return {"routing": _routing_update(state, has_response=True, has_tool_calls=False)}

    # Streaming: use streaming single-call for token-by-token output
    if _ctx().on_chunk:
        result = client.chat_stream_single_with_tools(
            tools,
            msgs,
            chunk_callback=_ctx().on_chunk,
            **_ctx().params,
        )
    else:
        result = client.chat_single_with_tools("", tools, messages_override=msgs, **_ctx().params)

    tool_calls = result.get("tool_calls")
    if tool_calls and state.routing.tool_call_count < state.routing.max_tool_iterations:
        # Fire tool_call_start callbacks for GUI
        for tc in tool_calls:
            args_json = json.dumps(
                tc.arguments if isinstance(tc.arguments, dict) else {}, ensure_ascii=False
            )
            if _ctx().on_tool_start:
                _ctx().on_tool_start(tc.name, args_json)

        _ctx()._extra["_pending_tool_calls"] = tool_calls
        if "assistant_message" in result:
            _ctx()._extra["_tool_messages"] = msgs + [result["assistant_message"]]
        return {
            "routing": _routing_update(
                state,
                has_tool_calls=True,
            ),
        }
    else:
        text = result.get("text", "")
        if tool_calls and not text:
            text = "工具调用已达到最大迭代次数 " f"({state.routing.max_tool_iterations})，已停止继续执行。"
        if not _ctx().on_chunk and text:
            _ctx().on_chunk(text) if _ctx().on_chunk else None
        _ctx().response = text
        return {"routing": _routing_update(state, has_response=True, has_tool_calls=False)}


async def _execute_tools_node(state: ChatGraphState) -> dict:
    """Execute pending tool calls, fire GUI callbacks, append results."""
    from llm_chat.tools import get_tool_registry, ToolExecutor

    registry = get_tool_registry()
    tool_calls = _ctx()._extra.get("_pending_tool_calls", [])
    policy = _ctx()._extra.get("capability_policy")
    proposals = _ctx()._extra.get("action_proposals")
    run_manager = _ctx()._extra.get("run_manager")
    run_id = _ctx()._extra.get("run_id")

    allowed_call_dicts = []
    results_by_id = {}
    for tc in tool_calls:
        tc_id = tc.id if hasattr(tc, "id") else f"tc_{tc.name}"
        args = tc.arguments if isinstance(tc.arguments, dict) else {}
        tool = registry.get_tool(tc.name)
        declared = getattr(tool, "capabilities", frozenset()) if tool else None
        decision, capabilities = (
            policy.evaluate(tc.name, declared) if policy else (PolicyDecision.ALLOW, set())
        )

        if decision == PolicyDecision.REQUIRE_APPROVAL and proposals:
            proposal = proposals.propose(
                run_id=run_id,
                conversation_id=_ctx().conversation_id,
                tool_name=tc.name,
                arguments=args,
                capabilities=capabilities,
            )
            prepare_action = _ctx()._extra.get("action_prepare")
            if prepare_action:
                proposal = prepare_action(proposal)
            if run_manager:
                run_manager.emit(
                    run_id,
                    "action.proposed",
                    {
                        "proposal_id": proposal.id,
                        "tool": tc.name,
                        "capabilities": sorted(capability.value for capability in capabilities),
                    },
                )
            results_by_id[tc_id] = {
                "tool_call_id": tc_id,
                "content": (
                    f"Action requires user approval. Proposal: {proposal.id}. "
                    f"Ask the user to run /approve-action {proposal.id} "
                    f"or /reject-action {proposal.id}. Do not claim it executed."
                ),
                "is_error": True,
            }
            continue

        if decision == PolicyDecision.DENY:
            results_by_id[tc_id] = {
                "tool_call_id": tc_id,
                "content": (
                    "Action denied by capability policy: "
                    + ", ".join(sorted(cap.value for cap in capabilities))
                ),
                "is_error": True,
            }
            if run_manager:
                run_manager.emit(
                    run_id,
                    "action.denied",
                    {"tool": tc.name},
                )
            continue

        allowed_call_dicts.append(
            {
                "id": tc_id,
                "function": {"name": tc.name, "arguments": json.dumps(args)},
            }
        )

    if allowed_call_dicts:
        if run_manager:
            for call in allowed_call_dicts:
                run_manager.emit(
                    run_id,
                    "tool.started",
                    {"tool": call["function"]["name"], "tool_call_id": call["id"]},
                )
        executor = ToolExecutor(registry, max_workers=5)
        try:
            executed = executor.execute_tools_parallel(allowed_call_dicts)
        finally:
            executor.shutdown()
        for result in executed:
            results_by_id[result["tool_call_id"]] = result
            if run_manager:
                run_manager.emit(
                    run_id,
                    "tool.completed",
                    {
                        "tool_call_id": result["tool_call_id"],
                        "is_error": result.get("is_error", False),
                    },
                )

    results = []
    for tc in tool_calls:
        tc_id = tc.id if hasattr(tc, "id") else f"tc_{tc.name}"
        results.append(
            results_by_id.get(
                tc_id,
                {
                    "tool_call_id": tc_id,
                    "content": "Error: missing tool execution result",
                    "is_error": True,
                },
            )
        )

    for tc, result in zip(tool_calls, results):
        tc_id = tc.id if hasattr(tc, "id") else f"tc_{tc.name}"
        content = result.get("content", "")
        # Fire tool_call_end callback for GUI
        if _ctx().on_tool_end:
            args_str = json.dumps(
                tc.arguments if isinstance(tc.arguments, dict) else {}, ensure_ascii=False
            )
            _ctx().on_tool_end(tc.name, args_str, content[:200])
        # Append tool result to messages
        _ctx()._extra.setdefault("_tool_messages", []).append(
            {
                "role": "tool",
                "tool_call_id": tc_id,
                "content": content,
            }
        )

    _ctx()._extra.pop("_pending_tool_calls", None)
    return {
        "routing": _routing_update(
            state,
            has_tool_calls=False,
            tool_call_count=state.routing.tool_call_count + 1,
        )
    }


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

    should_short_circuit = True: shortcut handled and persisted the request
    (e.g. /style, /help) → finish without a duplicate assistant write.

    Otherwise: proceed through the full pipeline (greetings go through LLM normally).
    """
    if state.routing.should_short_circuit:
        return "__finish__"
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
    g.add_conditional_edges(
        "shortcut",
        _post_shortcut_router,
        {
            "persist_user": "persist_user",
            "persist_assistant": "persist_assistant",
            "__finish__": END,
        },
    )

    g.add_edge("persist_user", "system_context")
    g.add_edge("system_context", "history")
    g.add_edge("history", "model_route")
    g.add_edge("model_route", "compress")
    g.add_edge("compress", "llm_call")

    # LLM → persist (tool loop handled internally by LLMCallStage/LLMClient)
    # Graph-level tool loop: llm_call → execute_tools → llm_call (or persist)
    g.add_conditional_edges(
        "llm_call",
        _post_llm_router,
        {"execute_tools": "execute_tools", "persist_assistant": "persist_assistant"},
    )
    g.add_edge("execute_tools", "llm_call")

    g.add_edge("persist_assistant", "memory_extract")
    g.add_edge("memory_extract", "knowledge_extract")
    g.add_edge("knowledge_extract", "token_record")
    g.add_edge("token_record", END)

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
        run_manager: Optional[RunManager] = None,
        capability_policy: Optional[CapabilityPolicy] = None,
        action_proposals: Optional[ActionProposalManager] = None,
        action_prepare: Optional[Callable[[Any], Any]] = None,
        action_approve: Optional[Callable[..., Any]] = None,
        action_reject: Optional[Callable[..., Any]] = None,
        context_hub: Optional[ContextHub] = None,
    ):
        self.client = client
        self.conversation_manager = conversation_manager
        self.config = config
        self.run_manager = run_manager or RunManager()
        self.capability_policy = capability_policy or CapabilityPolicy()
        self.action_proposals = action_proposals or ActionProposalManager()
        self.action_prepare = action_prepare
        self.action_approve = action_approve
        self.action_reject = action_reject
        self.context_hub = context_hub or build_default_context_hub(conversation_manager)
        self._cancel_event: Optional[threading.Event] = None
        self._prompt_skills_holder = MutableStrHolder("")
        self._style_holder = MutableStrHolder("default")

        from llm_chat.intent import IntentClassifier

        self.intent_classifier = IntentClassifier(
            enable_layer1=config.tools.enable_intent
            if hasattr(config.tools, "enable_intent")
            else True
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
        *,
        parent_run_id: Optional[str] = None,
        run_type: RunType = RunType.CHAT,
        **model_params,
    ) -> str:
        """Synchronous send_message — uses async graph internally."""
        run = self.run_manager.start(
            run_type,
            conversation_id=conversation_id,
            parent_run_id=parent_run_id,
            input={"message": message},
        )
        action_response = self._handle_action_command(
            conversation_id,
            message,
            command_run_id=run.id,
        )
        if action_response is not None:
            self.run_manager.complete(run.id, action_response)
            return action_response

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
            "run_manager": self.run_manager,
            "capability_policy": self.capability_policy,
            "action_proposals": self.action_proposals,
            "action_prepare": self.action_prepare,
            "context_hub": self.context_hub,
            "run_id": run.id,
        }

        _set_ctx(ctx)

        # Initialize decision card context for submit_decision_card tool
        init_card_context()

        state = ChatGraphState()

        try:
            asyncio.run(self._compiled.ainvoke(state))
        except Exception as e:
            logger.error(f"send_message graph failed: {e}", exc_info=True)
            self.run_manager.fail(run.id, str(e))
            return f"处理消息时发生错误: {str(e)}"
        finally:
            # Extract before clearing request-local state. ContextVar cleanup
            # must also happen on graph failures.
            card = get_pending_card() or ctx.pending_card
            clear_card_context()
            _clear_ctx()

        if ctx.cancel_event and ctx.cancel_event.is_set():
            self.run_manager.cancel(run.id)
        else:
            self.run_manager.complete(run.id, ctx.response)
        if card and on_card:
            card.conversation_id = conversation_id
            on_card(card)

        return ctx.response

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
        *,
        parent_run_id: Optional[str] = None,
        run_type: RunType = RunType.CHAT,
        **model_params,
    ) -> str:
        """Streaming send_message."""
        run = self.run_manager.start(
            run_type,
            conversation_id=conversation_id,
            parent_run_id=parent_run_id,
            input={"message": message, "stream": True},
        )
        action_response = self._handle_action_command(
            conversation_id,
            message,
            command_run_id=run.id,
        )
        if action_response is not None:
            if on_chunk:
                on_chunk(action_response)
            self.run_manager.complete(run.id, action_response)
            return action_response

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
            "run_manager": self.run_manager,
            "capability_policy": self.capability_policy,
            "action_proposals": self.action_proposals,
            "action_prepare": self.action_prepare,
            "context_hub": self.context_hub,
            "run_id": run.id,
        }

        _set_ctx(ctx)

        init_card_context()

        state = ChatGraphState()

        try:
            asyncio.run(self._compiled.ainvoke(state))
        except Exception as e:
            logger.error(f"send_message_stream graph failed: {e}", exc_info=True)
            self.run_manager.fail(run.id, str(e))
            return f"处理消息时发生错误: {str(e)}"
        finally:
            card = get_pending_card() or ctx.pending_card
            clear_card_context()
            _clear_ctx()

        if ctx.cancel_event and ctx.cancel_event.is_set():
            self.run_manager.cancel(run.id)
        else:
            self.run_manager.complete(run.id, ctx.response)
        if card and on_card:
            card.conversation_id = conversation_id
            on_card(card)

        return ctx.response

    def cancel_generation(self) -> None:
        """Cancel ongoing stream generation."""
        if self._cancel_event:
            self._cancel_event.set()

    def set_prompt_skills_context(self, context: str) -> None:
        """Inject prompt skills context (called by App after SkillManager init)."""
        self._prompt_skills_holder.set(context)

    def _handle_action_command(
        self,
        conversation_id: str,
        message: str,
        *,
        command_run_id: str,
    ) -> Optional[str]:
        """Execute explicit human approval commands before the LLM pipeline."""
        parts = message.strip().split(maxsplit=1)
        command = parts[0].lower() if parts else ""
        if command not in {
            "/actions",
            "/approve-action",
            "/reject-action",
        }:
            return None

        try:
            if command == "/actions":
                pending = self.action_proposals.list(
                    status=ActionStatus.PENDING,
                    conversation_id=conversation_id,
                )
                if pending:
                    lines = [
                        f"- {item.id}: {item.tool_name} "
                        f"[{', '.join(sorted(cap.value for cap in item.capabilities))}]"
                        for item in pending
                    ]
                    response = "待审批动作：\n" + "\n".join(lines)
                else:
                    response = "当前没有待审批动作。"
            elif len(parts) != 2 or not parts[1].strip():
                response = f"用法：{command} <action_id>"
            elif command == "/reject-action":
                action_reject = getattr(self, "action_reject", None)
                if action_reject:
                    proposal = action_reject(
                        parts[1].strip(),
                        conversation_id=conversation_id,
                    )
                else:
                    proposal = self.action_proposals.reject(
                        parts[1].strip(),
                        conversation_id=conversation_id,
                    )
                if not action_reject and self.run_manager.get(proposal.run_id):
                    self.run_manager.emit(
                        proposal.run_id,
                        "action.rejected",
                        {"proposal_id": proposal.id},
                    )
                response = f"已拒绝动作 {proposal.id}（{proposal.tool_name}）。"
            else:
                action_approve = getattr(self, "action_approve", None)
                if action_approve:
                    proposal = action_approve(
                        parts[1].strip(),
                        conversation_id=conversation_id,
                        parent_run_id=command_run_id,
                    )
                else:
                    from llm_chat.tools import get_tool_registry

                    proposal = self.action_proposals.approve_and_execute(
                        parts[1].strip(),
                        tool_registry=get_tool_registry(),
                        run_manager=self.run_manager,
                        parent_run_id=command_run_id,
                        conversation_id=conversation_id,
                    )
                if not action_approve and self.run_manager.get(proposal.run_id):
                    self.run_manager.emit(
                        proposal.run_id,
                        f"action.{proposal.status.value}",
                        {"proposal_id": proposal.id},
                    )
                if proposal.status == ActionStatus.COMPLETED:
                    response = f"动作 {proposal.id} 已批准并执行完成。\n" f"{proposal.result or ''}"
                else:
                    response = f"动作 {proposal.id} 执行失败：" f"{proposal.error or '未知错误'}"
        except (KeyError, ValueError) as exc:
            response = f"动作处理失败：{exc}"

        conversation = self.conversation_manager.get_conversation(conversation_id)
        conversation.add_user_message(message)
        conversation.add_assistant_message(response)
        return response

    # ── Convenience ───────────────────────────────────────────

    def get_system_context(self, conversation_id: str) -> Optional[str]:
        """Get system context for a conversation (for preview)."""
        stage = SystemContextStage(
            self.conversation_manager,
            self._prompt_skills_holder,
            self._style_holder,
            self.context_hub,
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
