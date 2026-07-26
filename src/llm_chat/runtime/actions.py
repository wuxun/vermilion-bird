"""Capability policy and auditable approval state for side effects."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Set
from uuid import uuid4

from pydantic import BaseModel, Field

from .manager import RunManager
from .models import RunType


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
            allowed
            or {
                Capability.READ,
                Capability.COMPUTE,
                Capability.NETWORK,
            }
        )
        self.require_approval = set(
            require_approval
            or {
                Capability.WORKSPACE_WRITE,
                Capability.PROCESS,
                Capability.EXTERNAL_MESSAGE,
                Capability.SECRETS,
                Capability.MEMORY_WRITE,
                Capability.SCHEDULE_WRITE,
            }
        )
        self.denied = set(denied or set())

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

    def __init__(self):
        self._proposals: Dict[str, ActionProposal] = {}
        self._dedupe: Dict[str, str] = {}
        self._lock = threading.RLock()

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
            return proposal.model_copy(deep=True)

    def get(self, proposal_id: str) -> Optional[ActionProposal]:
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            return proposal.model_copy(deep=True) if proposal else None

    def list(
        self,
        *,
        status: Optional[ActionStatus] = None,
        run_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> List[ActionProposal]:
        with self._lock:
            proposals = list(self._proposals.values())
            if status:
                proposals = [item for item in proposals if item.status == status]
            if run_id:
                proposals = [item for item in proposals if item.run_id == run_id]
            if conversation_id:
                proposals = [item for item in proposals if item.conversation_id == conversation_id]
            return [item.model_copy(deep=True) for item in proposals]

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
            return proposal.model_copy(deep=True)

    def approve_and_execute(
        self,
        proposal_id: str,
        *,
        tool_registry,
        run_manager: RunManager,
        parent_run_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> ActionProposal:
        with self._lock:
            proposal = self._require_locked(proposal_id)
            self._verify_conversation(proposal, conversation_id)
            if proposal.status != ActionStatus.PENDING:
                raise ValueError(f"Action {proposal_id} is {proposal.status.value}, not pending")
            proposal.status = ActionStatus.APPROVED
            proposal.decided_at = _utc_now()
            proposal.status = ActionStatus.EXECUTING
            snapshot = proposal.model_copy(deep=True)

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
            run_manager.fail(action_run.id, str(exc))
        else:
            with self._lock:
                proposal = self._require_locked(proposal_id)
                proposal.status = ActionStatus.COMPLETED
                proposal.result = str(result)
                proposal.finished_at = _utc_now()
            run_manager.complete(action_run.id, str(result))
        completed = self.get(proposal_id)
        assert completed is not None
        return completed

    def _require_locked(self, proposal_id: str) -> ActionProposal:
        try:
            return self._proposals[proposal_id]
        except KeyError as exc:
            raise KeyError(f"Unknown action proposal: {proposal_id}") from exc

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
