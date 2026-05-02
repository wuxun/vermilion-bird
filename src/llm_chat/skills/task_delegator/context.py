from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Set


@dataclass
class AgentContext:
    """子 agent 运行时上下文。

    _cancelled 用于协作式取消：cancel() 设置此事件，后台线程在执行关键步骤后
    检查此事件来决定是否放弃后续操作。
    """

    agent_id: str
    parent_id: Optional[str]
    depth: int
    allowed_tools: Set[str]
    conversation_id: str
    created_at: datetime
    status: str
    task: str = ""                        # 任务描述，供 GUI 面板展示
    result: Optional[str] = None
    work_dir: Optional[str] = None
    # 执行元数据 — 供 GUI 面板展示
    model: str = ""
    protocol: str = ""
    tool_calls_log: list = field(default_factory=list)
    _cancelled: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    # Dead agent detection
    started_at: float = 0.0  # time.time() when execution began
    deadline: float = 0.0    # time.time() after which agent is considered dead


def make_agent_context(
    agent_id: str,
    parent_id: Optional[str],
    depth: int,
    allowed_tools: Set[str],
    conversation_id: str,
    task: str = "",
    work_dir: str = ".vb/work",
) -> AgentContext:
    """统一创建 AgentContext，默认 status='running' 并标记创建时间。

    SpawnSubagentTool 和 WorkflowExecutor 共用此工厂，避免 AgentContext 创建逻辑重复。
    """
    return AgentContext(
        agent_id=agent_id,
        parent_id=parent_id,
        depth=depth,
        allowed_tools=allowed_tools,
        conversation_id=conversation_id,
        created_at=datetime.utcnow(),
        status="running",
        task=task,
        work_dir=work_dir,
    )
