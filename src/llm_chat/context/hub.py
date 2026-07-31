"""Unified retrieval and budgeting for all prompt context sources."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContextKind(str, Enum):
    USER_MEMORY = "user_memory"
    DOMAIN_KNOWLEDGE = "domain_knowledge"
    CONVERSATION_HISTORY = "conversation_history"
    INSTRUCTION = "instruction"
    PROMPT_SKILL = "prompt_skill"
    STYLE = "style"
    SUMMARY = "summary"
    RESOURCE = "resource"


class ContextScope(str, Enum):
    GLOBAL = "global"
    USER = "user"
    CONVERSATION = "conversation"
    PROJECT = "project"
    DOMAIN = "domain"


class Sensitivity(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    SENSITIVE = "sensitive"


class ContextItem(BaseModel):
    """A source-aware, rankable unit of context."""

    id: str = Field(default_factory=lambda: f"ctx_{uuid4().hex}")
    kind: ContextKind
    scope: ContextScope
    content: str
    source: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    priority: int = Field(default=50, ge=0, le=100)
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    conversation_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    expires_at: Optional[datetime] = None

    @property
    def active(self) -> bool:
        return self.expires_at is None or self.expires_at > _utc_now()

    @property
    def estimated_tokens(self) -> int:
        return max(1, len(self.content) // 4)


class ContextQuery(BaseModel):
    text: str = ""
    conversation_id: Optional[str] = None
    token_budget: int = Field(default=4000, ge=0)
    kinds: Optional[set[ContextKind]] = None
    include_sensitive: bool = True


class ContextProvider(Protocol):
    name: str

    def retrieve(self, query: ContextQuery) -> List[ContextItem]:
        """Return zero or more context items for the query."""


class ContextHub:
    """Aggregate providers, isolate failures, deduplicate, rank and budget."""

    def __init__(self, providers: Optional[Iterable[ContextProvider]] = None):
        self._providers: Dict[str, ContextProvider] = {}
        for provider in providers or []:
            self.register(provider)

    def register(self, provider: ContextProvider) -> None:
        self._providers[provider.name] = provider

    def retrieve(
        self,
        query: ContextQuery,
        *,
        extra_items: Optional[Sequence[ContextItem]] = None,
    ) -> List[ContextItem]:
        items = list(extra_items or [])
        for provider in self._providers.values():
            try:
                items.extend(provider.retrieve(query))
            except Exception:
                logger.warning(
                    "Context provider failed: %s",
                    provider.name,
                    exc_info=True,
                )

        filtered = [
            item
            for item in items
            if item.active
            and item.content.strip()
            and (query.kinds is None or item.kind in query.kinds)
            and (query.include_sensitive or item.sensitivity != Sensitivity.SENSITIVE)
            and (
                not item.conversation_id
                or not query.conversation_id
                or item.conversation_id == query.conversation_id
            )
        ]
        deduped: Dict[str, ContextItem] = {}
        for item in filtered:
            fingerprint = re.sub(r"\s+", " ", item.content).strip().casefold()
            current = deduped.get(fingerprint)
            if current is None or (item.priority, item.confidence) > (
                current.priority,
                current.confidence,
            ):
                deduped[fingerprint] = item

        ranked = sorted(
            deduped.values(),
            key=lambda item: (
                -item.priority,
                -item.confidence,
                item.created_at,
                item.id,
            ),
        )
        return self._apply_budget(ranked, query.token_budget)

    def render(
        self,
        query: ContextQuery,
        *,
        extra_items: Optional[Sequence[ContextItem]] = None,
    ) -> tuple[str, List[ContextItem]]:
        items = self.retrieve(query, extra_items=extra_items)
        return "\n\n---\n\n".join(item.content for item in items), items

    @staticmethod
    def _apply_budget(
        items: Sequence[ContextItem],
        token_budget: int,
    ) -> List[ContextItem]:
        if token_budget <= 0:
            return []
        selected: List[ContextItem] = []
        remaining = token_budget
        for item in items:
            if item.estimated_tokens <= remaining:
                selected.append(item)
                remaining -= item.estimated_tokens
                continue
            if remaining < 16:
                break
            char_limit = remaining * 4
            suffix = "\n[上下文已按预算截断]"
            truncated_content = item.content[: max(1, char_limit - len(suffix))].rstrip()
            truncated = item.model_copy(
                update={
                    "content": truncated_content + suffix,
                    "metadata": {**item.metadata, "truncated": True},
                },
                deep=True,
            )
            selected.append(truncated)
            break
        return selected


class MemoryContextProvider:
    name = "memory"

    def __init__(self, conversation_manager):
        self._conversation_manager = conversation_manager

    def retrieve(self, query: ContextQuery) -> List[ContextItem]:
        if not query.conversation_id:
            return []
        conversation = self._conversation_manager.get_conversation(query.conversation_id)
        manager = getattr(conversation, "_memory_manager", None)
        content = manager.build_system_prompt() if manager else ""
        if not content:
            return []
        return [
            ContextItem(
                kind=ContextKind.USER_MEMORY,
                scope=ContextScope.USER,
                content=content,
                source="memory.manager",
                priority=85,
                sensitivity=Sensitivity.SENSITIVE,
                conversation_id=query.conversation_id,
            )
        ]


class KnowledgeContextProvider:
    name = "knowledge"

    def __init__(self, conversation_manager):
        self._conversation_manager = conversation_manager

    def retrieve(self, query: ContextQuery) -> List[ContextItem]:
        manager = self._conversation_manager.knowledge_manager
        content = manager.build_knowledge_context(query.text) if manager else ""
        if not content:
            return []
        return [
            ContextItem(
                kind=ContextKind.DOMAIN_KNOWLEDGE,
                scope=ContextScope.DOMAIN,
                content=content,
                source="knowledge.manager",
                priority=70,
                confidence=0.8,
            )
        ]


class HistoryContextProvider:
    name = "history"

    def __init__(self, conversation_manager, limit: int = 5):
        self._conversation_manager = conversation_manager
        self._limit = limit

    def retrieve(self, query: ContextQuery) -> List[ContextItem]:
        if not query.text:
            return []
        matches = self._conversation_manager.search_messages(
            query.text,
            limit=self._limit,
        )
        relevant = [
            message
            for message in matches
            if len(message.get("content", "")) > 20
            and not (message.get("role") == "user" and message.get("content") == query.text)
        ][:3]
        if not relevant:
            return []
        lines = [
            "## 相关历史对话",
            "以下是与当前问题相关的历史对话片段，可作为回答参考：",
        ]
        for index, result in enumerate(relevant, 1):
            lines.append(
                f"{index}. [{result.get('role', 'unknown')}]: " f"{result.get('content', '')[:300]}"
            )
        return [
            ContextItem(
                kind=ContextKind.CONVERSATION_HISTORY,
                scope=ContextScope.USER,
                content="\n".join(lines),
                source="storage.fts5",
                priority=50,
                confidence=0.6,
            )
        ]


class ResourceContextProvider:
    name = "context_resources"

    def __init__(self, resource_service):
        self._resource_service = resource_service

    def retrieve(self, query: ContextQuery) -> List[ContextItem]:
        if not query.conversation_id:
            return []
        resources = self._resource_service.list(
            conversation_id=query.conversation_id,
            active_only=True,
        )
        items = []
        for resource in resources:
            try:
                content, changed = self._resource_service.read_for_context(resource)
            except Exception:
                logger.warning(
                    "Context resource read failed: %s",
                    resource.id,
                    exc_info=True,
                )
                continue
            if not content:
                continue
            items.append(
                ContextItem(
                    kind=ContextKind.RESOURCE,
                    scope=ContextScope.CONVERSATION,
                    content=content,
                    source=f"context_resource:{resource.id}",
                    priority=92,
                    sensitivity=Sensitivity(resource.sensitivity.value),
                    conversation_id=query.conversation_id,
                    metadata={
                        "context_resource_id": resource.id,
                        "changed_since_attachment": changed,
                        "resource_kind": resource.kind.value,
                    },
                )
            )
        return items


def build_default_context_hub(conversation_manager, *, resource_service=None) -> ContextHub:
    providers = [
        MemoryContextProvider(conversation_manager),
        KnowledgeContextProvider(conversation_manager),
        HistoryContextProvider(conversation_manager),
    ]
    if resource_service is not None:
        providers.append(ResourceContextProvider(resource_service))
    return ContextHub(providers)
