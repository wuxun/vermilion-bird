"""Tests for ember-agent workflow module — WorkflowNode, AgentWorkflow, WorkflowExecutor."""

import pytest
import time
from ember_agent.workflow import (
    WorkflowNode, WorkflowNodeType, WorkflowResult,
    AgentWorkflow, WorkflowExecutor,
)
from ember_agent.agent import AgentRegistry, make_agent_context


# ── WorkflowNode tests ─────────────────────────────────────────

class TestWorkflowNode:
    def test_agent_node(self):
        node = WorkflowNode(
            node_id="n1", node_type=WorkflowNodeType.AGENT,
            task_template="Do something", allowed_tools=["tool_a"],
            timeout=120,
        )
        d = node.to_dict()
        assert d["node_type"] == "agent"
        assert d["task_template"] == "Do something"

    def test_parallel_node(self):
        child1 = WorkflowNode(node_id="c1", node_type=WorkflowNodeType.AGENT, task_template="t1")
        child2 = WorkflowNode(node_id="c2", node_type=WorkflowNodeType.AGENT, task_template="t2")
        node = WorkflowNode(
            node_id="p1", node_type=WorkflowNodeType.PARALLEL,
            children=[child1, child2],
        )
        d = node.to_dict()
        assert d["node_type"] == "parallel"
        assert len(d["children"]) == 2

    def test_sequence_node(self):
        child = WorkflowNode(node_id="c1", node_type=WorkflowNodeType.AGENT, task_template="t1")
        node = WorkflowNode(
            node_id="s1", node_type=WorkflowNodeType.SEQUENCE,
            children=[child],
        )
        assert node.node_type == WorkflowNodeType.SEQUENCE


# ── AgentWorkflow tests ─────────────────────────────────────────

class TestAgentWorkflow:
    def test_simple(self):
        wf = AgentWorkflow.simple("Test", "do task")
        assert wf.name == "Test"
        assert wf.root.node_type == WorkflowNodeType.AGENT
        assert wf.root.task_template == "do task"

    def test_parallel(self):
        wf = AgentWorkflow.parallel("Multi", [
            {"task": "task a", "tools": ["t1"]},
            {"task": "task b", "tools": ["t2"]},
        ])
        assert wf.root.node_type == WorkflowNodeType.PARALLEL
        assert len(wf.root.children) == 2

    def test_pipeline(self):
        wf = AgentWorkflow.pipeline("Pipeline", [
            {"task": "stage 1", "tools": ["t1"]},
            {"task": "stage 2", "tools": ["t2"]},
        ])
        assert wf.root.node_type == WorkflowNodeType.SEQUENCE
        assert len(wf.root.children) == 2
        # Second stage's task should include {parent_result}
        assert "{parent_result}" in wf.root.children[1].task_template

    def test_from_json_simple(self):
        wf = AgentWorkflow.from_json({"mode": "simple", "name": "WF", "task": "do"})
        assert wf.root.task_template == "do"

    def test_from_json_parallel(self):
        wf = AgentWorkflow.from_json({
            "mode": "parallel", "name": "WF",
            "tasks": [{"task": "a"}, {"task": "b"}],
        })
        assert wf.root.node_type == WorkflowNodeType.PARALLEL


# ── WorkflowResult tests ───────────────────────────────────────

class TestWorkflowResult:
    def test_summary(self):
        result = WorkflowResult(workflow_id="w1", name="Test", status="completed")
        summary = result.to_summary()
        assert summary["workflow_id"] == "w1"
        assert summary["status"] == "completed"
        assert "duration_seconds" in summary

    def test_duration(self):
        result = WorkflowResult(workflow_id="w1", name="Test")
        assert result.duration_seconds >= 0


# ── WorkflowExecutor tests ─────────────────────────────────────

def _simple_executor_fn(agent_id, task, tools, timeout, context, model_config):
    """Stub executor for testing WorkflowExecutor without LLM."""
    return f"completed: {task[:50]}"


class TestWorkflowExecutor:
    def test_execute_simple(self):
        reg = AgentRegistry(max_workers=4)
        executor = WorkflowExecutor(reg, _simple_executor_fn)
        wf = AgentWorkflow.simple("Test", "do task")
        wf_id = executor.execute(wf)
        result = executor.get_result(wf_id)
        assert result is not None
        assert result.status == "completed"
        assert "root" in result.node_results
        assert result.node_results["root"]["status"] == "completed"
        reg.shutdown(wait=False)
        executor.cleanup()

    def test_execute_parallel(self):
        reg = AgentRegistry(max_workers=4)
        executor = WorkflowExecutor(reg, _simple_executor_fn, timeout_padding=10)
        wf = AgentWorkflow.parallel("Multi", [
            {"task": "task a", "tools": []},
            {"task": "task b", "tools": []},
            {"task": "task c", "tools": []},
        ])
        wf_id = executor.execute(wf)
        result = executor.get_result(wf_id)
        assert result.status == "completed"
        # parallel_root should have summary like "3/3 completed"
        node_result = result.node_results[wf.root.node_id]
        assert "3/3" in node_result["summary"]
        reg.shutdown(wait=False)
        executor.cleanup()

    def test_execute_pipeline(self):
        reg = AgentRegistry(max_workers=4)
        executor = WorkflowExecutor(reg, _simple_executor_fn)
        wf = AgentWorkflow.pipeline("Pipe", [
            {"task": "stage 1", "tools": []},
            {"task": "stage 2", "tools": []},
        ])
        wf_id = executor.execute(wf)
        result = executor.get_result(wf_id)
        assert result.status == "completed"
        reg.shutdown(wait=False)
        executor.cleanup()

    def test_cancel(self):
        reg = AgentRegistry(max_workers=4)
        executor = WorkflowExecutor(reg, _simple_executor_fn)

        # Submit a simple workflow but don't wait
        wf = AgentWorkflow.simple("Test", "do")
        # We can't easily cancel mid-execution with the stub, but
        # we can verify cancel() returns True for a running workflow
        wf_id = executor.execute(wf)  # completes synchronously with stub
        # After execution, cancel should return False
        assert not executor.cancel(wf_id)
        reg.shutdown(wait=False)
        executor.cleanup()
