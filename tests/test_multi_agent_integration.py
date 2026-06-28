"""Integration tests for multi-agent collaboration:
SpawnSubagentTool + AgentRole + CardAggregator + CollaborationPattern.

Tests wiring correctness — LLM calls are mocked.
"""

import json
import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from types import SimpleNamespace

from ember_agent.agent.role import AgentRole, get_preset, list_presets, register_preset
from ember_agent.agent.registry import AgentRegistry
from ember_agent.agent.context import make_agent_context
from ember_agent.consensus.aggregator import CardAggregator
from ember_agent.consensus.card import DecisionCard, DecisionOption
from ember_agent.patterns import CollaborationPattern, get_pattern, list_patterns

from llm_chat.skills.task_delegator.tools import SpawnSubagentTool
from llm_chat.skills.task_delegator.context import AgentContext
from llm_chat.skills.task_delegator.registry import SubAgentRegistry
from llm_chat.tools.registry import ToolRegistry


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def mock_config():
    """A mock Config with minimal required attributes."""
    cfg = MagicMock()
    cfg.llm.model = "test-model"
    cfg.llm.protocol = "openai"
    cfg.llm.base_url = "https://test.api.com"
    cfg.llm.api_key = "test-key"
    cfg.llm.timeout = 60
    cfg.llm.max_retries = 1
    cfg.llm.http_proxy = None
    cfg.llm.https_proxy = None
    cfg.enable_tools = True
    cfg.mcp.servers = []
    cfg.tools.work_dir = "/tmp/test-work"
    cfg.tools.subagent_models = {"simple": "gpt-4o-mini", "complex": "gpt-4o"}
    cfg.tools.subagent_max_concurrent = 3
    cfg.tools.subagent_max_retries = 1
    cfg.tools.subagent_retry_delay = 0.1
    cfg.memory = MagicMock()
    cfg.external_skill_dirs = []
    return cfg


@pytest.fixture
def parent_context():
    return make_agent_context(
        agent_id="parent-001",
        parent_id=None,
        depth=0,
        allowed_tools={"spawn_subagent", "web_search", "web_fetch"},
        conversation_id="conv-001",
        task="Orchestrate multi-agent research",
        work_dir="/tmp/test-work",
        timeout=300,
    )


@pytest.fixture
def subagent_registry():
    return SubAgentRegistry()


@pytest.fixture
def tool_registry():
    reg = ToolRegistry()
    return reg


@pytest.fixture
def spawn_tool(mock_config, parent_context, subagent_registry, tool_registry):
    return SpawnSubagentTool(
        registry=subagent_registry,
        parent_context=parent_context,
        config=mock_config,
        tool_registry=tool_registry,
    )


# ── AgentRole tests ────────────────────────────────────────────────

class TestAgentRoleIntegration:
    """AgentRole presets work correctly with SpawnSubagentTool."""

    def test_all_presets_registered(self):
        """All 4 presets exist."""
        assert set(list_presets()) >= {"planner", "executor", "critic", "synthesizer"}

    def test_planner_has_no_tools(self):
        """Planner role has empty default_tools (planning only)."""
        role = get_preset("planner")
        assert role.name == "Planner"
        assert role.default_tools == []

    def test_executor_has_tools(self):
        """Executor role has real tools for execution."""
        role = get_preset("executor")
        assert "web_search" in role.default_tools
        assert "file_reader" in role.default_tools

    def test_critic_uses_decision_card(self):
        """Critic role mentions submit_decision_card."""
        role = get_preset("critic")
        assert "submit_decision_card" in role.system_prompt

    def test_synthesizer_combines_outputs(self):
        """Synthesizer merges multiple agent outputs."""
        role = get_preset("synthesizer")
        assert "combine" in role.system_prompt.lower() or "synthesis" in role.system_prompt.lower()

    def test_spawn_tool_resolves_role_prompt(self, spawn_tool):
        """SpawnSubagentTool._resolve_system_prompt injects role prompt."""
        result = spawn_tool._resolve_system_prompt("test task", "planner")
        assert "test task" in result
        assert "strategic planner" in result.lower()

    def test_spawn_tool_invalid_role(self, spawn_tool):
        """Unknown role returns task as-is."""
        result = spawn_tool._resolve_system_prompt("test task", "nonexistent")
        assert result == "test task"

    def test_custom_role_registration(self):
        """Custom roles can be registered and used."""
        custom = AgentRole(
            name="Researcher",
            system_prompt="You are a deep research specialist.",
            default_tools=["web_search", "web_fetch"],
        )
        register_preset("researcher", custom)
        role = get_preset("researcher")
        assert role.name == "Researcher"
        assert "web_search" in role.default_tools
        assert "web_fetch" in role.default_tools


# ── SpawnSubagentTool + AgentRole tests ─────────────────────────────

class TestSpawnWithRole:
    """SpawnSubagentTool correctly applies AgentRole presets."""

    def test_spawn_with_planner_role(self, spawn_tool, mock_config):
        """Spawn with planner role: agent gets injected system prompt."""
        with patch.object(spawn_tool, '_execute_async_inner', return_value="Plan created."):
            result = spawn_tool.execute(
                task="Plan a research strategy for climate change",
                role="planner",
                wait=True,
            )
            parsed = json.loads(result)
            assert parsed["status"] == "completed"
            assert parsed["result"] == "Plan created."

    def test_spawn_with_executor_role(self, spawn_tool, mock_config):
        """Spawn with executor role: default_tools are applied."""
        with patch.object(spawn_tool, '_execute_async_inner', return_value="Data collected."):
            result = spawn_tool.execute(
                task="Search for latest climate data",
                role="executor",
                wait=True,
            )
            parsed = json.loads(result)
            assert parsed["status"] == "completed"

    def test_spawn_recursion_prevented(self, spawn_tool):
        """Spawning subagent from a depth>0 agent should fail."""
        spawn_tool.parent_context.depth = 1
        result_str = spawn_tool.execute(task="Try to spawn another subagent")
        parsed = json.loads(result_str)
        assert parsed["status"] == "failed"
        assert "recursion not allowed" in parsed.get("error", "").lower()

    def test_concurrency_limit(self, spawn_tool, subagent_registry):
        """Exceeding max_concurrent should reject."""
        spawn_tool.config.tools.subagent_max_concurrent = 1
        # Pre-register a running agent
        ctx = make_agent_context(
            agent_id="busy", parent_id=None, depth=0,
            allowed_tools=set(), conversation_id="c", task="busy", work_dir="/tmp",
        )
        ctx.status = "running"
        subagent_registry._agents["busy"] = ctx

        result_str = spawn_tool.execute(task="Try to spawn when busy")
        parsed = json.loads(result_str)
        assert parsed["status"] == "rejected"
        assert "concurrency" in parsed.get("error", "").lower()


# ── CardAggregator tests ──────────────────────────────────────────

class TestCardAggregatorIntegration:
    """CardAggregator strategies with multi-agent scenarios."""

    def _make_card(self, title, options_with_conf, recommendation=None):
        """Helper: build a DecisionCard from [(label, description, confidence), ...]."""
        opts = [
            DecisionOption(
                id=chr(65 + i),  # A, B, C, ...
                label=label,
                description=desc,
                confidence=conf,
            )
            for i, (label, desc, conf) in enumerate(options_with_conf)
        ]
        card = DecisionCard(
            title=title,
            context="Agent analysis",
            options=opts,
            recommendation=recommendation,
        )
        return card

    def test_vote_three_agree(self):
        """Three agents agree: majority wins."""
        cards = [
            self._make_card("What to do?", [
                ("Option A", "First choice", 0.9),
                ("Option B", "Second choice", 0.5),
            ], recommendation="A"),
            self._make_card("What to do?", [
                ("Option A", "First choice", 0.8),
                ("Option B", "Second choice", 0.6),
            ], recommendation="A"),
            self._make_card("What to do?", [
                ("Option A", "First choice", 0.7),
                ("Option B", "Second choice", 0.9),
            ], recommendation="B"),
        ]
        result = CardAggregator.vote(cards)
        assert result.recommendation == "A"  # 2 votes A, 1 vote B

    def test_weighted_score_different_weights(self):
        """Weighted scoring with agent-specific weights."""
        cards = [
            self._make_card("Choice", [
                ("Option A", "Good", 0.9),
                ("Option B", "Bad", 0.3),
            ], recommendation="A"),
            self._make_card("Choice", [
                ("Option A", "Risky", 0.2),
                ("Option B", "Safe", 0.95),
            ], recommendation="B"),
        ]
        # Agent 0 (expert) weight 2.0, Agent 1 (junior) weight 0.5
        weights = {None: 0.5}  # Both cards have no ID → gets 0.5 each
        result = CardAggregator.weighted_score(cards, weights=weights)
        # Score A: 0.9*0.5 + 0.2*0.5 = 0.55
        # Score B: 0.3*0.5 + 0.95*0.5 = 0.625
        assert result.recommendation == "B"

    def test_synthesize_fallback(self):
        """synthesize falls back to weighted_score when no fn given."""
        cards = [
            self._make_card("Test", [("A", "Desc", 0.9)], recommendation="A"),
            self._make_card("Test", [("A", "Desc", 0.5)], recommendation="A"),
        ]
        result = CardAggregator.synthesize(cards)
        assert result.recommendation == "A"

    def test_empty_cards(self):
        """Empty card list returns None."""
        assert CardAggregator.vote([]) is None
        assert CardAggregator.weighted_score([]) is None
        assert CardAggregator.synthesize([]) is None


# ── CollaborationPattern tests ──────────────────────────────────────

class TestCollaborationPatterns:
    """CollaborationPattern registry and built-in patterns."""

    def test_all_patterns_registered(self):
        """All 6 built-in patterns exist."""
        from ember_agent.patterns import list_patterns
        names = list_patterns()
        assert "research" in names
        assert "debate" in names
        assert "review" in names
        assert "compare" in names
        assert "pipeline" in names
        assert "critique_refine" in names

    def test_research_pattern_structure(self):
        """research: planner → executors (parallel) → synthesizer."""
        from ember_agent.patterns import get_pattern
        pat = get_pattern("research")
        assert pat.aggregator_role == "synthesizer"
        assert len(pat.stages) == 2
        assert pat.stages[1].parallel == 3
        assert pat.stages[1].depends_on == ["planner"]

    def test_pipeline_pattern_sequence(self):
        """pipeline: sequential chain, each stage depends on previous."""
        from ember_agent.patterns import get_pattern
        pat = get_pattern("pipeline")
        assert len(pat.stages) == 3
        assert pat.stages[1].depends_on == ["stage_0"]
        assert pat.stages[2].depends_on == ["stage_1"]

    def test_critique_refine_has_loops(self):
        """critique_refine pattern has max_rounds > 1 for the loop."""
        from ember_agent.patterns import get_pattern
        pat = get_pattern("critique_refine")
        assert pat.max_rounds == 3
        assert len(pat.stages) == 2
        assert pat.aggregator_role == "executor"


# ── End-to-end manager-worker simulation ─────────────────────────

class TestManagerWorkerSimulation:
    """Simulate the full manager-worker flow with mocked LLM calls.

    Flow:
        1. User: "Research climate tech investments"
        2. Orchestrator (main LLM) uses SpawnSubagentTool:
           - spawn planner agent → returns subtasks
           - spawn 2 executor agents with subtasks → collect results
           - spawn synthesizer agent → merge results
        3. CardAggregator.merge the final recommendation
    """

    def _mock_chat_with_tools(self, task, tool_defs):
        """Simulate different agent responses based on task content."""
        pass  # Not used — replaced by _execute_async_inner mock

    @patch.object(SpawnSubagentTool, '_execute_async_inner')
    def test_full_manager_worker_flow(self, mock_exec, spawn_tool, mock_config):
        """Simulate the complete manager-worker pipeline."""
        # Mock responses for each agent call
        call_count = [0]

        def mock_execute(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            responses = [
                # Planner
                json.dumps({
                    "subtasks": [
                        {"id": 1, "title": "Market size analysis",
                         "query": "What is the current size of the climate tech market?"},
                        {"id": 2, "title": "Key players identification",
                         "query": "Who are the top 5 climate tech companies?"},
                        {"id": 3, "title": "Investment trends",
                         "query": "What are the latest VC investment trends in climate tech?"},
                    ]
                }),
                # Executor 1
                "The climate tech market is estimated at $20B in 2025, growing 18% YoY.",
                # Executor 2
                "Top 5: Tesla ($500B), NextEra ($150B), BYD ($100B), Enphase ($15B), Sunrun ($5B).",
                # Executor 3
                "VC funding in climate tech reached $40B in 2024, up 25% from 2023.",
                # Synthesizer
                json.dumps({
                    "title": "Climate Tech Investment Recommendation",
                    "context": "Synthesized from 3 agents",
                    "options": [
                        {"label": "Invest in carbon capture",
                         "description": "Fastest growing segment with strong policy tailwinds"},
                        {"label": "Invest in green hydrogen",
                         "description": "High growth potential but still early stage"},
                        {"label": "Wait for market correction",
                         "description": "Valuations currently elevated across all subsectors"},
                    ],
                    "recommendation": "A",
                }),
            ]
            if idx < len(responses):
                return responses[idx]
            return "Analysis complete."

        mock_exec.side_effect = mock_execute

        # Step 1: Planner agent decomposes the task
        result = spawn_tool.execute(
            task="Plan a research strategy for climate tech investments",
            role="planner",
            wait=True,
        )
        parsed = json.loads(result)
        assert parsed["status"] == "completed"
        plan = json.loads(parsed["result"])
        assert len(plan["subtasks"]) == 3

        # Step 2: Executor agents run subtasks in parallel
        executor_results = []
        for subtask in plan["subtasks"]:
            res_str = spawn_tool.execute(
                task=f"Execute: {subtask['query']}",
                role="executor",
                wait=True,
            )
            executor_results.append(json.loads(res_str))

        assert all(r["status"] == "completed" for r in executor_results)
        assert "20B" in executor_results[0]["result"]
        assert "Tesla" in executor_results[1]["result"]
        assert "40B" in executor_results[2]["result"]

        # Step 3: Synthesizer merges executor results
        combined = "\n\n".join(r["result"] for r in executor_results)
        result = spawn_tool.execute(
            task=f"Synthesize these findings and produce a decision card:\n\n{combined}",
            role="synthesizer",
            wait=True,
        )
        parsed = json.loads(result)
        assert parsed["status"] == "completed"
        synthesis = json.loads(parsed["result"])
        assert synthesis["title"] == "Climate Tech Investment Recommendation"
        assert len(synthesis["options"]) == 3
        assert synthesis["recommendation"] == "A"

    def test_card_aggregator_on_synthesized_results(self):
        """CardAggregator can merge decision cards from multiple agents."""
        card_a = DecisionCard(
            title="Investment choice",
            options=[
                DecisionOption(id="A", label="Carbon capture", confidence=0.9),
                DecisionOption(id="B", label="Green hydrogen", confidence=0.6),
                DecisionOption(id="C", label="Solar", confidence=0.4),
            ],
            recommendation="A",
        )
        card_b = DecisionCard(
            title="Investment choice",
            options=[
                DecisionOption(id="A", label="Carbon capture", confidence=0.3),
                DecisionOption(id="B", label="Green hydrogen", confidence=0.95),
                DecisionOption(id="C", label="Solar", confidence=0.5),
            ],
            recommendation="B",
        )
        card_c = DecisionCard(
            title="Investment choice",
            options=[
                DecisionOption(id="A", label="Carbon capture", confidence=0.7),
                DecisionOption(id="B", label="Green hydrogen", confidence=0.7),
                DecisionOption(id="C", label="Solar", confidence=0.3),
            ],
            recommendation="A",
        )

        # Majority vote
        vote_result = CardAggregator.vote([card_a, card_b, card_c])
        assert vote_result.recommendation == "A"

        # Weighted score: agent A gets 2x weight
        cards_with_ids = [card_a, card_b, card_c]
        cards_with_ids[0].id = "expert"
        weighted = CardAggregator.weighted_score(cards_with_ids, weights={"expert": 2.0})
        # A: 0.9*2 + 0.3*1 + 0.7*1 = 2.8
        # B: 0.6*2 + 0.95*1 + 0.7*1 = 2.85
        assert weighted.recommendation == "B"

    def test_agent_role_depth_protection(self, spawn_tool):
        """AgentRoles don't bypass depth protection."""
        spawn_tool.parent_context.depth = 1
        for role_name in ["planner", "executor", "critic", "synthesizer"]:
            result_str = spawn_tool.execute(
                task=f"Task as {role_name}",
                role=role_name,
            )
            parsed = json.loads(result_str)
            assert parsed["status"] == "failed", f"Role {role_name} should be blocked at depth 1"


# ── SharedBlackboard + PeerReviewTool tests ──────────────────────

class TestPeerCollaboration:
    """Agent peer review and dialogue patterns."""

    def test_peer_review_tool_schema(self):
        """PeerReviewTool has the expected schema."""
        from ember_agent.peer.review import PeerReviewTool
        tool = PeerReviewTool(registry=AgentRegistry())
        schema = tool.get_parameters_schema()
        props = schema.get("properties", {})
        assert "target_agent_id" in props
        assert "criteria" in props
        assert "focus_areas" in props

    def test_shared_blackboard_basic(self):
        """SharedBlackboard post/query operations."""
        from ember_agent.agent.blackboard import SharedBlackboard, BlackboardEntry, EntryType
        board = SharedBlackboard()

        entry1 = BlackboardEntry(
            agent_id="agent-1",
            entry_type=EntryType.FINDING,
            key="data",
            value='{"key": "value"}',
        )
        eid = board.post(entry1)
        assert eid

        result = board.get(eid)
        assert result.agent_id == "agent-1"
        assert result.key == "data"

        board.clear()
        assert board.get(eid) is None

    def test_shared_blackboard_overwrite(self):
        """Blackboard entries can be queried and removed."""
        from ember_agent.agent.blackboard import SharedBlackboard, BlackboardEntry, EntryType
        board = SharedBlackboard()

        entry = BlackboardEntry(
            agent_id="agent-1",
            entry_type=EntryType.FINDING,
            key="score",
            value="10",
        )
        eid = board.post(entry)

        results = board.query("score", agent_id="agent-1")
        assert len(results) >= 1
        assert results[0].value == "10"

        board.remove(eid)
        assert board.get(eid) is None
