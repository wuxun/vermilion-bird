"""
Agent Workflow — 子 Agent 工作流编排层

支持三种工作流模式：
- simple:   单个子 agent 执行单一任务
- parallel: 多个子 agent 并行执行独立子任务
- pipeline: 多个子 agent 串行执行，前一个输出传给下一个

线程模型：
- Agent 执行 → SubAgentRegistry 的池 (max_workers=8)
- parallel 节点编排 → 临时 ThreadPoolExecutor（用完即关）
- 其余节点编排 → 同步串行（pipeline 本身语义即串行）
"""

from __future__ import annotations

import uuid
import json
import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor, Future

if TYPE_CHECKING:
    from llm_chat.skills.task_delegator.registry import SubAgentRegistry
    from llm_chat.skills.task_delegator.tools import SpawnSubagentTool

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Core data types
# ------------------------------------------------------------------


class WorkflowNodeType(Enum):
    AGENT = "agent"          # 单个子 agent 任务
    PARALLEL = "parallel"    # 并行执行多个子节点
    SEQUENCE = "sequence"    # 串行执行多个子节点


@dataclass
class WorkflowNode:
    """工作流节点 —— 描述一个子 agent 任务或一组任务的拓扑。"""

    node_id: str
    node_type: WorkflowNodeType

    # AGENT 类型参数
    task_template: Optional[str] = None       # 任务模板（支持 {parent_result} 变量）
    allowed_tools: List[str] = field(default_factory=list)
    model_config: Optional[Dict[str, Any]] = None
    timeout: int = 60

    # PARALLEL / SEQUENCE 类型参数
    children: List[WorkflowNode] = field(default_factory=list)

    # CONDITION 类型参数
    condition: Optional[Dict[str, Any]] = None  # {field, operator, value}
    true_branch: Optional[List[WorkflowNode]] = None
    false_branch: Optional[List[WorkflowNode]] = None

    # 通用
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


@dataclass
class WorkflowResult:
    """工作流执行结果。"""

    workflow_id: str
    name: str
    status: str = "running"         # running | completed | partial | failed
    node_results: Dict[str, Any] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    error: Optional[str] = None

    @property
    def duration_seconds(self) -> float:
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


# ------------------------------------------------------------------
# AgentWorkflow — 工作流定义
# ------------------------------------------------------------------


class AgentWorkflow:
    """Agent 工作流 —— 描述子 agent 的拓扑和执行顺序。

    使用工厂方法构造：
        AgentWorkflow.simple("搜索", "用 web_search 搜索 X")
        AgentWorkflow.parallel("多路搜索", [
            {"task": "搜索 A", "tools": ["web_search"]},
            {"task": "搜索 B", "tools": ["web_search"]},
        ])
        AgentWorkflow.pipeline("搜索+总结", [
            {"task": "搜索 A", "tools": ["web_search"]},
            {"task": "基于结果总结", "tools": ["file_writer"]},
        ])
    """

    def __init__(self, workflow_id: str, name: str):
        self.workflow_id = workflow_id
        self.name = name
        self.root: Optional[WorkflowNode] = None

    @classmethod
    def simple(cls, name: str, task: str, tools: Optional[List[str]] = None) -> AgentWorkflow:
        """创建单 agent 简单工作流。"""
        wf = cls(str(uuid.uuid4()), name)
        wf.root = WorkflowNode(
            node_id="root",
            node_type=WorkflowNodeType.AGENT,
            task_template=task,
            allowed_tools=tools or [],
        )
        return wf

    @classmethod
    def parallel(cls, name: str, tasks: List[Dict[str, Any]]) -> AgentWorkflow:
        """创建并行工作流 —— 多个子 agent 同时执行。

        Args:
            tasks: [{"task": "...", "tools": ["..."]}, ...]
        """
        wf = cls(str(uuid.uuid4()), name)
        children = []
        for i, t in enumerate(tasks):
            children.append(WorkflowNode(
                node_id=f"agent_{i}",
                node_type=WorkflowNodeType.AGENT,
                task_template=t["task"],
                allowed_tools=t.get("tools", []),
                timeout=t.get("timeout", 60),
                model_config=t.get("model_config"),
            ))
        wf.root = WorkflowNode(
            node_id="parallel_root",
            node_type=WorkflowNodeType.PARALLEL,
            children=children,
        )
        return wf

    @classmethod
    def pipeline(cls, name: str, stages: List[Dict[str, Any]]) -> AgentWorkflow:
        """创建串行管道工作流 —— 前一个输出作为后一个输入。

        Args:
            stages: [{"task": "...", "tools": ["..."]}, ...]
        """
        wf = cls(str(uuid.uuid4()), name)
        children = []
        for i, stage in enumerate(stages):
            task = stage["task"]
            # 自动追加前置结果上下文
            if i > 0 and "{parent_result}" not in task:
                task = (
                    f"{task}\n\n---\n前置阶段输出结果：\n{{parent_result}}"
                )
            children.append(WorkflowNode(
                node_id=f"stage_{i}",
                node_type=WorkflowNodeType.AGENT,
                task_template=task,
                allowed_tools=stage.get("tools", []),
                timeout=stage.get("timeout", 60),
                model_config=stage.get("model_config"),
            ))
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
        """从 JSON 字典反序列化（简化版，仅支持 simple 模式）。"""
        # 用于 LLM 通过 execute_workflow 工具直接描述工作流
        mode = data.get("mode", "simple")
        name = data.get("name", "workflow")
        tasks = data.get("tasks", [])

        if mode == "parallel":
            return cls.parallel(name, tasks)
        elif mode == "pipeline":
            return cls.pipeline(name, tasks)
        else:
            # simple: 取第一个 task
            task = tasks[0]["task"] if tasks else data.get("task", "")
            tools = tasks[0].get("tools", []) if tasks else []
            return cls.simple(name, task, tools)


# ------------------------------------------------------------------
# WorkflowExecutor — 工作流执行引擎
# ------------------------------------------------------------------


class WorkflowExecutor:
    """工作流执行器 —— 同步执行 AgentWorkflow。

    线程模型：
    - execute() 调用方线程同步执行整个工作流（调用方通常是工具执行线程）
    - Agent 任务委托给 SubAgentRegistry 的线程池
    - parallel 节点使用临时 ThreadPoolExecutor 并行编排子节点
    """

    def __init__(
        self,
        subagent_registry: SubAgentRegistry,
        spawn_tool: SpawnSubagentTool,
    ):
        self._registry = subagent_registry
        self._spawn_tool = spawn_tool
        self._running: Dict[str, WorkflowResult] = {}
        # Track agent_id → workflow_id mapping for cancel chain
        self._agent_to_wf: Dict[str, str] = {}
        # Register cancel callback so panel cancel cascades to workflow
        self._registry.add_cancel_callback(self._on_agent_cancelled)

    def _timeout_padding(self) -> int:
        """节点超时 padding（可配置 via config.tools.workflow_timeout_padding）。"""
        try:
            return self._spawn_tool.config.tools.workflow_timeout_padding
        except Exception:
            return 30

    def _on_agent_cancelled(self, agent_id: str) -> None:
        """Called by registry when an agent is cancelled.

        Cascades cancellation to the enclosing workflow.
        """
        wf_id = self._agent_to_wf.get(agent_id)
        if wf_id:
            self.cancel(wf_id)
            logger.info(
                "Cascaded cancel from agent '%s' to workflow '%s'",
                agent_id, wf_id,
            )

    def execute(self, workflow: AgentWorkflow) -> str:
        """同步执行工作流，阻塞直到完成，返回 workflow_id。

        调用方可立即通过 get_workflow_status() 查询完整结果。
        """
        result = WorkflowResult(
            workflow_id=workflow.workflow_id,
            name=workflow.name,
            status="running",
        )
        self._running[workflow.workflow_id] = result

        logger.info(
            "Workflow '%s' (%s) started: %s",
            workflow.name,
            workflow.workflow_id,
            _describe_node(workflow.root),
        )

        self._execute_node(
            workflow.root,
            workflow,
            result,
            None,  # no parent_result for root
        )

        # 所有节点执行完毕且无错误 → completed (除非已被 cancel 设成 cancelled)
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
    ):
        """递归执行工作流节点。"""
        # 检查工作流是否已被取消
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

    # --------------------------------------------------------------
    # Node execution strategies
    # --------------------------------------------------------------

    def _run_agent_node(
        self,
        node: WorkflowNode,
        workflow: AgentWorkflow,
        result: WorkflowResult,
        parent_result: Optional[str] = None,
    ):
        """执行单个 AGENT 节点 — 通过 spawn_subagent 异步创建并等待完成。"""
        from llm_chat.skills.task_delegator.context import make_agent_context

        # 构建任务（注入父节点结果）
        task = node.task_template or ""
        if parent_result and "{parent_result}" in task:
            task = task.replace("{parent_result}", parent_result)

        # 使用 SpawnSubagentTool 的 _execute_async 直接运行
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

        # Track agent → workflow mapping for cancel cascade
        self._agent_to_wf[agent_id] = workflow.workflow_id

        future = self._registry.submit(
            agent_id,
            self._spawn_tool._execute_async,
            agent_id,
            task,
            node.allowed_tools,
            node.timeout,
            context,
            node.model_config,
        )

        try:
            agent_result = future.result(timeout=node.timeout + self._timeout_padding())
            # Check if workflow was cancelled while waiting
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

    def _run_parallel(
        self,
        node: WorkflowNode,
        workflow: AgentWorkflow,
        result: WorkflowResult,
        parent_result: Optional[str] = None,
    ):
        """并行执行所有子节点。

        使用临时 ThreadPoolExecutor，在工作流上下文中并行编排子节点。
        Agent 的实际执行仍委托给 SubAgentRegistry 的线程池。
        """
        futures: Dict[str, Future] = {}
        child_results: Dict[str, Any] = {}

        # 临时池：大小 = 子节点数，用完即关
        with ThreadPoolExecutor(
            max_workers=len(node.children),
            thread_name_prefix=f"wf-par-{workflow.workflow_id[:8]}",
        ) as pool:
            for child in node.children:
                f = pool.submit(
                    self._execute_node,
                    child,
                    workflow,
                    result,
                    parent_result,
                )
                futures[child.node_id] = f

            # 等待所有子节点完成
            for child_id, f in futures.items():
                try:
                    f.result(timeout=node.timeout * len(node.children) + self._timeout_padding())
                except Exception as e:
                    child_results[child_id] = {"status": "failed", "error": str(e)}
                    logger.error(
                        "Workflow '%s' parallel child '%s' error: %s",
                        workflow.name, child_id, e,
                    )

        # 汇总
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

    def _run_sequence(
        self,
        node: WorkflowNode,
        workflow: AgentWorkflow,
        result: WorkflowResult,
        parent_result: Optional[str] = None,
    ):
        """串行执行子节点，前一个输出传给下一个。"""
        prev_result = parent_result

        for child in node.children:
            self._execute_node(child, workflow, result, prev_result)

            # 提取上一个节点的结果传给下一个
            child_result = result.node_results.get(child.node_id, {})
            if isinstance(child_result, dict) and child_result.get("result"):
                prev_result = child_result["result"]
            elif isinstance(child_result, str):
                prev_result = child_result

        result.node_results[node.node_id] = {
            "type": "sequence",
            "stages": len(node.children),
        }

    def _run_condition(
        self,
        node: WorkflowNode,
        workflow: AgentWorkflow,
        result: WorkflowResult,
        parent_result: Optional[str] = None,
    ):
        """条件分支节点：根据 parent_result 的 status 选择分支。

        node.condition 字段格式:
          {"field": "status", "operator": "equals", "value": "completed"}
        或省略 condition (默认: 上一个节点成功 → true_branch，失败 → false_branch)

        node.true_branch / node.false_branch: 子节点列表（可选）
        """
        # 评估条件：默认根据 parent 节点的状态判断
        condition = getattr(node, 'condition', None) or {}
        field = condition.get("field", "status")
        operator = condition.get("operator", "equals")
        expected = condition.get("value", "completed")

        # 从 parent_result (上一个节点的 node_id) 获取实际结果
        prev_node_result = {}
        if parent_result and parent_result in result.node_results:
            prev_node_result = result.node_results[parent_result]
            if isinstance(prev_node_result, str):
                prev_node_result = {"result": prev_node_result}

        actual_value = prev_node_result.get(field, "")

        # 评估条件
        is_true = False
        if operator == "equals":
            is_true = str(actual_value) == str(expected)
        elif operator == "not_empty":
            is_true = bool(actual_value)
        elif operator == "contains":
            is_true = str(expected) in str(actual_value)
        elif operator == "is_error":
            is_true = ("error" in str(actual_value).lower() or
                       "failed" in str(actual_value).lower())

        logger.info(
            "Workflow '%s' condition '%s': %s %s %s → %s",
            workflow.name, node.node_id,
            actual_value, operator, expected,
            "true_branch" if is_true else "false_branch",
        )

        # 执行对应分支
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

    # --------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------

    def get_result(self, workflow_id: str) -> Optional[WorkflowResult]:
        """获取工作流执行结果。"""
        return self._running.get(workflow_id)

    def cancel(self, workflow_id: str) -> bool:
        """取消工作流（尽力而为）。"""
        wf_result = self._running.get(workflow_id)
        if wf_result and wf_result.status == "running":
            wf_result.status = "cancelled"
            wf_result.end_time = time.time()
            wf_result.error = "Cancelled by user"
            return True
        return False

    def list_active(self) -> List[Dict[str, Any]]:
        """列出所有活跃工作流。"""
        return [
            r.to_summary()
            for r in self._running.values()
            if r.status == "running"
        ]

    def cleanup(self) -> int:
        """Remove completed/failed/cancelled workflows, release resources."""
        to_remove = [
            wf_id for wf_id, r in self._running.items()
            if r.status != "running"
        ]
        for wf_id in to_remove:
            del self._running[wf_id]
        # Clean up agent→wf mappings for removed workflows
        self._agent_to_wf = {
            aid: wf_id for aid, wf_id in self._agent_to_wf.items()
            if wf_id in self._running
        }
        if to_remove:
            logger.info("Cleaned up %d finished workflows", len(to_remove))
        return len(to_remove)


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------


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
