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

from ember_agent.consensus import init_card_context, get_pending_card, clear_card_context
from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime

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
from llm_chat.runtime.chat_execution import (
    ChatGraphState,
    ChatRuntimeContext,
    SerializableToolCall,
)
from llm_chat.utils.observability import observe

logger = logging.getLogger(__name__)

StreamCallback = Callable[[str], None]
ToolCallStartCallback = Callable[[str, str], None]
ToolCallEndCallback = Callable[[str, str, str], None]
CardCallback = Callable[[Any], None]


def _routing_update(state: ChatGraphState, **changes) -> ChatRoutingState:
    """Patch routing fields without resetting counters and execution budgets."""
    return state.routing.model_copy(update=changes)


def _pipeline_context(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> PipelineContext:
    return state.to_pipeline_context(runtime.context)


async def _run_stage(stage, ctx: PipelineContext) -> Dict[str, Any]:
    await stage.setup(ctx)
    await stage.process(ctx)
    await stage.teardown(ctx)
    return ChatGraphState.pipeline_update(ctx)


# ── Node functions ────────────────────────────────────────────────


async def _intent_node(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict:
    """Intent classification node."""
    ctx = _pipeline_context(state, runtime)
    decision = runtime.context.intent_classifier.classify(ctx.user_message)
    ctx.routing_decision = decision
    if decision.override_message:
        ctx.effective_message = decision.override_message

    update = ChatGraphState.pipeline_update(ctx)
    update["routing"] = _routing_update(
        state,
        intent=decision.intent.value,
        skip_llm=decision.skip_llm,
    )
    return update


async def _shortcut_node(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict:
    """Shortcut handling node."""
    ctx = _pipeline_context(state, runtime)
    stage = ShortcutStage(
        runtime.context.conversation_manager,
        runtime.context.style_holder,
    )
    update = await _run_stage(stage, ctx)
    update["routing"] = _routing_update(
        state,
        should_short_circuit=ctx.should_short_circuit,
        skip_llm=ctx.routing_decision.skip_llm if ctx.routing_decision else False,
    )
    return update


async def _persist_user_node(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict:
    """Persist user message to storage."""
    ctx = _pipeline_context(state, runtime)
    return await _run_stage(
        PersistUserStage(runtime.context.conversation_manager),
        ctx,
    )


async def _system_context_node(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict:
    """Build system context (memory + prompts + style)."""
    ctx = _pipeline_context(state, runtime)
    stage = SystemContextStage(
        runtime.context.conversation_manager,
        runtime.context.prompt_skills_holder,
        runtime.context.style_holder,
        runtime.context.context_hub,
    )
    update = await _run_stage(stage, ctx)
    run_manager = runtime.context.run_manager
    run_id = runtime.context.run_id
    context_items = ctx.metadata.get("context_items", [])
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
    return update


async def _history_node(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict:
    """Load and process conversation history."""
    ctx = _pipeline_context(state, runtime)
    return await _run_stage(
        HistoryStage(runtime.context.conversation_manager),
        ctx,
    )


async def _model_route_node(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict:
    """Route to appropriate model based on intent."""
    ctx = _pipeline_context(state, runtime)
    return await _run_stage(
        ModelRouteStage(runtime.context.config),
        ctx,
    )


async def _compress_node(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict:
    """Compress conversation context if needed."""
    ctx = _pipeline_context(state, runtime)
    return await _run_stage(
        CompressStage(runtime.context.conversation_manager),
        ctx,
    )


async def _llm_call_node(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict:
    """Call LLM — single iteration. Graph-level tool loop.

    Streaming: uses chat_stream_single_with_tools with on_chunk callback.
    Sync: uses chat_single_with_tools.
    """
    ctx = _pipeline_context(state, runtime)
    client = runtime.context.client
    config = runtime.context.config
    tools_enabled = getattr(config, "enable_tools", True)
    tools = client.get_builtin_tools() if tools_enabled and client.has_builtin_tools() else []

    # Build/accumulate messages
    msgs = list(state.tool_messages)
    if not msgs:
        if ctx.system_context:
            msgs.append({"role": "system", "content": ctx.system_context})
        msgs.extend(ctx.processed_history or [])
        msgs.append({"role": "user", "content": ctx.processed_message})

    if not tools:
        text = client.chat(
            ctx.processed_message,
            history=ctx.processed_history,
            system_context=ctx.system_context,
            **ctx.params,
        )
        if ctx.on_chunk:
            ctx.on_chunk(text)
        ctx.response = text
        update = ChatGraphState.pipeline_update(ctx)
        update.update(
            {
                "tool_messages": msgs,
                "routing": _routing_update(
                    state,
                    has_response=True,
                    has_tool_calls=False,
                ),
            }
        )
        return update

    # Streaming: use streaming single-call for token-by-token output
    if ctx.on_chunk:
        result = client.chat_stream_single_with_tools(
            tools,
            msgs,
            chunk_callback=ctx.on_chunk,
            **ctx.params,
        )
    else:
        result = client.chat_single_with_tools(
            "",
            tools,
            messages_override=msgs,
            **ctx.params,
        )

    tool_calls = result.get("tool_calls")
    if tool_calls and state.routing.tool_call_count < state.routing.max_tool_iterations:
        # Fire tool_call_start callbacks for GUI
        for tc in tool_calls:
            args_json = json.dumps(
                tc.arguments if isinstance(tc.arguments, dict) else {}, ensure_ascii=False
            )
            if ctx.on_tool_start:
                ctx.on_tool_start(tc.name, args_json)

        if "assistant_message" in result:
            msgs = msgs + [result["assistant_message"]]
        update = ChatGraphState.pipeline_update(ctx)
        update.update(
            {
                "tool_messages": msgs,
                "pending_tool_calls": [
                    SerializableToolCall.from_tool_call(item) for item in tool_calls
                ],
                "routing": _routing_update(
                    state,
                    has_tool_calls=True,
                ),
            }
        )
        return update
    else:
        text = result.get("text", "")
        if tool_calls and not text:
            text = "工具调用已达到最大迭代次数 " f"({state.routing.max_tool_iterations})，已停止继续执行。"
        ctx.response = text
        update = ChatGraphState.pipeline_update(ctx)
        update.update(
            {
                "tool_messages": msgs,
                "pending_tool_calls": [],
                "routing": _routing_update(
                    state,
                    has_response=True,
                    has_tool_calls=False,
                ),
            }
        )
        return update


async def _execute_tools_node(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict:
    """Execute pending tool calls, fire GUI callbacks, append results."""
    from llm_chat.tools import ToolExecutor, get_tool_registry

    ctx = _pipeline_context(state, runtime)
    registry = runtime.context.tool_registry or get_tool_registry()
    tool_calls = [item.to_tool_call() for item in state.pending_tool_calls]
    policy = runtime.context.capability_policy
    proposals = runtime.context.action_proposals
    run_manager = runtime.context.run_manager
    run_id = runtime.context.run_id

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
                conversation_id=ctx.conversation_id,
                tool_name=tc.name,
                arguments=args,
                capabilities=capabilities,
            )
            prepare_action = runtime.context.action_prepare
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

    messages = list(state.tool_messages)
    for tc, result in zip(tool_calls, results):
        tc_id = tc.id if hasattr(tc, "id") else f"tc_{tc.name}"
        content = result.get("content", "")
        # Fire tool_call_end callback for GUI
        if ctx.on_tool_end:
            args_str = json.dumps(
                tc.arguments if isinstance(tc.arguments, dict) else {}, ensure_ascii=False
            )
            ctx.on_tool_end(tc.name, args_str, content[:200])
        # Append tool result to messages
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tc_id,
                "content": content,
            }
        )

    update = ChatGraphState.pipeline_update(ctx)
    update.update(
        {
            "tool_messages": messages if tool_calls else list(state.tool_messages),
            "pending_tool_calls": [],
            "routing": _routing_update(
                state,
                has_tool_calls=False,
                tool_call_count=state.routing.tool_call_count + 1,
            ),
        }
    )
    return update


async def _persist_assistant_node(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict:
    """Persist assistant response to storage."""
    ctx = _pipeline_context(state, runtime)
    return await _run_stage(
        PersistAssistantStage(runtime.context.conversation_manager),
        ctx,
    )


async def _memory_extract_node(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict:
    """Extract memories from conversation."""
    ctx = _pipeline_context(state, runtime)
    return await _run_stage(
        MemoryExtractStage(runtime.context.conversation_manager),
        ctx,
    )


async def _knowledge_extract_node(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict:
    """Extract knowledge from conversation."""
    ctx = _pipeline_context(state, runtime)
    return await _run_stage(
        KnowledgeExtractStage(runtime.context.conversation_manager),
        ctx,
    )


async def _token_record_node(
    state: ChatGraphState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict:
    """Record token usage."""
    ctx = _pipeline_context(state, runtime)
    return await _run_stage(
        TokenRecordStage(runtime.context.config),
        ctx,
    )


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
    g = StateGraph(
        ChatGraphState,
        context_schema=ChatRuntimeContext,
    )

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

        # Initialize decision card context for submit_decision_card tool
        init_card_context()

        state = ChatGraphState.from_request(
            conversation_id=conversation_id,
            message=message,
            params=model_params,
        )
        runtime_context = self._build_runtime_context(
            run.id,
            on_card=on_card,
        )

        try:
            output = asyncio.run(
                self._compiled.ainvoke(
                    state,
                    context=runtime_context,
                )
            )
            final_state = ChatGraphState.model_validate(output)
        except Exception as e:
            logger.error(f"send_message graph failed: {e}", exc_info=True)
            self.run_manager.fail(run.id, str(e))
            return f"处理消息时发生错误: {str(e)}"
        finally:
            card = get_pending_card()
            clear_card_context()

        if runtime_context.cancel_event and runtime_context.cancel_event.is_set():
            self.run_manager.cancel(run.id)
        else:
            self.run_manager.complete(run.id, final_state.response)
        if card and on_card:
            card.conversation_id = conversation_id
            on_card(card)

        return final_state.response

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
        init_card_context()

        state = ChatGraphState.from_request(
            conversation_id=conversation_id,
            message=message,
            params=model_params,
        )
        runtime_context = self._build_runtime_context(
            run.id,
            on_chunk=on_chunk,
            on_tool_start=on_tool_start,
            on_tool_end=on_tool_end,
            on_context_update=on_context_update,
            on_card=on_card,
            cancel_event=self._cancel_event,
        )

        try:
            output = asyncio.run(
                self._compiled.ainvoke(
                    state,
                    context=runtime_context,
                )
            )
            final_state = ChatGraphState.model_validate(output)
        except Exception as e:
            logger.error(f"send_message_stream graph failed: {e}", exc_info=True)
            self.run_manager.fail(run.id, str(e))
            return f"处理消息时发生错误: {str(e)}"
        finally:
            card = get_pending_card()
            clear_card_context()

        if runtime_context.cancel_event and runtime_context.cancel_event.is_set():
            self.run_manager.cancel(run.id)
        else:
            self.run_manager.complete(run.id, final_state.response)
        if card and on_card:
            card.conversation_id = conversation_id
            on_card(card)

        return final_state.response

    def _build_runtime_context(
        self,
        run_id: str,
        *,
        on_chunk: Optional[StreamCallback] = None,
        on_tool_start: Optional[ToolCallStartCallback] = None,
        on_tool_end: Optional[ToolCallEndCallback] = None,
        on_context_update: Optional[Callable[[int, int], None]] = None,
        on_card: Optional[CardCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> ChatRuntimeContext:
        from llm_chat.tools import get_tool_registry

        return ChatRuntimeContext(
            client=self.client,
            conversation_manager=self.conversation_manager,
            config=self.config,
            intent_classifier=self.intent_classifier,
            prompt_skills_holder=self._prompt_skills_holder,
            style_holder=self._style_holder,
            run_manager=self.run_manager,
            capability_policy=self.capability_policy,
            action_proposals=self.action_proposals,
            context_hub=self.context_hub,
            tool_registry=get_tool_registry(),
            run_id=run_id,
            action_prepare=self.action_prepare,
            on_chunk=on_chunk,
            on_tool_start=on_tool_start,
            on_tool_end=on_tool_end,
            on_context_update=on_context_update,
            on_card=on_card,
            cancel_event=cancel_event,
        )

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
