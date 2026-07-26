"""Canonical reusable agent profile."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AgentProfile(BaseModel):
    """Instructions, model/context policy and capabilities for one agent."""

    name: str
    description: str = ""
    system_prompt: str
    tools: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    model: Optional[str] = None
    complexity: Optional[str] = None
    context_policy: Dict[str, Any] = Field(default_factory=dict)
    capability_policy: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")
