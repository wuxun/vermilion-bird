"""SubmitCardTool — LLM submits structured decision cards via tool call.

Request-level isolation via contextvars:
    - init_card_context() establishes a request_id
    - SubmitCardTool.execute() writes card to _cards[request_id]
    - get_pending_card() reads and clears current request's card
    - clear_card_context() tears down

This mechanism works across ThreadPoolExecutor boundaries (contextvars
auto-propagate in Python 3.7+).
"""

from __future__ import annotations

import contextvars
import logging
import threading
import uuid
from typing import Any, Dict, Optional

from ember_core.tools.base import BaseTool

logger = logging.getLogger(__name__)

# ── Request-scoped card storage ─────────────────────────────────────

_card_request_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "card_request_id", default=None
)
_cards: Dict[str, "DecisionCard"] = {}
_cards_lock = threading.Lock()


def init_card_context() -> str:
    """Initialize card context, returning a unique request_id.

    Call before each LLM request. The request_id propagates via contextvars
    to all threads in the ThreadPoolExecutor.
    """
    request_id = uuid.uuid4().hex[:12]
    _card_request_id.set(request_id)
    logger.debug(f"[CardContext] init request_id={request_id}")
    return request_id


def clear_card_context() -> None:
    """Clear the current request's card context.

    Call after get_pending_card() to prevent leakage to next request.
    """
    request_id = _card_request_id.get()
    if request_id:
        with _cards_lock:
            _cards.pop(request_id, None)
    _card_request_id.set(None)


def submit_card(card: "DecisionCard") -> None:
    """Submit a decision card within the current request context."""
    request_id = _card_request_id.get()
    if request_id:
        with _cards_lock:
            _cards[request_id] = card
        logger.info(
            f"[SubmitCard] {card.id}: {card.title} (request={request_id})"
        )
    else:
        logger.warning("[SubmitCard] No active request context, card discarded")


def get_pending_card() -> Optional["DecisionCard"]:
    """Get and clear the pending decision card for the current request.

    Returns None if no card was submitted in this request context.
    """
    request_id = _card_request_id.get()
    if not request_id:
        return None
    with _cards_lock:
        return _cards.pop(request_id, None)


# ── Tool ────────────────────────────────────────────────────────────


class SubmitCardTool(BaseTool):
    """Tool: LLM calls this to submit a structured decision card.

    Unlike embedding JSON in text output, this leverages function calling
    for guaranteed structural validity via JSON Schema validation.

    Compatibility:
        - GUI: ChatCore extracts card → CardSignals → widget rendering
        - CLI: Card extracted → text prompt display
        - Agent-to-agent: cards flow through contextvar channel for consensus
    """

    @property
    def name(self) -> str:
        return "submit_decision_card"

    @property
    def description(self) -> str:
        return (
            "Submit a structured decision card to the user. "
            "Use this when you have completed multi-dimensional analysis "
            "and want to present options alongside your text response."
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Card title with emoji, one sentence summarizing the decision topic",
                },
                "context": {
                    "type": "string",
                    "description": "Background summary: 1-2 sentences explaining why a decision is needed",
                },
                "options": {
                    "type": "array",
                    "description": "Option list (2-3 recommended). Each option describes a distinct path.",
                    "minItems": 2,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "Option name, e.g. 'Increase connection pool (recommended)'",
                            },
                            "description": {
                                "type": "string",
                                "description": "Detailed explanation including expected effect and risk",
                            },
                            "confidence": {
                                "type": "number",
                                "description": "Confidence in this option (0.0-1.0). Higher = more certain.",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "expected_effect": {
                                "type": "string",
                                "description": "What will happen if this option is chosen",
                            },
                            "risk": {
                                "type": "string",
                                "description": "Risks or downsides of this option",
                            },
                        },
                        "required": ["label"],
                    },
                },
                "recommendation": {
                    "type": "string",
                    "description": "Recommended option id (A/B/C), optional",
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Information source citations, optional",
                },
            },
            "required": ["title", "options"],
        }

    def execute(
        self,
        title: str,
        options: list,
        context: str = "",
        recommendation: str = "",
        sources: list = None,
        **kwargs,
    ) -> str:
        """Validate and store a decision card via contextvar channel.

        The card is consumed by ChatCore or agent workflow after the
        LLM response completes.
        """
        from ember_agent.consensus.card import DecisionCard, DecisionOption

        try:
            option_ids = ["A", "B", "C", "D"]
            option_objs = []
            for i, o in enumerate(options):
                oid = o.get("id") or (
                    option_ids[i] if i < len(option_ids) else f"O{i + 1}"
                )
                # Use LLM-provided confidence if available, else default
                conf = o.get("confidence")
                if conf is None:
                    conf = 0.85 if recommendation and oid == recommendation else 0.70

                option_objs.append(
                    DecisionOption(
                        id=oid,
                        label=o.get("label", ""),
                        description=o.get("description"),
                        expected_effect=o.get("expected_effect"),
                        risk=o.get("risk"),
                        confidence=conf,
                    )
                )

            card = DecisionCard(
                title=title,
                context=context or None,
                options=option_objs,
                recommendation=recommendation or None,
                sources=sources or [],
            )

            submit_card(card)
            conf_str = ", ".join(
                f"{o.id}={o.confidence:.0%}" for o in option_objs
            )
            return (
                f"Card submitted. ID: {card.id}, "
                f"{len(options)} options, "
                f"confidence: [{conf_str}], "
                f"recommendation: {recommendation or 'none'}."
            )

        except Exception as e:
            logger.error(f"[SubmitCard failed] {e}")
            return f"Card submission failed: {e}"
