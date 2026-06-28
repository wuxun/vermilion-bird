"""Decision card data models — pure Pydantic, zero dependencies beyond stdlib.

Core type hierarchy:
    DecisionCard  — complete decision card (options + recommendation)
    DecisionOption — single option (label, description, confidence, risk)
    CardType       — card type enum
    CardStatus     — card lifecycle state machine
    DecisionRecord — persisted decision log entry
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class CardType(str, Enum):
    """Decision card type."""
    DECISION = "decision"
    """Multi-option decision: user selects one to execute."""


class CardStatus(str, Enum):
    """Decision card lifecycle states."""

    PENDING = "pending"
    """Awaiting user decision."""

    DECIDED = "decided"
    """User has made a choice."""

    DISMISSED = "dismissed"
    """User dismissed / deferred the card."""


class DecisionOption(BaseModel):
    """A single option in a decision card."""

    id: str = Field(description="Option identifier (e.g. 'A', 'B', 'C')")
    label: str = Field(description="Option name, e.g. 'Connection pool increase (recommended)'")
    description: Optional[str] = Field(
        default=None, description="Detailed explanation of this option"
    )
    expected_effect: Optional[str] = Field(
        default=None, description="Expected outcome summary"
    )
    risk: Optional[str] = Field(default=None, description="Risk description")
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0 ~ 1.0)",
    )


class DecisionCard(BaseModel):
    """Structured decision card — the core data unit of Decision-First paradigm.

    Each card represents one question requiring user decision.
    """

    id: str = Field(default_factory=lambda: f"card_{uuid.uuid4().hex[:12]}")
    """Unique card identifier."""

    card_type: CardType = CardType.DECISION
    """Card type."""

    status: CardStatus = CardStatus.PENDING
    """Current lifecycle state."""

    title: str = Field(description="Card title — one sentence summarizing the decision")
    context: Optional[str] = Field(
        default=None, description="Background summary (1-3 lines)"
    )
    options: List[DecisionOption] = Field(
        default_factory=list,
        description="Option list (at least 1, typically 2-3)",
    )
    recommendation: Optional[str] = Field(
        default=None,
        description="Recommended option id",
    )
    sources: List[str] = Field(
        default_factory=list,
        description="Information source citations",
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="Associated conversation ID",
    )

    # ── Timestamps ──
    created_at: datetime = Field(default_factory=datetime.now)
    decided_at: Optional[datetime] = Field(default=None)
    dismissed_at: Optional[datetime] = Field(default=None)
    selected_option_id: Optional[str] = Field(
        default=None,
        description="User's final choice (persisted for widget rebuild)",
    )

    def decide(self, option_id: str) -> DecisionOption:
        """User makes a decision.

        Args:
            option_id: The selected option ID.

        Returns:
            The selected DecisionOption.

        Raises:
            ValueError: If option_id not in options or card already decided.
        """
        if self.status != CardStatus.PENDING:
            raise ValueError(
                f"Card {self.id} is {self.status.value}, cannot decide"
            )

        selected = next(
            (o for o in self.options if o.id == option_id), None
        )
        if not selected:
            raise ValueError(
                f"Option {option_id} not in card {self.id} options: "
                f"{[o.id for o in self.options]}"
            )

        self.status = CardStatus.DECIDED
        self.decided_at = datetime.now()
        self.selected_option_id = option_id
        return selected

    def dismiss(self) -> None:
        """User dismisses / defers this card."""
        if self.status != CardStatus.PENDING:
            raise ValueError(
                f"Card {self.id} is {self.status.value}, cannot dismiss"
            )
        self.status = CardStatus.DISMISSED
        self.dismissed_at = datetime.now()


class DecisionRecord(BaseModel):
    """Archived decision record (stored in decision_log table)."""

    id: str = Field(default_factory=lambda: f"rec_{uuid.uuid4().hex[:12]}")
    """Record unique identifier."""

    card_id: str = Field(description="Original decision card ID")
    card_type: CardType = Field(description="Card type")
    title: str = Field(description="Card title")

    selected_option_id: Optional[str] = Field(default=None)
    selected_option_label: Optional[str] = Field(default=None)
    recommendation: Optional[str] = Field(default=None)

    context_snapshot: Optional[str] = Field(
        default=None, description="Context snapshot at decision time"
    )
    conversation_id: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.now)
    decided_at: Optional[datetime] = Field(default=None)
