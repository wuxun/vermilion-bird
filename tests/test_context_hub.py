"""Unified Context Hub ranking, scoping and provider adapter tests."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from llm_chat.context import (
    ContextHub,
    ContextItem,
    ContextKind,
    ContextQuery,
    ContextScope,
    Sensitivity,
    build_default_context_hub,
)


class StaticProvider:
    name = "static"

    def __init__(self, items):
        self.items = items

    def retrieve(self, query):
        return list(self.items)


def _item(content, *, priority=50, **kwargs):
    return ContextItem(
        kind=kwargs.pop("kind", ContextKind.SUMMARY),
        scope=kwargs.pop("scope", ContextScope.USER),
        content=content,
        source=kwargs.pop("source", "test"),
        priority=priority,
        **kwargs,
    )


def test_hub_deduplicates_ranks_and_applies_budget():
    hub = ContextHub(
        [
            StaticProvider(
                [
                    _item("duplicate", priority=20),
                    _item("duplicate", priority=90),
                    _item("lower priority context", priority=10),
                ]
            )
        ]
    )

    selected = hub.retrieve(ContextQuery(token_budget=5))

    assert len([item for item in selected if "duplicate" in item.content]) == 1
    assert selected[0].priority == 90
    assert sum(item.estimated_tokens for item in selected) <= 12


def test_hub_filters_expired_sensitive_and_cross_conversation_items():
    now = datetime.now(timezone.utc)
    hub = ContextHub(
        [
            StaticProvider(
                [
                    _item(
                        "expired",
                        expires_at=now - timedelta(seconds=1),
                    ),
                    _item(
                        "secret",
                        sensitivity=Sensitivity.SENSITIVE,
                    ),
                    _item(
                        "other conversation",
                        scope=ContextScope.CONVERSATION,
                        conversation_id="conv-b",
                    ),
                    _item(
                        "visible",
                        scope=ContextScope.CONVERSATION,
                        conversation_id="conv-a",
                    ),
                ]
            )
        ]
    )

    selected = hub.retrieve(
        ContextQuery(
            conversation_id="conv-a",
            include_sensitive=False,
        )
    )

    assert [item.content for item in selected] == ["visible"]


def test_default_adapters_unify_memory_knowledge_and_history():
    memory = SimpleNamespace(build_system_prompt=lambda: "memory context")
    conversation = SimpleNamespace(_memory_manager=memory)
    knowledge = SimpleNamespace(build_knowledge_context=lambda text: f"knowledge for {text}")

    class ConversationManager:
        knowledge_manager = knowledge

        def get_conversation(self, conversation_id):
            return conversation

        def search_messages(self, text, limit=5):
            return [
                {
                    "role": "assistant",
                    "content": "historical context that is long enough to include",
                }
            ]

    hub = build_default_context_hub(ConversationManager())
    selected = hub.retrieve(ContextQuery(text="question", conversation_id="conv-a"))

    assert {item.kind for item in selected} == {
        ContextKind.USER_MEMORY,
        ContextKind.DOMAIN_KNOWLEDGE,
        ContextKind.CONVERSATION_HISTORY,
    }
    assert {item.source for item in selected} == {
        "memory.manager",
        "knowledge.manager",
        "storage.fts5",
    }
