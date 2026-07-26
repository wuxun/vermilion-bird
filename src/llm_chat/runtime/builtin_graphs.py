"""应用内置的 LangGraph 工作流。"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from typing_extensions import TypedDict


class ToolApprovalState(TypedDict, total=False):
    proposal_id: str
    tool_name: str
    arguments: dict
    reason: str
    impact: str
    risk: str
    approved: bool
    outcome: str
    result: Any


def build_tool_approval_graph(
    execute_approved: Callable[[str], Any],
) -> StateGraph:
    """审批前绝不执行工具；恢复后由持久化 proposal ID 定位动作。"""

    builder = StateGraph(ToolApprovalState)

    def request_approval(state: ToolApprovalState) -> dict:
        decision = interrupt(
            {
                "kind": "tool_approval",
                "proposal_id": state["proposal_id"],
                "tool_name": state["tool_name"],
                "arguments": state.get("arguments", {}),
                "reason": state.get("reason", ""),
                "impact": state.get("impact", ""),
                "risk": state.get("risk", "medium"),
            }
        )
        approved = bool(decision.get("approved") if isinstance(decision, dict) else decision)
        return {"approved": approved}

    def route_decision(state: ToolApprovalState) -> str:
        return "execute" if state.get("approved") else "reject"

    def execute(state: ToolApprovalState) -> dict:
        result = execute_approved(state["proposal_id"])
        return {
            "outcome": "completed",
            "result": result,
        }

    def reject(_state: ToolApprovalState) -> dict:
        return {"outcome": "rejected"}

    builder.add_node("request_approval", request_approval)
    builder.add_node("execute", execute)
    builder.add_node("reject", reject)
    builder.add_edge(START, "request_approval")
    builder.add_conditional_edges(
        "request_approval",
        route_decision,
        {"execute": "execute", "reject": "reject"},
    )
    builder.add_edge("execute", END)
    builder.add_edge("reject", END)
    return builder
