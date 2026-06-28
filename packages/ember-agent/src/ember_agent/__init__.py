"""ember-agent — Multi-agent collaboration framework built on ember-core.

Subpackages:
    agent       — AgentContext, AgentRegistry, AgentRole, SharedBlackboard
    workflow    — WorkflowNode, WorkflowExecutor, AgentWorkflow
    consensus   — DecisionCard, SubmitCardTool, CardAggregator, DecisionLogStore
    peer        — PeerReviewTool, PeerDialogue

Top-level:
    MultiAgentPattern — manager_worker / debate / pipeline / critique_refine
"""

from ember_agent.patterns import MultiAgentPattern

# No __all__ here — submodule imports are the primary API
