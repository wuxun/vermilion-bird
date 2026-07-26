"""副作用人工对账的应用服务。"""

from __future__ import annotations

from typing import Any, List, Optional

from .actions import ActionProposalManager, ActionStatus
from .effects import (
    EffectOutbox,
    EffectRecord,
    EffectResolution,
    EffectStatus,
)
from .manager import RunManager
from .models import RunStatus


class EffectReconciliationService:
    """同步 Outbox、ActionProposal 与执行 Run 的人工核对结论。"""

    def __init__(
        self,
        *,
        outbox: EffectOutbox,
        proposals: ActionProposalManager,
        runs: RunManager,
    ):
        self.outbox = outbox
        self.proposals = proposals
        self.runs = runs

    def list(
        self,
        *,
        status: Optional[EffectStatus] = None,
        limit: int = 500,
    ) -> List[EffectRecord]:
        return self.outbox.repository.list_effects(status=status, limit=limit)

    def resolve(
        self,
        effect_key: str,
        *,
        resolution: EffectResolution,
        note: str,
        result: Any = None,
        actor: str = "local-user",
    ) -> EffectRecord:
        record = self.outbox.resolve_uncertain(
            effect_key=effect_key,
            resolution=resolution,
            note=note,
            result=result,
            actor=actor,
        )
        if resolution == EffectResolution.RETRY_APPROVED:
            return record

        self._align_linked_state(record)
        return record

    def repair_linked_state(self, *, limit: int = 1000) -> List[EffectRecord]:
        """启动时修复 Outbox 已落盘但关联状态尚未同步的崩溃窗口。"""

        repaired: List[EffectRecord] = []
        for record in self.list(limit=limit):
            if record.resolution not in {
                EffectResolution.SUCCEEDED,
                EffectResolution.NOT_APPLIED,
            }:
                continue
            if self._align_linked_state(record):
                repaired.append(record)
        return repaired

    def _align_linked_state(self, record: EffectRecord) -> bool:
        succeeded = record.resolution == EffectResolution.SUCCEEDED
        note = record.reconciliation_note or "人工副作用对账"
        result = record.result
        changed = False
        proposal_id = record.payload.get("proposal_id")
        if proposal_id:
            proposal = self.proposals.get(str(proposal_id))
            expected_action = ActionStatus.COMPLETED if succeeded else ActionStatus.FAILED
            if proposal is not None and proposal.status != expected_action:
                self.proposals.reconcile_effect(
                    proposal.id,
                    succeeded=succeeded,
                    note=note,
                    result=result,
                )
                changed = True
        if record.run_id:
            run = self.runs.get(record.run_id)
            expected_run = RunStatus.COMPLETED if succeeded else RunStatus.FAILED
            if run is not None and run.status != expected_run:
                self.runs.reconcile_terminal(
                    record.run_id,
                    succeeded=succeeded,
                    note=note,
                    result=result,
                )
                changed = True
        return changed
