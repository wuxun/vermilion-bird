"""Chat 图的可序列化状态和非持久化运行时依赖。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from llm_chat.intent.types import Intent, RoutingDecision
from llm_chat.pipeline.chat_state import ChatRoutingState
from llm_chat.pipeline.stage import PipelineContext
from llm_chat.protocols.base import ToolCall, ToolCallStatus


class SerializableToolCall(BaseModel):
    id: str
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    status: str = ToolCallStatus.PENDING.value
    result: Optional[str] = None
    error: Optional[str] = None

    @classmethod
    def from_tool_call(cls, value: Any) -> "SerializableToolCall":
        if isinstance(value, cls):
            return value
        return cls(
            id=str(value.id),
            name=str(value.name),
            arguments=dict(value.arguments or {}),
            status=getattr(
                getattr(value, "status", ToolCallStatus.PENDING),
                "value",
                getattr(value, "status", ToolCallStatus.PENDING.value),
            ),
            result=getattr(value, "result", None),
            error=getattr(value, "error", None),
        )

    def to_tool_call(self) -> ToolCall:
        return ToolCall(
            id=self.id,
            name=self.name,
            arguments=dict(self.arguments),
            status=ToolCallStatus(self.status),
            result=self.result,
            error=self.error,
        )


class ChatGraphState(BaseModel):
    """可由 LangGraph checkpointer 完整保存的请求状态。"""

    conversation_id: str = ""
    user_message: str = ""
    effective_message: str = ""
    routing_decision: Optional[Dict[str, Any]] = None
    should_short_circuit: bool = False
    system_context: Optional[str] = None
    processed_history: List[Dict[str, Any]] = Field(default_factory=list)
    processed_message: str = ""
    params: Dict[str, Any] = Field(default_factory=dict)
    response: str = ""
    status: str = "running"
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tool_messages: List[Dict[str, Any]] = Field(default_factory=list)
    pending_tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    pending_card: Optional[Dict[str, Any]] = None
    routing: Dict[str, Any] = Field(
        default_factory=lambda: ChatRoutingState().model_dump()
    )

    @field_validator("routing", mode="before")
    @classmethod
    def _serialize_routing(cls, value: Any) -> Dict[str, Any]:
        if isinstance(value, ChatRoutingState):
            return value.model_dump()
        return dict(value or {})

    @classmethod
    def from_request(
        cls,
        *,
        conversation_id: str,
        message: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> "ChatGraphState":
        return cls(
            conversation_id=conversation_id,
            user_message=message,
            effective_message=message,
            params=dict(params or {}),
        )

    @classmethod
    def from_pipeline_context(
        cls,
        ctx: PipelineContext,
        *,
        routing: Optional[ChatRoutingState] = None,
    ) -> "ChatGraphState":
        return cls(
            conversation_id=ctx.conversation_id,
            user_message=ctx.user_message,
            effective_message=ctx.effective_message,
            routing_decision=_dump_routing_decision(ctx.routing_decision),
            should_short_circuit=ctx.should_short_circuit,
            system_context=ctx.system_context,
            processed_history=list(ctx.processed_history),
            processed_message=ctx.processed_message,
            params=dict(ctx.params),
            response=ctx.response,
            status=ctx.status,
            error=ctx.error,
            metadata=dict(ctx.metadata),
            routing=(routing or ChatRoutingState()).model_dump(),
        )

    def to_pipeline_context(
        self,
        runtime: "ChatRuntimeContext",
    ) -> PipelineContext:
        return PipelineContext(
            conversation_id=self.conversation_id,
            user_message=self.user_message,
            effective_message=self.effective_message,
            routing_decision=_load_routing_decision(self.routing_decision),
            should_short_circuit=self.should_short_circuit,
            system_context=self.system_context,
            processed_history=list(self.processed_history),
            processed_message=self.processed_message,
            params=dict(self.params),
            response=self.response,
            cancel_event=runtime.cancel_event,
            status=self.status,
            error=self.error,
            on_chunk=runtime.on_chunk,
            on_tool_start=runtime.on_tool_start,
            on_tool_end=runtime.on_tool_end,
            on_context_update=runtime.on_context_update,
            on_card=runtime.on_card,
            metadata=dict(self.metadata),
        )

    @staticmethod
    def pipeline_update(ctx: PipelineContext) -> Dict[str, Any]:
        return {
            "effective_message": ctx.effective_message,
            "routing_decision": _dump_routing_decision(ctx.routing_decision),
            "should_short_circuit": ctx.should_short_circuit,
            "system_context": ctx.system_context,
            "processed_history": list(ctx.processed_history),
            "processed_message": ctx.processed_message,
            "params": dict(ctx.params),
            "response": ctx.response,
            "status": ctx.status,
            "error": ctx.error,
            "metadata": dict(ctx.metadata),
        }


@dataclass
class ChatRuntimeContext:
    """一次调用的依赖和回调；LangGraph 不会持久化该对象。"""

    client: Any
    conversation_manager: Any
    config: Any
    intent_classifier: Any
    prompt_skills_holder: Any
    style_holder: Any
    run_manager: Any
    capability_policy: Any
    action_proposals: Any
    context_hub: Any
    tool_registry: Any
    run_id: str
    action_prepare: Optional[Callable[[Any], Any]] = None
    on_chunk: Optional[Callable[[str], None]] = None
    on_tool_start: Optional[Callable[[str, str], None]] = None
    on_tool_end: Optional[Callable[[str, str, str], None]] = None
    on_context_update: Optional[Callable[[int, int], None]] = None
    on_card: Optional[Callable[..., None]] = None
    cancel_event: Optional[threading.Event] = None

    @classmethod
    def from_pipeline_context(
        cls,
        ctx: PipelineContext,
    ) -> "ChatRuntimeContext":
        extra = getattr(ctx, "_extra", {})
        return cls(
            client=extra.get("client"),
            conversation_manager=extra.get("conversation_manager"),
            config=extra.get("config"),
            intent_classifier=extra.get("intent_classifier"),
            prompt_skills_holder=extra.get("prompt_skills_holder"),
            style_holder=extra.get("style_holder"),
            run_manager=extra.get("run_manager"),
            capability_policy=extra.get("capability_policy"),
            action_proposals=extra.get("action_proposals"),
            context_hub=extra.get("context_hub"),
            tool_registry=extra.get("tool_registry"),
            run_id=extra.get("run_id", ""),
            action_prepare=extra.get("action_prepare"),
            on_chunk=ctx.on_chunk,
            on_tool_start=ctx.on_tool_start,
            on_tool_end=ctx.on_tool_end,
            on_context_update=ctx.on_context_update,
            on_card=ctx.on_card,
            cancel_event=ctx.cancel_event,
        )


def _dump_routing_decision(
    decision: Optional[RoutingDecision],
) -> Optional[Dict[str, Any]]:
    if decision is None:
        return None
    return {
        "intent": decision.intent.value,
        "confidence": decision.confidence,
        "skip_llm": decision.skip_llm,
        "direct_response": decision.direct_response,
        "override_message": decision.override_message,
        "suggested_model": decision.suggested_model,
        "suggested_tools": list(decision.suggested_tools),
        "force_reasoning": decision.force_reasoning,
    }


def _load_routing_decision(
    value: Optional[Dict[str, Any]],
) -> Optional[RoutingDecision]:
    if value is None:
        return None
    return RoutingDecision(
        intent=Intent(value["intent"]),
        confidence=float(value.get("confidence", 1.0)),
        skip_llm=bool(value.get("skip_llm", False)),
        direct_response=value.get("direct_response"),
        override_message=value.get("override_message"),
        suggested_model=value.get("suggested_model"),
        suggested_tools=list(value.get("suggested_tools", [])),
        force_reasoning=bool(value.get("force_reasoning", False)),
    )
