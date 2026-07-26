"""GhostConfig — Pydantic model for reusable agent profiles.

Inspired by Wegent's Ghost CRD: a Ghost is a reusable persona
definition that can be referenced by name in SpawnSubagentTool.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class GhostConfig(BaseModel):
    """A reusable agent profile stored as a YAML file.

    Ghosts decouple agent definition from code. A ghost can be:
    - Created via CLI (`vermilion-bird ghost create`)
    - Loaded at startup from ~/.vermilion-bird/ghosts/
    - Referenced in SpawnSubagentTool via `ghost="name"`
    - Shared as YAML files between users

    Example YAML:
        name: "Senior Code Reviewer"
        description: "Reviews code for bugs, style, and architecture"
        system_prompt: |
            You are a senior code reviewer. For each review:
            1. Check for correctness and edge cases
            2. Evaluate code style and readability
            3. Assess architectural fit
            4. Suggest concrete improvements
        tools: [file_reader, file_writer, shell_exec]
        model: gpt-4o
        complexity: complex
        metadata:
            tags: [code, review]
            version: "1.0"
    """

    name: str = Field(description="Human-readable display name, e.g. 'Deep Researcher'")
    description: str = Field(
        default="",
        description="Brief description of what this ghost does",
    )
    system_prompt: str = Field(
        description="Core system prompt defining the agent's personality and behavior",
    )
    tools: List[str] = Field(
        default_factory=list,
        description="Default tool names available to this ghost",
    )
    model: Optional[str] = Field(
        default=None,
        description="Preferred model name, e.g. 'gpt-4o-mini' or 'claude-3-5-sonnet'",
    )
    skills: List[str] = Field(
        default_factory=list,
        description="Optional skill names to activate for this ghost",
    )
    complexity: Optional[str] = Field(
        default=None,
        description="Task complexity hint: simple, moderate, or complex",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata (tags, version, author, etc.)",
    )

    @classmethod
    def from_yaml_dict(cls, data: Dict[str, Any]) -> "GhostConfig":
        """Create a GhostConfig from a YAML-loaded dict, with defaults."""
        return cls(**data)

    def to_yaml_dict(self) -> Dict[str, Any]:
        """Serialize to a dict suitable for YAML dumping."""
        d = self.model_dump(exclude_none=True, exclude_defaults=False)
        # Remove empty defaults to keep YAML clean
        if not d.get("description"):
            d.pop("description", None)
        if not d.get("skills"):
            d.pop("skills", None)
        if not d.get("metadata"):
            d.pop("metadata", None)
        if d.get("tools") == []:
            d.pop("tools", None)
        return d
