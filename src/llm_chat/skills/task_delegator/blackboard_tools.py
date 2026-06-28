"""Blackboard tools — agent-to-agent communication via SharedBlackboard.

Sub-agents get these tools automatically to:
- post_finding: share a discovery with other agents
- query_findings: search what other agents have found

The blackboard is scoped per conversation/task, so agents working
on the same task can discover and build on each other's findings.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, TYPE_CHECKING

from llm_chat.tools.base import BaseTool

if TYPE_CHECKING:
    from ember_agent.agent.blackboard import SharedBlackboard

logger = logging.getLogger(__name__)


class PostFindingTool(BaseTool):
    """Tool for sub-agents to post findings to the shared blackboard."""

    def __init__(self, blackboard: "SharedBlackboard"):
        self._bb = blackboard

    @property
    def name(self) -> str:
        return "post_finding"

    @property
    def description(self) -> str:
        return (
            "Post a finding to the shared workspace. Other agents working on "
            "the same task can discover this. Use when you find a key piece "
            "of information that might help other agents."
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Short label for the finding, e.g. 'market_size_2025'",
                },
                "value": {
                    "type": "string",
                    "description": "The finding content. Can be structured text.",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence 0.0-1.0. Use 0.9+ for verified facts, 0.5-0.7 for estimates.",
                    "default": 0.7,
                },
            },
            "required": ["key", "value"],
        }

    def execute(self, **kwargs) -> str:
        from ember_agent.agent.blackboard import BlackboardEntry, EntryType

        key = kwargs.get("key", "unknown")
        value = kwargs.get("value", "")
        confidence = kwargs.get("confidence", 0.7)

        entry = BlackboardEntry(
            key=key,
            value=value,
            entry_type=EntryType.FINDING,
            confidence=confidence,
            tags=[key],
        )
        entry_id = self._bb.post(entry)
        logger.info(f"Blackboard: posted '{key}' (confidence={confidence})")
        return json.dumps({
            "posted": True,
            "entry_id": entry_id,
            "key": key,
            "message": f"Finding '{key}' posted. {len(self._bb)} entries total.",
        }, ensure_ascii=False)


class QueryFindingsTool(BaseTool):
    """Tool for sub-agents to search the shared blackboard."""

    def __init__(self, blackboard: "SharedBlackboard"):
        self._bb = blackboard

    @property
    def name(self) -> str:
        return "query_findings"

    @property
    def description(self) -> str:
        return (
            "Search the shared workspace for findings posted by other agents. "
            "Use when you need to check if another agent has already discovered "
            "relevant information. Returns up to 5 results sorted by confidence."
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keywords, e.g. 'market size' or 'competitor'",
                },
            },
            "required": ["query"],
        }

    def execute(self, **kwargs) -> str:
        query = kwargs.get("query", "")
        results = self._bb.query(query, top_k=5)

        if not results:
            return json.dumps({
                "results": [],
                "message": f"No findings match '{query}'. Try broader keywords.",
            }, ensure_ascii=False)

        formatted = []
        for r in results:
            formatted.append({
                "key": r.key,
                "value": str(r.value)[:300],
                "confidence": r.confidence,
                "entry_id": r.id,
            })

        return json.dumps({
            "results": formatted,
            "total": len(self._bb),
            "matched": len(results),
        }, ensure_ascii=False, indent=2)
