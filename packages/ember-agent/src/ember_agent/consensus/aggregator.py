"""CardAggregator — merge multiple DecisionCards into consensus.

Three strategies:
    vote           — majority rule: option with most selections wins
    weighted_score — confidence × weight: highest total score wins
    synthesize     — LLM-driven: feed all cards to a synthesizer agent

Usage:
    cards = [card_from_agent_a, card_from_agent_b, card_from_agent_c]
    final = CardAggregator.weighted_score(cards, weights={"a": 1.0, "b": 0.7})
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ember_agent.consensus.card import DecisionCard, DecisionOption


class CardAggregator:
    """Strategies for merging multiple DecisionCards into one."""

    @staticmethod
    def vote(cards: List[DecisionCard]) -> Optional[DecisionCard]:
        """Majority vote: each card's recommended option gets one vote.

        Returns a new DecisionCard with the winning option as recommendation.
        Returns None if cards is empty.
        """
        if not cards:
            return None

        if len(cards) == 1:
            return cards[0]

        votes: Dict[str, int] = {}
        for card in cards:
            if card.recommendation:
                votes[card.recommendation] = votes.get(card.recommendation, 0) + 1

        if not votes:
            return cards[0]

        winner_id = max(votes, key=votes.get)
        winner_option = None
        for card in cards:
            for opt in card.options:
                if opt.id == winner_id:
                    winner_option = opt
                    break
            if winner_option:
                break

        # Collect all unique options across cards
        all_options: Dict[str, DecisionOption] = {}
        for card in cards:
            for opt in card.options:
                if opt.id not in all_options:
                    all_options[opt.id] = opt

        # Build result
        result = DecisionCard(
            title=cards[0].title,
            context=f"Consensus from {len(cards)} agents. "
                    f"Votes: {votes}. Winner: {winner_id} ({votes[winner_id]} votes).",
            options=list(all_options.values()),
            recommendation=winner_id,
            sources=sum((c.sources for c in cards), []),
        )
        return result

    @staticmethod
    def weighted_score(
        cards: List[DecisionCard],
        weights: Optional[Dict[str, float]] = None,
    ) -> Optional[DecisionCard]:
        """Weighted scoring: each option's confidence × agent weight.

        Args:
            cards: DecisionCards from different agents.
            weights: {agent_id: weight} for each agent. Default weight = 1.0.

        Returns:
            New DecisionCard with highest-scoring option as recommendation.
        """
        if not cards:
            return None

        if len(cards) == 1:
            return cards[0]

        weights = weights or {}
        scores: Dict[str, float] = {}

        for card in cards:
            agent_weight = weights.get(card.id, 1.0)
            for opt in card.options:
                score = opt.confidence * agent_weight
                scores[opt.id] = scores.get(opt.id, 0.0) + score

        if not scores:
            return cards[0]

        winner_id = max(scores, key=scores.get)

        # Collect options
        all_options: Dict[str, DecisionOption] = {}
        for card in cards:
            for opt in card.options:
                if opt.id not in all_options:
                    all_options[opt.id] = opt

        score_detail = ", ".join(
            f"{oid}={s:.2f}" for oid, s in
            sorted(scores.items(), key=lambda x: x[1], reverse=True)
        )

        result = DecisionCard(
            title=cards[0].title,
            context=f"Weighted consensus from {len(cards)} agents. "
                    f"Scores: [{score_detail}]. Winner: {winner_id}.",
            options=list(all_options.values()),
            recommendation=winner_id,
            sources=sum((c.sources for c in cards), []),
        )
        return result

    @staticmethod
    def synthesize(
        cards: List[DecisionCard],
        synthesizer_fn=None,
    ) -> Optional[DecisionCard]:
        """LLM-driven synthesis: feed all cards to a synthesizer.

        Args:
            cards: DecisionCards from multiple agents.
            synthesizer_fn: Callable that takes (context_str, options_list)
                           and returns a synthesized DecisionCard.
                           If None, falls back to weighted_score.

        Returns:
            Synthesized DecisionCard.
        """
        if not cards:
            return None

        if len(cards) == 1 or synthesizer_fn is None:
            return CardAggregator.weighted_score(cards)

        # Build context for the synthesizer
        context_parts = [f"## Synthesis required from {len(cards)} agents\n"]
        for i, card in enumerate(cards):
            context_parts.append(f"### Agent {i + 1}")
            context_parts.append(f"Recommendation: {card.recommendation or 'none'}")
            for opt in card.options:
                context_parts.append(
                    f"  - [{opt.id}] {opt.label} "
                    f"(confidence: {opt.confidence:.0%})"
                )
                if opt.description:
                    context_parts.append(f"    {opt.description[:200]}")
            context_parts.append("")

        context_str = "\n".join(context_parts)

        # Collect all unique options
        all_options: Dict[str, DecisionOption] = {}
        for card in cards:
            for opt in card.options:
                if opt.id not in all_options:
                    all_options[opt.id] = opt

        return synthesizer_fn(context_str, list(all_options.values()))
