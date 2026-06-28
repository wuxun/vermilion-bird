# ember-agent

Multi-agent collaboration framework built on ember-core.

## Packages

- **agent** — `AgentContext`, `AgentRegistry`, `AgentRole` (planner/executor/critic/synthesizer), `SharedBlackboard`
- **workflow** — `WorkflowNode`, `WorkflowExecutor`, `AgentWorkflow`
- **consensus** — `DecisionCard`, `CardAggregator` (vote/weighted_score/synthesize), `SubmitCardTool`
- **peer** — `PeerReviewTool`, `PeerDialogue`
- **patterns** — `CollaborationPattern` (6 built-in + YAML-extensible)

## Philosophy

**Zero LLM awareness.** ember-agent defines agent structure and collaboration patterns but never calls an LLM directly. It depends on ember-core for infrastructure. The caller provides LLM-backed implementations.

## Install

```bash
pip install ember-agent
```

## Usage

```python
from ember_agent.agent.role import AgentRole, get_preset
from ember_agent.patterns import CollaborationPattern, get_pattern
from ember_agent.consensus import CardAggregator, DecisionCard

# Use preset roles
planner = get_preset("planner")

# Use collaboration patterns
pattern = get_pattern("research")

# Aggregate multi-agent decisions
final = CardAggregator.weighted_score(cards, weights={"expert": 2.0})
```
