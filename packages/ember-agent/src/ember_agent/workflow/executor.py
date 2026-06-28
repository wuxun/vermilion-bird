"""WorkflowExecutor — synchronous DAG execution engine.

Executes AgentWorkflow topologies. Supports:
    - AGENT nodes: delegate to executor_fn
    - PARALLEL nodes: fan-out via temporary ThreadPoolExecutor
    - SEQUENCE nodes: chain with result propagation
    - CONDITION nodes: branch based on previous node result

Thread model:
    - execute() runs synchronously in caller's thread
    - Agent tasks are delegated to AgentRegistry's pool
    - PARALLEL orchestration uses a local temporary pool
"""

from __future__ import annotations

import uuid
import time
import logging
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Dict, List, Optional, Any, TYPE_CHECKING

from ember_agent.workflow.nodes import (
    WorkflowNode,
    WorkflowNodeType,
    WorkflowResult,
    AgentWorkflow,
)
from ember_agent.agent.context import make_agent_context

if TYPE_CHECKING:
    from ember_agent.agent.registry import AgentRegistry

logger = logging.getLogger(__name__)

#: Agent executor signature: (agent_id, task, tools, timeout, context, model_config) -> str
AgentExecutorFn = Callable[[str, str, List[str], int, Any, Optional[Dict]], str]


def _describe_node(node: Optional[WorkflowNode]) -> str:
    if node is None:
        return "empty"
    if node.node_type == WorkflowNodeType.AGENT:
        task = (node.task_template or "")[:60]
        return f"agent({task}...)"
    elif node.node_type == WorkflowNodeType.PARALLEL:
        return f"parallel({len(node.children)} children)"
    elif node.node_type == WorkflowNodeType.SEQUENCE:
        return f"sequence({len(node.children)} stages)"
    return str(node.node_type)


class WorkflowExecutor:
    """Executes AgentWorkflow DAGs synchronously.

    Usage:
        executor = WorkflowExecutor(
            registry=agent_registry,
            execute_fn=my_spawn_tool._execute_async,
            timeout_padding=30,
        )
        workflow_id = executor.execute(workflow)
    """

    def __init__(
        self,
        registry: "AgentRegistry",
        execute_fn: AgentExecutorFn,
        timeout_padding: int = 30,
    ):
        self._registry = registry
        self._execute_fn = execute_fn
        self._timeout_padding = timeout_padding
        self._running: Dict[str, WorkflowResult] = {}
        self._agent_to_wf: Dict[str, str] = {}
        self._registry.add_cancel_callback(self._on_agent_cancelled)

    # ------------------------------------------------------------------
    # Cancel cascade
    # ------------------------------------------------------------------

    def _on_agent_cancelled(self, agent_id: str) -> None:
        """Agent cancelled → cascade to enclosing workflow."""
        wf_id = self._agent_to_wf.get(agent_id)
        if wf_id:
            self.cancel(wf_id)
            logger.info(
                "Cascaded cancel from agent '%s' to workflow '%s'",
                agent_id, wf_id,
            )

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self, workflow: AgentWorkflow) -> str:
        """Execute a workflow synchronously. Blocks until complete.

        Returns workflow_id — caller can poll get_result() for details.
        """
        result = WorkflowResult(
            workflow_id=workflow.workflow_id,
            name=workflow.name,
            status="running",
        )
        self._running[workflow.workflow_id] = result

        logger.info(
            "Workflow '%s' (%s) started: %s",
            workflow.name, workflow.workflow_id,
            _describe_node(workflow.root),
        )

        self._execute_node(
            workflow.root, workflow, result, None  # no parent_result for root
        )

        if result.status == "running":
            result.status = "completed"
        result.end_time = time.time()

        logger.info(
            "Workflow '%s' (%s) finished: status=%s, duration=%.1fs",
            workflow.name, workflow.workflow_id,
            result.status, result.duration_seconds,
        )
        return workflow.workflow_id

    def _execute_node(
        self,
        node: WorkflowNode,
        workflow: AgentWorkflow,
        result: WorkflowResult,
        parent_result: Optional[str] = None,
    ) -> None:
        """Recursively execute a workflow node."""
        if result.status == "cancelled":
            logger.debug(
                "Workflow '%s' node '%s' aborted: workflow cancelled",
                workflow.name, node.node_id,
            )
            return

        try:
            if node.node_type == WorkflowNodeType.AGENT:
                self._run_agent_node(node, workflow, result, parent_result)
            elif node.node_type == WorkflowNodeType.PARALLEL:
                self._run_parallel(node, workflow, result, parent_result)
            elif node.node_type == WorkflowNodeType.SEQUENCE:
                self._run_sequence(node, workflow, result, parent_result)
            elif node.node_type == WorkflowNodeType.CONDITION:
                self._run_condition(node, workflow, result, parent_result)

        except Exception as e:
            logger.error(
                "Workflow '%s' node '%s' error: %s",
                workflow.name, node.node_id, e, exc_info=True,
            )
            result.node_results[node.node_id] = {
                "status": "failed",
                "error": str(e),
            }
            result.status = "failed"
            result.error = str(e)

    # ------------------------------------------------------------------
    # Agent node
    # ------------------------------------------------------------------

    def _run_agent_node(
        self,
        node: WorkflowNode,
        workflow: AgentWorkflow,
        result: WorkflowResult,
        parent_result: Optional[str] = None,
    ) -> None:
        """Execute a single AGENT node via the injected executor_fn."""
        task = node.task_template or ""
        if parent_result and "{parent_result}" in task:
            task = task.replace("{parent_result}", parent_result)

        agent_id = str(uuid.uuid4())
        context = make_agent_context(
            agent_id=agent_id,
            parent_id=workflow.workflow_id,
            depth=0,
            allowed_tools=set(node.allowed_tools),
            conversation_id=f"wf_{workflow.workflow_id}_{node.node_id}",
            task=task,
        )
        self._registry.spawn(agent_id, context)
        self._agent_to_wf[agent_id] = workflow.workflow_id

        future = self._registry.submit(
            agent_id,
            self._execute_fn,
            agent_id,
            task,
            node.allowed_tools,
            node.timeout,
            context,
            node.model_config,
        )

        try:
            agent_result = future.result(
                timeout=node.timeout + self._timeout_padding
            )
            if result.status == "cancelled":
                self._registry.cancel(agent_id)
                result.node_results[node.node_id] = {
                    "agent_id": agent_id,
                    "status": "cancelled",
                    "error": "Workflow cancelled",
                }
                return
            result.node_results[node.node_id] = {
                "agent_id": agent_id,
                "status": "completed",
                "result": agent_result,
            }
            logger.info(
                "Workflow '%s' agent '%s' completed: %d chars",
                workflow.name, node.node_id, len(agent_result or ""),
            )
        except Exception as e:
            self._registry.cancel(agent_id)
            result.node_results[node.node_id] = {
                "agent_id": agent_id,
                "status": "failed",
                "error": str(e),
            }
            raise

    # ------------------------------------------------------------------
    # Parallel
    # ------------------------------------------------------------------

    def _run_parallel(
        self,
        node: WorkflowNode,
        workflow: AgentWorkflow,
        result: WorkflowResult,
        parent_result: Optional[str] = None,
    ) -> None:
        """Execute all children concurrently via temporary thread pool."""
        futures: Dict[str, Future] = {}
        child_results: Dict[str, Any] = {}

        with ThreadPoolExecutor(
            max_workers=len(node.children),
            thread_name_prefix=f"wf-par-{workflow.workflow_id[:8]}",
        ) as pool:
            for child in node.children:
                f = pool.submit(
                    self._execute_node,
                    child, workflow, result, parent_result,
                )
                futures[child.node_id] = f

            for child_id, f in futures.items():
                try:
                    f.result(
                        timeout=node.timeout * len(node.children)
                        + self._timeout_padding
                    )
                except Exception as e:
                    child_results[child_id] = {
                        "status": "failed", "error": str(e)
                    }
                    logger.error(
                        "Workflow '%s' parallel child '%s' error: %s",
                        workflow.name, child_id, e,
                    )

        failed = sum(
            1 for r in child_results.values()
            if isinstance(r, dict) and r.get("status") == "failed"
        )
        completed = len(node.children) - failed

        result.node_results[node.node_id] = {
            "type": "parallel",
            "children": child_results,
            "summary": f"{completed}/{len(node.children)} completed",
        }

        if failed > 0 and node.on_error == "fail":
            result.status = "partial"
            result.error = f"{failed} child tasks failed"

    # ------------------------------------------------------------------
    # Sequence (pipeline)
    # ------------------------------------------------------------------

    def _run_sequence(
        self,
        node: WorkflowNode,
        workflow: AgentWorkflow,
        result: WorkflowResult,
        parent_result: Optional[str] = None,
    ) -> None:
        """Execute children sequentially, passing each output to next."""
        prev_result = parent_result

        for child in node.children:
            self._execute_node(child, workflow, result, prev_result)

            child_result = result.node_results.get(child.node_id, {})
            if isinstance(child_result, dict) and child_result.get("result"):
                prev_result = child_result["result"]
            elif isinstance(child_result, str):
                prev_result = child_result

        result.node_results[node.node_id] = {
            "type": "sequence",
            "stages": len(node.children),
        }

    # ------------------------------------------------------------------
    # Condition (branch)
    # ------------------------------------------------------------------

    def _run_condition(
        self,
        node: WorkflowNode,
        workflow: AgentWorkflow,
        result: WorkflowResult,
        parent_result: Optional[str] = None,
    ) -> None:
        """Branch based on previous node result's status."""
        condition = getattr(node, 'condition', None) or {}
        field = condition.get("field", "status")
        operator = condition.get("operator", "equals")
        expected = condition.get("value", "completed")

        prev_node_result = {}
        if parent_result and parent_result in result.node_results:
            prev_node_result = result.node_results[parent_result]
            if isinstance(prev_node_result, str):
                prev_node_result = {"result": prev_node_result}

        actual_value = prev_node_result.get(field, "")

        is_true = False
        if operator == "equals":
            is_true = str(actual_value) == str(expected)
        elif operator == "not_empty":
            is_true = bool(actual_value)
        elif operator == "contains":
            is_true = str(expected) in str(actual_value)
        elif operator == "is_error":
            is_true = (
                "error" in str(actual_value).lower()
                or "failed" in str(actual_value).lower()
            )

        logger.info(
            "Workflow '%s' condition '%s': %s %s %s → %s",
            workflow.name, node.node_id,
            actual_value, operator, expected,
            "true_branch" if is_true else "false_branch",
        )

        branch = node.true_branch if is_true else node.false_branch
        if branch:
            if isinstance(branch, list):
                for child in branch:
                    self._execute_node(child, workflow, result, parent_result)
            else:
                self._execute_node(branch, workflow, result, parent_result)

        result.node_results[node.node_id] = {
            "type": "condition",
            "condition_met": is_true,
            "branch": "true" if is_true else "false",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_result(self, workflow_id: str) -> Optional[WorkflowResult]:
        """Get workflow execution result."""
        return self._running.get(workflow_id)

    def cancel(self, workflow_id: str) -> bool:
        """Cancel a running workflow (best-effort)."""
        wf_result = self._running.get(workflow_id)
        if wf_result and wf_result.status == "running":
            wf_result.status = "cancelled"
            wf_result.end_time = time.time()
            wf_result.error = "Cancelled by user"
            return True
        return False

    def list_active(self) -> List[Dict[str, Any]]:
        """List all active workflows."""
        return [
            r.to_summary()
            for r in self._running.values()
            if r.status == "running"
        ]

    def cleanup(self) -> int:
        """Remove finished workflows. Returns count removed."""
        to_remove = [
            wf_id for wf_id, r in self._running.items()
            if r.status != "running"
        ]
        for wf_id in to_remove:
            del self._running[wf_id]
        self._agent_to_wf = {
            aid: wf_id
            for aid, wf_id in self._agent_to_wf.items()
            if wf_id in self._running
        }
        if to_remove:
            logger.info("Cleaned up %d finished workflows", len(to_remove))
        return len(to_remove)
