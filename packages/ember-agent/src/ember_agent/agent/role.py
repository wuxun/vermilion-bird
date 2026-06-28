"""AgentRole — typed agent persona definition.

An AgentRole defines:
    - name: human-readable role name
    - system_prompt: role-specific system instructions
    - default_tools: tools available to this role type
    - output_schema: optional Pydantic model for structured output

Preset roles: planner, executor, critic, synthesizer
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Type

from pydantic import BaseModel, Field, ConfigDict


# ── Preset registry (module-level, not on the model class) ────────

_PRESETS: Dict[str, "AgentRole"] = {}


def register_preset(key: str, role: "AgentRole") -> None:
    """Register a named preset role."""
    _PRESETS[key] = role


def get_preset(key: str) -> Optional["AgentRole"]:
    """Get a preset role by key."""
    return _PRESETS.get(key)


def list_presets() -> List[str]:
    """List all registered preset keys."""
    return list(_PRESETS.keys())


# ── AgentRole model ───────────────────────────────────────────────

class AgentRole(BaseModel):
    """Defines an agent's persona and capabilities.

    Usage:
        role = AgentRole(
            name="Code Reviewer",
            system_prompt="You are a senior code reviewer...",
            default_tools=["file_reader", "grep"],
        )

        # Or use a preset:
        role = get_preset("critic")
    """

    name: str = Field(description="Human-readable role name, e.g. 'Code Reviewer'")
    system_prompt: str = Field(
        description="Role-specific system instructions"
    )
    default_tools: List[str] = Field(
        default_factory=list,
        description="Tool names available to agents of this role",
    )
    output_schema: Optional[Type[BaseModel]] = Field(
        default=None,
        description="Optional Pydantic model for structured output",
        exclude=True,
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary role metadata (routing, weights, etc.)",
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


# ── Built-in presets ────────────────────────────────────────────────

register_preset(
    "planner",
    AgentRole(
        name="Planner",
        system_prompt=(
            "You are a strategic planner. Your role is to decompose complex tasks "
            "into clear, actionable subtasks. For each subtask, specify:\n"
            "- What needs to be done\n"
            "- What tools are needed\n"
            "- What the expected output should look like\n\n"
            "Be concise and structured. Do not execute the subtasks yourself — "
            "your output will be used to assign work to executor agents."
        ),
        default_tools=[],
    ),
)

register_preset(
    "executor",
    AgentRole(
        name="Executor",
        system_prompt=(
            "You are a task executor. You receive a specific subtask with clear "
            "instructions and tools. Execute it thoroughly and return the result. "
            "If you encounter ambiguity, make reasonable assumptions and note them. "
            "If you cannot complete the task with available tools, explain why."
        ),
        default_tools=["file_reader", "file_writer", "web_search", "shell_exec"],
    ),
)

register_preset(
    "critic",
    AgentRole(
        name="Critic",
        system_prompt=(
            "You are a critical reviewer. Your role is to examine outputs from "
            "other agents and identify:\n"
            "- Factual errors or unsupported claims\n"
            "- Logical inconsistencies\n"
            "- Missing edge cases or unhandled scenarios\n"
            "- Opportunities for improvement\n\n"
            "Be constructive but rigorous. Rate the output on correctness, "
            "completeness, and clarity. Use submit_decision_card for verdict."
        ),
        default_tools=["file_reader", "web_search"],
    ),
)

register_preset(
    "synthesizer",
    AgentRole(
        name="Synthesizer",
        system_prompt=(
            "You are a synthesis agent. You receive outputs from multiple agents "
            "and combine them into a coherent, unified result. Your job is to:\n"
            "- Identify agreements and resolve contradictions\n"
            "- Eliminate redundancy across inputs\n"
            "- Produce a single, well-structured final output\n"
            "- Note any unresolved disagreements\n\n"
            "Be fair and balanced. Do not favor any single source without reason."
        ),
        default_tools=["file_writer"],
    ),
)
