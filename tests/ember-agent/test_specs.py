"""Canonical AgentProfile and WorkflowSpec compatibility tests."""

from ember_agent.agent import AgentProfile, AgentRole
from ember_agent.patterns import CollaborationPattern, PatternStage
from ember_agent.workflow import WorkflowNodeSpec, WorkflowSpec


def test_role_converts_to_canonical_profile():
    role = AgentRole(
        name="Researcher",
        system_prompt="Research carefully.",
        default_tools=["web_search"],
        metadata={"owner": "team"},
    )

    profile = role.to_profile(key="researcher")

    assert isinstance(profile, AgentProfile)
    assert profile.tools == ["web_search"]
    assert profile.metadata == {"owner": "team", "role": "researcher"}


def test_workflow_spec_accepts_canonical_names():
    spec = WorkflowSpec(
        name="research",
        description="research flow",
        nodes=[
            WorkflowNodeSpec(
                id="researcher",
                profile="researcher",
            )
        ],
        aggregator_profile="synthesizer",
    )

    assert spec.nodes[0].profile == "researcher"
    assert spec.stages[0].role == "researcher"
    assert spec.aggregator_role == "synthesizer"


def test_collaboration_pattern_is_legacy_view_of_workflow_spec():
    pattern = CollaborationPattern(
        name="legacy",
        description="legacy syntax",
        stages=[PatternStage(id="worker", role="executor")],
        aggregator_role="synthesizer",
    )

    assert isinstance(pattern, WorkflowSpec)
    assert pattern.nodes[0].profile == "executor"
    assert pattern.stages[0].role == "executor"
    assert pattern.aggregator_profile == "synthesizer"
    dumped = pattern.model_dump()
    assert "nodes" in dumped
    assert "stages" not in dumped
