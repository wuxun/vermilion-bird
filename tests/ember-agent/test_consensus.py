"""Tests for ember-agent consensus module — DecisionCard, CardAggregator, DecisionLogStore."""

import pytest
import tempfile
import os
from ember_agent.consensus import (
    DecisionCard, DecisionOption, CardType, CardStatus, DecisionRecord,
    CardAggregator, DecisionLogStore,
    init_card_context, clear_card_context, submit_card, get_pending_card,
)
from ember_core.storage import SQLiteStore


# ── DecisionCard tests ─────────────────────────────────────────

class TestDecisionCard:
    def test_create_card(self):
        opts = [DecisionOption(id="A", label="Opt A"), DecisionOption(id="B", label="Opt B")]
        card = DecisionCard(title="Test", options=opts, recommendation="A")
        assert card.status == CardStatus.PENDING
        assert card.recommendation == "A"
        assert len(card.options) == 2
        assert card.id.startswith("card_")

    def test_decide(self):
        opts = [DecisionOption(id="A", label="A"), DecisionOption(id="B", label="B")]
        card = DecisionCard(title="Test", options=opts)
        selected = card.decide("A")
        assert selected.id == "A"
        assert card.status == CardStatus.DECIDED
        assert card.selected_option_id == "A"
        assert card.decided_at is not None

    def test_decide_invalid_option(self):
        card = DecisionCard(title="Test", options=[DecisionOption(id="A", label="A")])
        with pytest.raises(ValueError, match="not in card"):
            card.decide("X")

    def test_decide_already_decided(self):
        card = DecisionCard(title="Test", options=[DecisionOption(id="A", label="A")])
        card.decide("A")
        with pytest.raises(ValueError, match="cannot decide"):
            card.decide("A")

    def test_dismiss(self):
        card = DecisionCard(title="Test", options=[DecisionOption(id="A", label="A")])
        card.dismiss()
        assert card.status == CardStatus.DISMISSED

    def test_dismiss_already_decided(self):
        card = DecisionCard(title="Test", options=[DecisionOption(id="A", label="A")])
        card.decide("A")
        with pytest.raises(ValueError, match="cannot dismiss"):
            card.dismiss()

    def test_option_confidence_range(self):
        opt = DecisionOption(id="A", label="A", confidence=0.5)
        assert opt.confidence == 0.5
        with pytest.raises(Exception):  # pydantic validation
            DecisionOption(id="A", label="A", confidence=1.5)

    def test_decision_record(self):
        record = DecisionRecord(card_id="c1", card_type=CardType.DECISION,
                                title="Test", selected_option_id="A")
        assert record.id.startswith("rec_")


# ── CardAggregator tests ───────────────────────────────────────

class TestCardAggregator:
    def test_vote_majority(self):
        c1 = DecisionCard(title="T", options=[
            DecisionOption(id="A", label="A"), DecisionOption(id="B", label="B"),
        ], recommendation="A")
        c2 = DecisionCard(title="T", options=[
            DecisionOption(id="A", label="A"), DecisionOption(id="B", label="B"),
        ], recommendation="A")
        c3 = DecisionCard(title="T", options=[
            DecisionOption(id="A", label="A"), DecisionOption(id="B", label="B"),
        ], recommendation="B")

        result = CardAggregator.vote([c1, c2, c3])
        assert result.recommendation == "A"  # 2 votes for A, 1 for B

    def test_vote_single(self):
        card = DecisionCard(title="T", options=[DecisionOption(id="A", label="A")], recommendation="A")
        result = CardAggregator.vote([card])
        assert result is card

    def test_vote_empty(self):
        assert CardAggregator.vote([]) is None

    def test_weighted_score(self):
        c1 = DecisionCard(title="T", options=[
            DecisionOption(id="A", label="A", confidence=0.9),
            DecisionOption(id="B", label="B", confidence=0.5),
        ], recommendation="A")
        c2 = DecisionCard(title="T", options=[
            DecisionOption(id="A", label="A", confidence=0.3),
            DecisionOption(id="B", label="B", confidence=0.9),
        ], recommendation="B")

        # Without weights: A=0.9+0.3=1.2, B=0.5+0.9=1.4 → B wins
        result = CardAggregator.weighted_score([c1, c2])
        assert result.recommendation == "B"

        # With weights favoring c1: A=0.9*2+0.3=2.1, B=0.5*2+0.9=1.9 → A wins
        result_w = CardAggregator.weighted_score([c1, c2], weights={c1.id: 2.0})
        assert result_w.recommendation == "A"


# ── Card channel tests ─────────────────────────────────────────

class TestCardChannel:
    def test_submit_and_retrieve(self):
        card = DecisionCard(title="Test", options=[DecisionOption(id="A", label="A")])
        init_card_context()
        submit_card(card)
        retrieved = get_pending_card()
        assert retrieved is not None
        assert retrieved.id == card.id
        # After retrieval, card is cleared
        assert get_pending_card() is None

    def test_clear(self):
        card = DecisionCard(title="Test", options=[DecisionOption(id="A", label="A")])
        init_card_context()
        submit_card(card)
        clear_card_context()
        assert get_pending_card() is None

    def test_no_context(self):
        # Without init, submit_card logs warning but doesn't crash
        submit_card(DecisionCard(title="T", options=[DecisionOption(id="A", label="A")]))
        assert get_pending_card() is None


# ── DecisionLogStore tests ─────────────────────────────────────

class TestDecisionLogStore:
    def test_record_and_history(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.db")
            store = SQLiteStore(path)
            log = DecisionLogStore(store)
            rec_id = log.record("c1", "decision", "Test", "A", "Option A")
            assert rec_id.startswith("rec_")
            history = log.get_history()
            assert len(history) == 1
            assert history[0]["card_id"] == "c1"

    def test_statistics(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.db")
            log = DecisionLogStore(SQLiteStore(path))
            log.record("c1", "decision", "T1", "A", recommendation="A")
            log.record("c2", "decision", "T2", "B", recommendation="A")
            stats = log.get_statistics()
            assert stats["total"] == 2
            assert stats["accepted"] == 1  # c1: A==A ✓, c2: B!=A ✗
            assert stats["acceptance_rate"] == 0.5

    def test_record_from_card(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.db")
            log = DecisionLogStore(SQLiteStore(path))
            card = DecisionCard(
                title="Test", options=[DecisionOption(id="A", label="A")],
                recommendation="A",
            )
            card.decide("A")
            rec_id = log.record_from_card(card, "A")
            history = log.get_history()
            assert len(history) == 1
