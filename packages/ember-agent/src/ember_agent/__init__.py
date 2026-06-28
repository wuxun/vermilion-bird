"""ember-agent — Multi-agent collaboration framework built on ember-core.

Subpackages:
    agent       — AgentContext, AgentRegistry, AgentRole, SharedBlackboard
    workflow    — WorkflowNode, WorkflowExecutor, AgentWorkflow
    consensus   — DecisionCard, SubmitCardTool, CardAggregator, DecisionLogStore
    peer        — PeerReviewTool, PeerDialogue

Top-level:
    CollaborationPattern — YAML-definable multi-agent orchestration recipes
    (research, debate, review, compare, pipeline, critique_refine)
"""

from ember_agent.patterns import (
    CollaborationPattern, PatternStage,
    register_pattern, get_pattern, list_patterns,
    load_patterns_from_yaml,
)

# No __all__ here — submodule imports are the primary API
