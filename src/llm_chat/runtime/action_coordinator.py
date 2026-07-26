"""持久化审批提案与可恢复工具执行图的协调器。"""

from __future__ import annotations

from typing import Optional

from .actions import ActionProposal, ActionProposalManager, ActionStatus
from .execution_service import GraphExecutionService
from .models import RunType


class DurableActionCoordinator:
    """保证授权决定和工具副作用通过同一 durable graph 串联。"""

    GRAPH_NAME = "tool_approval"

    def __init__(
        self,
        *,
        proposals: ActionProposalManager,
        execution_service: GraphExecutionService,
        tool_registry,
    ):
        self.proposals = proposals
        self.execution_service = execution_service
        self.tool_registry = tool_registry

    def prepare(self, proposal: ActionProposal) -> ActionProposal:
        """为新提案创建一个停在审批 interrupt 的 Tool Run。"""

        if proposal.execution_run_id:
            current = self.proposals.get(proposal.id)
            return current or proposal
        run = self.execution_service.start(
            self.GRAPH_NAME,
            run_type=RunType.TOOL,
            inputs={
                "proposal_id": proposal.id,
                "tool_name": proposal.tool_name,
                "arguments": proposal.arguments,
                "reason": proposal.reason,
                "impact": proposal.impact,
                "risk": proposal.risk,
            },
            conversation_id=proposal.conversation_id,
            parent_run_id=proposal.run_id,
            idempotency_key=f"action:{proposal.id}",
            metadata={
                "proposal_id": proposal.id,
                "approval_kind": "tool",
                "run_handler": "action",
            },
        )
        return self.proposals.link_execution(proposal.id, run.id)

    def approve(
        self,
        proposal_id: str,
        *,
        conversation_id: Optional[str] = None,
    ) -> ActionProposal:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Unknown action proposal: {proposal_id}")
        if proposal.status == ActionStatus.PENDING:
            proposal = self.proposals.approve(
                proposal_id,
                conversation_id=conversation_id,
            )
        elif proposal.status != ActionStatus.APPROVED:
            raise ValueError(f"Action {proposal_id} is {proposal.status.value}, not pending")
        if not proposal.execution_run_id:
            raise ValueError(f"Action {proposal_id} has no durable execution run")

        self.execution_service.resume(
            proposal.execution_run_id,
            {"approved": True, "proposal_id": proposal.id},
        )
        current = self.proposals.get(proposal_id)
        assert current is not None
        return current

    def reject(
        self,
        proposal_id: str,
        *,
        conversation_id: Optional[str] = None,
    ) -> ActionProposal:
        proposal = self.proposals.reject(
            proposal_id,
            conversation_id=conversation_id,
        )
        if proposal.execution_run_id:
            self.execution_service.resume(
                proposal.execution_run_id,
                {"approved": False, "proposal_id": proposal.id},
            )
        return proposal

    def execute_approved(self, proposal_id: str):
        """LangGraph 节点回调：只有 APPROVED 状态才能到达这里。"""

        proposal = self.proposals.execute_approved(
            proposal_id,
            tool_registry=self.tool_registry,
        )
        if proposal.status == ActionStatus.FAILED:
            raise RuntimeError(proposal.error or f"Action {proposal_id} failed")
        return proposal.result

    def resume(self, run_id: str, value=None):
        run = self.execution_service.run_manager.get(run_id)
        if run is None:
            raise KeyError(f"Unknown run: {run_id}")
        proposal_id = run.metadata.get("proposal_id")
        if not proposal_id:
            raise ValueError(f"Run {run_id} has no action proposal")
        approved = value.get("approved") if isinstance(value, dict) else value
        if bool(approved):
            self.approve(
                str(proposal_id),
                conversation_id=run.conversation_id,
            )
        else:
            self.reject(
                str(proposal_id),
                conversation_id=run.conversation_id,
            )
        restored = self.execution_service.run_manager.get(run_id)
        assert restored is not None
        return restored

    @staticmethod
    def can_retry(_run) -> bool:
        return False

    @staticmethod
    def can_replay(_run) -> bool:
        return False

    def retry(self, run_id: str):
        raise ValueError(
            f"Action run {run_id} cannot be retried because its side effect is uncertain"
        )

    def replay(self, run_id: str):
        raise ValueError(f"Action run {run_id} cannot be replayed; create a new proposal instead")
