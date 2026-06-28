"""Workflow data types — DAG nodes, results, and workflow definitions.

Supports four composition patterns:
    simple        — single agent task
    parallel      — multiple agents executing concurrently
    sequence      — chain: output of stage N fed to stage N+1
    condition     — branch based on previous node result
"""

from __future__ import annotations

import uuid
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


# ── Node types ──────────────────────────────────────────────────────


class WorkflowNodeType(Enum):
    AGENT = "agent"          # Single agent task
    PARALLEL = "parallel"    # Concurrent children
    SEQUENCE = "sequence"    # Sequential children (pipeline)
    CONDITION = "condition"  # Branch based on previous result


@dataclass
class WorkflowNode:
    """One node in the workflow DAG.

    AGENT nodes: task_template, allowed_tools, model_config, timeout
    PARALLEL/SEQUENCE nodes: children list
    CONDITION nodes: condition dict, true_branch, false_branch
    """

    node_id: str
    node_type: WorkflowNodeType

    # AGENT parameters
    task_template: Optional[str] = None
    allowed_tools: List[str] = field(default_factory=list)
    model_config: Optional[Dict[str, Any]] = None
    timeout: int = 60

    # PARALLEL / SEQUENCE parameters
    children: List[WorkflowNode] = field(default_factory=list)

    # CONDITION parameters
    condition: Optional[Dict[str, Any]] = None  # {field, operator, value}
    true_branch: Optional[List[WorkflowNode]] = None
    false_branch: Optional[List[WorkflowNode]] = None

    # Common
    on_error: str = "fail"  # fail | skip

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
        }
        if self.task_template:
            result["task_template"] = self.task_template[:100]
        if self.allowed_tools:
            result["allowed_tools"] = self.allowed_tools
        if self.children:
            result["children"] = [c.to_dict() for c in self.children]
        return result


# ── Result ──────────────────────────────────────────────────────────


@dataclass
class WorkflowResult:
    """Workflow execution result."""

    workflow_id: str
    name: str
    status: str = "running"  # running | completed | partial | failed | cancelled
    node_results: Dict[str, Any] = field(default_factory=dict)
    start_time: float = field(default_factory=__import__("time").time)
    end_time: Optional[float] = None
    error: Optional[str] = None

    @property
    def duration_seconds(self) -> float:
        import time
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time

    def to_summary(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "status": self.status,
            "duration_seconds": round(self.duration_seconds, 2),
            "nodes_completed": len(
                [r for r in self.node_results.values() if isinstance(r, dict)]
            ),
            "error": self.error,
        }


# ── Workflow definition ─────────────────────────────────────────────


class AgentWorkflow:
    """Agent workflow — describes agent topology and execution order.

    Factory methods:
        AgentWorkflow.simple("Search", "search for X", tools=["web_search"])
        AgentWorkflow.parallel("Multi-search", [
            {"task": "search A", "tools": ["web_search"]},
            {"task": "search B", "tools": ["web_search"]},
        ])
        AgentWorkflow.pipeline("Search+Summarize", [
            {"task": "search A", "tools": ["web_search"]},
            {"task": "summarize results", "tools": ["file_writer"]},
        ])
    """

    def __init__(self, workflow_id: str, name: str):
        self.workflow_id = workflow_id
        self.name = name
        self.root: Optional[WorkflowNode] = None

    @classmethod
    def simple(
        cls, name: str, task: str, tools: Optional[List[str]] = None
    ) -> AgentWorkflow:
        """Create a single-agent workflow."""
        wf = cls(str(uuid.uuid4()), name)
        wf.root = WorkflowNode(
            node_id="root",
            node_type=WorkflowNodeType.AGENT,
            task_template=task,
            allowed_tools=tools or [],
        )
        return wf

    @classmethod
    def parallel(
        cls, name: str, tasks: List[Dict[str, Any]]
    ) -> AgentWorkflow:
        """Create a parallel workflow — multiple agents run concurrently.

        Args:
            tasks: [{"task": "...", "tools": ["..."]}, ...]
        """
        wf = cls(str(uuid.uuid4()), name)
        children = []
        for i, t in enumerate(tasks):
            children.append(
                WorkflowNode(
                    node_id=f"agent_{i}",
                    node_type=WorkflowNodeType.AGENT,
                    task_template=t["task"],
                    allowed_tools=t.get("tools", []),
                    timeout=t.get("timeout", 60),
                    model_config=t.get("model_config"),
                )
            )
        wf.root = WorkflowNode(
            node_id="parallel_root",
            node_type=WorkflowNodeType.PARALLEL,
            children=children,
        )
        return wf

    @classmethod
    def pipeline(
        cls, name: str, stages: List[Dict[str, Any]]
    ) -> AgentWorkflow:
        """Create a pipeline workflow — each stage's output feeds the next.

        Args:
            stages: [{"task": "...", "tools": ["..."]}, ...]
        """
        wf = cls(str(uuid.uuid4()), name)
        children = []
        for i, stage in enumerate(stages):
            task = stage["task"]
            if i > 0 and "{parent_result}" not in task:
                task = (
                    f"{task}\n\n---\nPrevious stage output:\n{{parent_result}}"
                )
            children.append(
                WorkflowNode(
                    node_id=f"stage_{i}",
                    node_type=WorkflowNodeType.AGENT,
                    task_template=task,
                    allowed_tools=stage.get("tools", []),
                    timeout=stage.get("timeout", 60),
                    model_config=stage.get("model_config"),
                )
            )
        wf.root = WorkflowNode(
            node_id="pipeline_root",
            node_type=WorkflowNodeType.SEQUENCE,
            children=children,
        )
        return wf

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "root": self.root.to_dict() if self.root else None,
        }

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> AgentWorkflow:
        """Deserialize from JSON dict (simplified, simple/parallel/pipeline)."""
        mode = data.get("mode", "simple")
        name = data.get("name", "workflow")
        tasks = data.get("tasks", [])

        if mode == "parallel":
            return cls.parallel(name, tasks)
        elif mode == "pipeline":
            return cls.pipeline(name, tasks)
        else:
            task = tasks[0]["task"] if tasks else data.get("task", "")
            tools = tasks[0].get("tools", []) if tasks else []
            return cls.simple(name, task, tools)
