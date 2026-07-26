"""Capability policy and auditable approval state for side effects."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Set,
)
from uuid import uuid4

from pydantic import BaseModel, Field

from .manager import RunManager
from .models import RunType

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Capability(str, Enum):
    READ = "read"
    COMPUTE = "compute"
    NETWORK = "network"
    WORKSPACE_WRITE = "workspace_write"
    PROCESS = "process"
    EXTERNAL_MESSAGE = "external_message"
    SECRETS = "secrets"
    MEMORY_WRITE = "memory_write"
    SCHEDULE_WRITE = "schedule_write"


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class ActionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in {
            ActionStatus.REJECTED,
            ActionStatus.COMPLETED,
            ActionStatus.FAILED,
        }


class ActionProposal(BaseModel):
    """A proposed side effect that can only execute after explicit approval."""

    id: str = Field(default_factory=lambda: f"action_{uuid4().hex}")
    run_id: str
    execution_run_id: Optional[str] = None
    conversation_id: Optional[str] = None
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    capabilities: Set[Capability] = Field(default_factory=set)
    reason: str
    impact: str
    risk: str = "medium"
    reversible: bool = False
    status: ActionStatus = ActionStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=_utc_now)
    decided_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class ActionProposalRepository(Protocol):
    """ActionProposalManager 所需的最小持久化端口。"""

    def save_action_proposal(self, proposal: ActionProposal) -> None:
        ...

    def get_action_proposal(self, proposal_id: str) -> Optional[ActionProposal]:
        ...

    def list_action_proposals(
        self,
        limit: int = 100,
        *,
        offset: int = 0,
        status: Optional[ActionStatus] = None,
        run_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> List[ActionProposal]:
        ...


ActionProposalObserver = Callable[[ActionProposal], None]


class CapabilityPolicy:
    """Classify tool effects and decide whether execution needs approval."""

    _TOOL_CAPABILITIES: Mapping[str, FrozenSet[Capability]] = {
        "write_file": frozenset({Capability.WORKSPACE_WRITE}),
        "create_directory": frozenset({Capability.WORKSPACE_WRITE}),
        "delete_file": frozenset({Capability.WORKSPACE_WRITE}),
        "replace_text": frozenset({Capability.WORKSPACE_WRITE}),
        "insert_text": frozenset({Capability.WORKSPACE_WRITE}),
        "delete_text": frozenset({Capability.WORKSPACE_WRITE}),
        "delete_lines": frozenset({Capability.WORKSPACE_WRITE}),
        "shell_exec": frozenset({Capability.PROCESS, Capability.WORKSPACE_WRITE}),
        "remember_fact": frozenset({Capability.MEMORY_WRITE}),
        "remember_knowledge": frozenset({Capability.MEMORY_WRITE}),
        "create_scheduled_task": frozenset({Capability.SCHEDULE_WRITE}),
        "delete_scheduled_task": frozenset({Capability.SCHEDULE_WRITE}),
        "toggle_scheduled_task": frozenset({Capability.SCHEDULE_WRITE}),
        "run_scheduled_task": frozenset({Capability.SCHEDULE_WRITE}),
    }

    def __init__(
        self,
        *,
        allowed: Optional[Iterable[Capability]] = None,
        require_approval: Optional[Iterable[Capability]] = None,
        denied: Optional[Iterable[Capability]] = None,
    ):
        self.allowed = set(
            {
                Capability.READ,
                Capability.COMPUTE,
                Capability.NETWORK,
            }
            if allowed is None
            else allowed
        )
        self.require_approval = set(
            {
                Capability.WORKSPACE_WRITE,
                Capability.PROCESS,
                Capability.EXTERNAL_MESSAGE,
                Capability.SECRETS,
                Capability.MEMORY_WRITE,
                Capability.SCHEDULE_WRITE,
            }
            if require_approval is None
            else require_approval
        )
        self.denied = set() if denied is None else set(denied)

    def capabilities_for(
        self,
        tool_name: str,
        declared: Optional[Iterable[str]] = None,
    ) -> Set[Capability]:
        if declared:
            return {Capability(value) for value in declared}
        if tool_name in self._TOOL_CAPABILITIES:
            return set(self._TOOL_CAPABILITIES[tool_name])
        if tool_name.startswith(("web_", "mcp__")):
            return {Capability.NETWORK}
        if any(token in tool_name for token in ("send_", "notify_", "push_")):
            return {Capability.EXTERNAL_MESSAGE}
        if any(token in tool_name for token in ("secret", "keyring", "api_key")):
            return {Capability.SECRETS}
        return {Capability.COMPUTE}

    def evaluate(
        self,
        tool_name: str,
        declared: Optional[Iterable[str]] = None,
    ) -> tuple[PolicyDecision, Set[Capability]]:
        capabilities = self.capabilities_for(tool_name, declared)
        if capabilities & self.denied:
            return PolicyDecision.DENY, capabilities
        if capabilities & self.require_approval:
            return PolicyDecision.REQUIRE_APPROVAL, capabilities
        if capabilities <= self.allowed:
            return PolicyDecision.ALLOW, capabilities
        return PolicyDecision.DENY, capabilities


class ActionProposalManager:
    """Thread-safe ActionProposal state machine and approved executor."""

    def __init__(
        self,
        *,
        repository: Optional[ActionProposalRepository] = None,
        restore_limit: int = 1000,
    ):
        self._repository = repository
        self._restore_limit = restore_limit
        self._proposals: Dict[str, ActionProposal] = {}
        self._dedupe: Dict[str, str] = {}
        self._observers: List[ActionProposalObserver] = []
        self._lock = threading.RLock()
        self._restore()

    def propose(
        self,
        *,
        run_id: str,
        conversation_id: Optional[str] = None,
        tool_name: str,
        arguments: Dict[str, Any],
        capabilities: Set[Capability],
        reason: Optional[str] = None,
    ) -> ActionProposal:
        dedupe_key = json.dumps(
            [run_id, conversation_id, tool_name, arguments],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        with self._lock:
            existing_id = self._dedupe.get(dedupe_key)
            existing = self._proposals.get(existing_id) if existing_id else None
            if existing and not existing.status.terminal:
                return existing.model_copy(deep=True)

            capability_text = ", ".join(sorted(item.value for item in capabilities))
            proposal = ActionProposal(
                run_id=run_id,
                conversation_id=conversation_id,
                tool_name=tool_name,
                arguments=arguments,
                capabilities=capabilities,
                reason=reason or f"工具需要能力：{capability_text}",
                impact=f"执行工具 {tool_name}，参数将在批准后原样使用。",
                reversible=tool_name not in {"delete_file", "shell_exec"},
                risk=(
                    "high"
                    if Capability.PROCESS in capabilities or Capability.SECRETS in capabilities
                    else "medium"
                ),
            )
            self._proposals[proposal.id] = proposal
            self._dedupe[dedupe_key] = proposal.id
            snapshot = proposal.model_copy(deep=True)
            self._persist_locked(proposal)
        self._notify(snapshot)
        return snapshot

    def get(self, proposal_id: str) -> Optional[ActionProposal]:
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal:
                return proposal.model_copy(deep=True)
        if self._repository is not None:
            try:
                return self._repository.get_action_proposal(proposal_id)
            except Exception:
                logger.warning(
                    "Failed to load action proposal %s",
                    proposal_id,
                    exc_info=True,
                )
        return None

    def link_execution(
        self,
        proposal_id: str,
        execution_run_id: str,
    ) -> ActionProposal:
        """将提案关联到负责 interrupt/resume 的 durable Run。"""

        if not execution_run_id:
            raise ValueError("execution_run_id cannot be empty")
        with self._lock:
            proposal = self._require_locked(proposal_id)
            if proposal.execution_run_id not in {None, execution_run_id}:
                raise ValueError(
                    f"Action {proposal_id} is already linked to " f"{proposal.execution_run_id}"
                )
            proposal.execution_run_id = execution_run_id
            snapshot = proposal.model_copy(deep=True)
            self._persist_locked(proposal)
        self._notify(snapshot)
        return snapshot

    def list(
        self,
        *,
        status: Optional[ActionStatus] = None,
        run_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ActionProposal]:
        if limit <= 0:
            return []
        if self._repository is not None:
            try:
                return self._repository.list_action_proposals(
                    limit=limit,
                    offset=offset,
                    status=status,
                    run_id=run_id,
                    conversation_id=conversation_id,
                )
            except Exception:
                logger.warning("Failed to list action proposals", exc_info=True)
        with self._lock:
            proposals = list(reversed(self._proposals.values()))
            if status:
                proposals = [item for item in proposals if item.status == status]
            if run_id:
                proposals = [item for item in proposals if item.run_id == run_id]
            if conversation_id:
                proposals = [item for item in proposals if item.conversation_id == conversation_id]
            return [
                item.model_copy(deep=True)
                for item in proposals[max(0, offset) : max(0, offset) + limit]
            ]

    def reject(
        self,
        proposal_id: str,
        *,
        conversation_id: Optional[str] = None,
    ) -> ActionProposal:
        with self._lock:
            proposal = self._require_locked(proposal_id)
            self._verify_conversation(proposal, conversation_id)
            if proposal.status != ActionStatus.PENDING:
                raise ValueError(f"Action {proposal_id} is {proposal.status.value}, not pending")
            proposal.status = ActionStatus.REJECTED
            proposal.decided_at = _utc_now()
            proposal.finished_at = proposal.decided_at
            snapshot = proposal.model_copy(deep=True)
            self._persist_locked(proposal)
        self._notify(snapshot)
        return snapshot

    def approve(
        self,
        proposal_id: str,
        *,
        conversation_id: Optional[str] = None,
    ) -> ActionProposal:
        """只记录授权决定，不在调用线程中执行副作用。"""

        with self._lock:
            proposal = self._require_locked(proposal_id)
            self._verify_conversation(proposal, conversation_id)
            if proposal.status != ActionStatus.PENDING:
                raise ValueError(f"Action {proposal_id} is {proposal.status.value}, not pending")
            proposal.status = ActionStatus.APPROVED
            proposal.decided_at = _utc_now()
            snapshot = proposal.model_copy(deep=True)
            self._persist_locked(proposal)
        self._notify(snapshot)
        return snapshot

    def execute_approved(
        self,
        proposal_id: str,
        *,
        tool_registry,
    ) -> ActionProposal:
        """执行已批准提案；已完成记录直接返回，避免正常重入。"""

        with self._lock:
            proposal = self._require_locked(proposal_id)
            if proposal.status == ActionStatus.COMPLETED:
                return proposal.model_copy(deep=True)
            if proposal.status != ActionStatus.APPROVED:
                raise ValueError(f"Action {proposal_id} is {proposal.status.value}, not approved")
            proposal.status = ActionStatus.EXECUTING
            snapshot = proposal.model_copy(deep=True)
            self._persist_locked(proposal)
        self._notify(snapshot)

        try:
            result = tool_registry.execute_tool(
                snapshot.tool_name,
                arguments=snapshot.arguments,
            )
        except Exception as exc:
            with self._lock:
                proposal = self._require_locked(proposal_id)
                proposal.status = ActionStatus.FAILED
                proposal.error = str(exc)
                proposal.finished_at = _utc_now()
                snapshot = proposal.model_copy(deep=True)
                self._persist_locked(proposal)
            self._notify(snapshot)
            return snapshot

        with self._lock:
            proposal = self._require_locked(proposal_id)
            proposal.status = ActionStatus.COMPLETED
            proposal.result = str(result)
            proposal.error = None
            proposal.finished_at = _utc_now()
            snapshot = proposal.model_copy(deep=True)
            self._persist_locked(proposal)
        self._notify(snapshot)
        return snapshot

    def approve_and_execute(
        self,
        proposal_id: str,
        *,
        tool_registry,
        run_manager: RunManager,
        parent_run_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> ActionProposal:
        snapshot = self.approve(
            proposal_id,
            conversation_id=conversation_id,
        )

        action_run = run_manager.start(
            RunType.TOOL,
            parent_run_id=parent_run_id or snapshot.run_id,
            input={
                "proposal_id": snapshot.id,
                "tool": snapshot.tool_name,
                "arguments": snapshot.arguments,
            },
            metadata={"proposal_origin_run_id": snapshot.run_id},
        )
        snapshot = self.execute_approved(
            proposal_id,
            tool_registry=tool_registry,
        )
        if snapshot.status == ActionStatus.FAILED:
            run_manager.fail(
                action_run.id,
                snapshot.error or "Action failed",
            )
        else:
            run_manager.complete(action_run.id, snapshot.result)
        return snapshot

    def subscribe(self, observer: ActionProposalObserver) -> Callable[[], None]:
        with self._lock:
            self._observers.append(observer)

        def unsubscribe() -> None:
            with self._lock:
                if observer in self._observers:
                    self._observers.remove(observer)

        return unsubscribe

    def _require_locked(self, proposal_id: str) -> ActionProposal:
        try:
            return self._proposals[proposal_id]
        except KeyError as exc:
            raise KeyError(f"Unknown action proposal: {proposal_id}") from exc

    def _restore(self) -> None:
        if self._repository is None:
            return
        try:
            restored = self._repository.list_action_proposals(limit=self._restore_limit)
        except Exception:
            logger.warning("Failed to restore action proposals", exc_info=True)
            return

        with self._lock:
            for proposal in reversed(restored):
                interrupted_legacy_approval = (
                    proposal.status == ActionStatus.APPROVED and not proposal.execution_run_id
                )
                if proposal.status == ActionStatus.EXECUTING or interrupted_legacy_approval:
                    proposal.status = ActionStatus.FAILED
                    proposal.error = "应用重启前动作未正常结束，请重新发起"
                    proposal.finished_at = _utc_now()
                    self._persist_locked(proposal)
                self._proposals[proposal.id] = proposal
                if not proposal.status.terminal:
                    self._dedupe[self._dedupe_key(proposal)] = proposal.id

    def _persist_locked(self, proposal: ActionProposal) -> None:
        if self._repository is None:
            return
        try:
            self._repository.save_action_proposal(proposal.model_copy(deep=True))
        except Exception:
            logger.warning(
                "Failed to persist action proposal %s",
                proposal.id,
                exc_info=True,
            )

    def _notify(self, proposal: ActionProposal) -> None:
        with self._lock:
            observers = list(self._observers)
        for observer in observers:
            try:
                observer(proposal.model_copy(deep=True))
            except Exception:
                logger.warning("Action proposal observer failed", exc_info=True)

    @staticmethod
    def _dedupe_key(proposal: ActionProposal) -> str:
        return json.dumps(
            [
                proposal.run_id,
                proposal.conversation_id,
                proposal.tool_name,
                proposal.arguments,
            ],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    @staticmethod
    def _verify_conversation(
        proposal: ActionProposal,
        conversation_id: Optional[str],
    ) -> None:
        if (
            proposal.conversation_id
            and conversation_id
            and proposal.conversation_id != conversation_id
        ):
            raise ValueError("Action proposal belongs to another conversation")
