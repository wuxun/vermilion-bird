"""CollaborationPattern — multi-agent orchestration recipes.

Patterns define the structure of multi-agent collaboration:
    - research:       planner → [executor×N] → synthesizer
    - debate:         pro → con → judge
    - review:         creator → critic → creator (refine)
    - compare:        [analyst×N] → synthesizer
    - pipeline:       sequential chain A → B → C
    - critique_refine: creator → critic ← (loop) → creator

All patterns are YAML-extensible via config.yaml `collaboration_patterns:`.

Architecture: single source of truth. No separate StateGraph-based system.
CollaborationEngine executes patterns by spawning agents via SpawnSubagentTool.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict

import logging
logger = logging.getLogger(__name__)


# ── Schema ──────────────────────────────────────────────────────

class PatternStage(BaseModel):
    """One stage in a collaboration pattern."""
    id: str
    role: str
    task: str = "{user_task}"
    parallel: int = 1
    depends_on: List[str] = Field(default_factory=list)
    collect: str = ""  # 'concat' | 'numbered' | 'json_array'
    model_config = ConfigDict(extra="forbid")


class CollaborationPattern(BaseModel):
    """A named multi-agent collaboration template."""
    name: str
    description: str
    stages: List[PatternStage]
    aggregator_role: Optional[str] = None
    aggregator_task: Optional[str] = None
    max_parallel: int = 5
    timeout_per_agent: int = 300
    max_rounds: int = 1  # >1 enables loop
    continue_on_failure: bool = True  # If True, continue to aggregator even on failures
    model_config = ConfigDict(extra="forbid")


# ── Registry ─────────────────────────────────────────────────────

_PATTERNS: Dict[str, CollaborationPattern] = {}


def register_pattern(pattern: CollaborationPattern) -> None:
    if pattern.name in _PATTERNS:
        logger.warning(f"Pattern '{pattern.name}' exists, overwriting")
    _PATTERNS[pattern.name] = pattern


def get_pattern(name: str) -> Optional[CollaborationPattern]:
    return _PATTERNS.get(name)


def list_patterns() -> List[str]:
    return list(_PATTERNS.keys())


# ── Built-in patterns ────────────────────────────────────────────

register_pattern(CollaborationPattern(
    name="research",
    description=(
        "Planner decomposes → executors research in parallel → synthesizer merges. "
        "Best for: 调研, 对比分析, 多维度评估."
    ),
    stages=[
        PatternStage(id="planner", role="planner",
            task="Decompose: {user_task}. Output as JSON: [{\"id\":1,\"query\":\"...\"},...]"),
        PatternStage(id="executors", role="executor", parallel=3,
            task="Execute your assigned sub-task using search tools.",
            depends_on=["planner"],
            collect="numbered"),
    ],
    aggregator_role="synthesizer",
    aggregator_task=(
        "Synthesize all executor findings into one cohesive report. "
        "Output the report directly as your response text. "
        "Do NOT save to file — write it inline."
    ),
))

register_pattern(CollaborationPattern(
    name="debate",
    description="Pro argues → con argues → judge decides. Best for: 决策, 风险评估.",
    stages=[
        PatternStage(id="pro", role="executor",
            task="Argue FOR: {user_task}"),
        PatternStage(id="con", role="critic",
            task="Argue AGAINST: {user_task}\n\nThe pro argument was:\n{pro.result}",
            depends_on=["pro"]),
    ],
    aggregator_role="synthesizer",
    aggregator_task="Evaluate both sides. Produce balanced verdict.",
))

register_pattern(CollaborationPattern(
    name="review",
    description="Creator → critic → creator refine. Best for: 文案优化, 代码审查.",
    stages=[
        PatternStage(id="creator", role="planner",
            task="Create first draft: {user_task}"),
        PatternStage(id="critic", role="critic",
            task="Review this output and provide actionable feedback:\n\n{creator.result}",
            depends_on=["creator"]),
    ],
    aggregator_role="executor",
    aggregator_task="Refine based on feedback. Show before/after for key changes.",
))

register_pattern(CollaborationPattern(
    name="compare",
    description="Parallel analysis → comparison. Best for: 竞品分析, 技术选型.",
    stages=[
        PatternStage(id="analysts", role="executor", parallel=2,
            task="Analyze one aspect of: {user_task}", collect="numbered"),
    ],
    aggregator_role="synthesizer",
    aggregator_task="Compare side by side. Structured table + recommendation.",
))

register_pattern(CollaborationPattern(
    name="pipeline",
    description="Sequential chain: stage_0 → stage_1 → stage_2. Each feeds to next.",
    stages=[
        PatternStage(id="stage_0", role="planner",
            task="Plan the approach for: {user_task}"),
        PatternStage(id="stage_1", role="executor",
            task="Execute the plan from stage_0: {stage_0.result}", depends_on=["stage_0"]),
        PatternStage(id="stage_2", role="synthesizer",
            task="Polish and finalize: {stage_1.result}", depends_on=["stage_1"]),
    ],
))

register_pattern(CollaborationPattern(
    name="critique_refine",
    description="Creator → critic → (loop until quality ok). Best for: 深度打磨.",
    max_rounds=3,
    stages=[
        PatternStage(id="creator", role="executor",
            task="Create initial output for: {user_task}"),
        PatternStage(id="critic", role="critic",
            task=(
                "Review the creator's output below:\n\n{creator.result}\n\n"
                "Rate on a scale of 1-10 for quality, completeness, and polish. "
                "If all ratings >= 8, respond with 'PASS: ' followed by a brief summary. "
                "Otherwise respond with specific improvements needed. "
                "Output must start with PASS or FAIL."
            ),
            depends_on=["creator"]),
    ],
    aggregator_role="executor",
    aggregator_task="Produce the final polished version incorporating all feedback.",
))


# ── YAML loader ──────────────────────────────────────────────────

def load_patterns_from_yaml(path: str = "config.yaml") -> int:
    """Load custom patterns from config.yaml under `collaboration_patterns`."""
    try:
        from pathlib import Path
        import yaml
        config_path = Path(path)
        if not config_path.exists():
            alt = Path.home() / ".vermilion-bird" / "config.yaml"
            config_path = alt if alt.exists() else config_path
        if not config_path.exists():
            return 0
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        patterns = data.get("collaboration_patterns", {})
        count = 0
        for name, spec in patterns.items():
            if not isinstance(spec, dict):
                continue
            stages = [PatternStage(
                id=s["id"], role=s["role"],
                task=s.get("task", "{user_task}"),
                parallel=s.get("parallel", 1),
                depends_on=s.get("depends_on", []),
                collect=s.get("collect", ""),
            ) for s in spec.get("stages", [])]
            pattern = CollaborationPattern(
                name=name, description=spec.get("description", f"Pattern: {name}"),
                stages=stages, aggregator_role=spec.get("aggregator_role"),
                aggregator_task=spec.get("aggregator_task"),
                max_parallel=spec.get("max_parallel", 5),
                timeout_per_agent=spec.get("timeout_per_agent", 300),
                max_rounds=spec.get("max_rounds", 1),
                continue_on_failure=spec.get("continue_on_failure", True),
            )
            register_pattern(pattern)
            count += 1
            logger.info(f"Loaded pattern: {name}")
        return count
    except Exception as e:
        logger.warning(f"Failed to load patterns from YAML: {e}")
        return 0
