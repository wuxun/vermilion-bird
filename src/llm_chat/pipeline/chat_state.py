"""ChatGraphState — Pydantic model for ChatCore StateGraph routing."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ChatRoutingState(BaseModel):
    """Minimal routing state for ChatCore StateGraph."""

    intent: str = ""
    skip_llm: bool = False
    should_short_circuit: bool = False

    # Tool loop tracking
    tool_call_count: int = 0
    max_tool_iterations: int = 10
    has_tool_calls: bool = False  # Set by LLM node when tool_calls detected

    has_response: bool = False

    def needs_tool_execution(self) -> bool:
        """Should we execute tools (another iteration)?"""
        return self.has_tool_calls and self.tool_call_count < self.max_tool_iterations
