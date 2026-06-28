"""PeerReviewTool — agent evaluates another agent's output.

Gives agents the ability to:
    - read another agent's result
    - evaluate against criteria
    - return a structured verdict (pass / revise / reject)

This is the foundation for critic-executor patterns.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ember_core.tools.base import BaseTool


class PeerReviewTool(BaseTool):
    """Tool: an agent reviews another agent's output.

    The tool reads the target agent's result from the registry and
    evaluates it against caller-specified criteria.

    Returns a structured verdict with score, issues, and suggestion.
    """

    def __init__(self, registry):
        """Args:
            registry: AgentRegistry instance for looking up agent results.
        """
        self._registry = registry

    @property
    def name(self) -> str:
        return "peer_review"

    @property
    def description(self) -> str:
        return (
            "Review another agent's output against specified criteria. "
            "Returns a structured verdict: pass, revise, or reject, "
            "with specific issues and suggestions."
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target_agent_id": {
                    "type": "string",
                    "description": "ID of the agent whose output to review",
                },
                "criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Review criteria, e.g. ['correctness', 'completeness', 'clarity']",
                },
                "focus_areas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific areas to focus on, e.g. ['error handling', 'performance']",
                },
            },
            "required": ["target_agent_id", "criteria"],
        }

    def execute(
        self,
        target_agent_id: str,
        criteria: List[str],
        focus_areas: List[str] = None,
        **kwargs,
    ) -> str:
        """Look up agent output and return it for review.

        The actual review is performed by the calling LLM — this tool
        fetches the content and frames it for evaluation.
        """
        ctx = self._registry.get(target_agent_id)
        if ctx is None:
            return (
                f"Error: Agent '{target_agent_id}' not found in registry. "
                "Available agents: check list_subagents."
            )

        if ctx.status not in ("completed", "failed"):
            return (
                f"Agent '{target_agent_id}' is still {ctx.status}. "
                "Wait for completion before reviewing."
            )

        result_text = ctx.result or "(no output)"

        focus = ""
        if focus_areas:
            focus = f"\nFocus areas: {', '.join(focus_areas)}"

        review_context = (
            f"## Peer Review Request\n\n"
            f"**Agent**: {target_agent_id}\n"
            f"**Status**: {ctx.status}\n"
            f"**Task**: {ctx.task[:500]}\n\n"
            f"**Output**:\n```\n{result_text[:3000]}\n```\n\n"
            f"**Review Criteria**: {', '.join(criteria)}{focus}\n\n"
            f"Please evaluate the output and return a verdict:\n"
            f"- Verdict: PASS / REVISE / REJECT\n"
            f"- Score: 0-10\n"
            f"- Issues: list specific problems\n"
            f"- Suggestions: actionable improvements"
        )

        return review_context
