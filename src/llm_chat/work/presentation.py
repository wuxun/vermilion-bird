"""面向任务工作区的前端无关只读投影。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

from llm_chat.runtime import ActionProposal, ActionStatus

from .models import (
    Artifact,
    ArtifactFeedback,
    ArtifactFeedbackDecision,
    ArtifactKind,
    ArtifactReviewPolicy,
    PlanStatus,
    WorkItem,
    WorkItemDetail,
    WorkItemKind,
    WorkItemStatus,
)


class TaskWorkspaceScope(str, Enum):
    """任务列表的产品级视图范围。"""

    ALL = "all"
    ACTIVE = "active"
    ATTENTION = "attention"
    UPDATES = "updates"
    FINISHED = "finished"


class AttentionKind(str, Enum):
    PLAN = "plan"
    APPROVAL = "approval"
    FAILURE = "failure"
    ARTIFACT = "artifact"


class AttentionLevel(str, Enum):
    REQUIRED = "required"
    NOTICE = "notice"


class TimelineKind(str, Enum):
    OBJECTIVE = "objective"
    DELIVERABLE = "deliverable"
    PLAN = "plan"
    APPROVAL = "approval"
    ACTIVITY = "activity"
    ARTIFACT = "artifact"


@dataclass(frozen=True)
class AttentionItemView:
    id: str
    kind: AttentionKind
    level: AttentionLevel
    title: str
    summary: str
    action_label: str
    occurred_at: datetime


@dataclass(frozen=True)
class TimelineEntryView:
    id: str
    kind: TimelineKind
    title: str
    summary: str
    details: Tuple[str, ...]
    occurred_at: datetime


@dataclass(frozen=True)
class PrimaryActionView:
    action: Optional[str]
    label: str
    enabled: bool


@dataclass(frozen=True)
class TaskWorkspaceView:
    work_item_id: str
    title: str
    objective: str
    status: WorkItemStatus
    status_label: str
    kind: WorkItemKind
    kind_label: str
    series_key: Optional[str]
    artifact_review_policy: ArtifactReviewPolicy
    updated_at: datetime
    expected_deliverable: str
    attention: Tuple[AttentionItemView, ...]
    timeline: Tuple[TimelineEntryView, ...]
    artifact_count: int
    unreviewed_artifact_count: int
    required_review_count: int
    optional_review_count: int
    primary_action: PrimaryActionView

    @property
    def requires_attention(self) -> bool:
        return self.action_required_count > 0

    @property
    def action_required_count(self) -> int:
        return sum(item.level == AttentionLevel.REQUIRED for item in self.attention)

    @property
    def notice_count(self) -> int:
        return sum(item.level == AttentionLevel.NOTICE for item in self.attention)

    @property
    def has_updates(self) -> bool:
        return self.notice_count > 0


_STATUS_LABELS: Dict[WorkItemStatus, str] = {
    WorkItemStatus.DRAFT: "草稿",
    WorkItemStatus.READY: "待执行",
    WorkItemStatus.RUNNING: "执行中",
    WorkItemStatus.CANCELLING: "正在取消",
    WorkItemStatus.PAUSING: "正在暂停",
    WorkItemStatus.WAITING_APPROVAL: "待审批",
    WorkItemStatus.PAUSED: "已暂停",
    WorkItemStatus.COMPLETED: "已完成",
    WorkItemStatus.FAILED: "失败",
    WorkItemStatus.CANCELLED: "已取消",
}

_KIND_LABELS: Dict[WorkItemKind, str] = {
    WorkItemKind.CHAT: "对话",
    WorkItemKind.TASK: "任务",
    WorkItemKind.AUTOMATION: "自动化",
}

_RUN_STATUS_LABELS = {
    "pending": "待执行",
    "running": "执行中",
    "cancel_requested": "正在取消",
    "pause_requested": "正在暂停",
    "waiting_approval": "待审批",
    "paused": "已暂停",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}

_RUN_TYPE_LABELS = {
    "chat": "对话",
    "tool": "工具",
    "workflow": "任务执行",
    "scheduled": "定时任务",
    "webhook": "事件任务",
    "proactive": "主动任务",
}

_PLAN_STATUS_LABELS = {
    "draft": "待确认",
    "approved": "已批准",
    "superseded": "已取代",
}

_STEP_STATUS_LABELS = {
    "pending": "待执行",
    "running": "执行中",
    "blocked": "受阻",
    "completed": "已完成",
    "failed": "失败",
    "skipped": "已跳过",
}

_ARTIFACT_KIND_LABELS = {
    ArtifactKind.TEXT: "文本",
    ArtifactKind.FILE: "文件",
    ArtifactKind.REPORT: "报告",
    ArtifactKind.CODE: "代码",
    ArtifactKind.LINK: "链接",
    ArtifactKind.MESSAGE: "消息",
    ArtifactKind.OTHER: "其他",
}

_FEEDBACK_LABELS = {
    ArtifactFeedbackDecision.ACCEPTED: "已接受",
    ArtifactFeedbackDecision.NEEDS_REVISION: "需修改",
    ArtifactFeedbackDecision.REJECTED: "已拒绝",
}


class WorkItemReader(Protocol):
    def list(
        self,
        limit: int = 50,
        *,
        offset: int = 0,
        status: Optional[WorkItemStatus] = None,
        kind: Optional[WorkItemKind] = None,
        conversation_id: Optional[str] = None,
    ) -> List[WorkItem]:
        ...

    def detail(self, work_item_id: str) -> WorkItemDetail:
        ...


class ActionReader(Protocol):
    def list(
        self,
        *,
        status: Optional[ActionStatus] = None,
        run_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ActionProposal]:
        ...


class TaskWorkspaceProjector:
    """把领域事实投影成稳定、可直接渲染的任务工作区视图。"""

    def project(
        self,
        detail: WorkItemDetail,
        proposals: Sequence[ActionProposal] = (),
    ) -> TaskWorkspaceView:
        item = detail.work_item
        feedback = self._latest_feedback(detail.artifact_feedback)
        pending = [proposal for proposal in proposals if proposal.status == ActionStatus.PENDING]
        unreviewed = [
            artifact for artifact in detail.artifacts if artifact.id not in feedback
        ]
        required_review = [
            artifact
            for artifact in unreviewed
            if self._review_policy(item, artifact) == ArtifactReviewPolicy.REQUIRED
        ]
        optional_review = [
            artifact
            for artifact in unreviewed
            if self._review_policy(item, artifact) == ArtifactReviewPolicy.OPTIONAL
        ]
        attention = self._attention(
            detail,
            pending,
            required_review,
            optional_review,
        )
        timeline = self._timeline(detail, pending, feedback)
        expected = ""
        if item.metadata:
            expected = str(item.metadata.get("expected_deliverable") or "").strip()
        return TaskWorkspaceView(
            work_item_id=item.id,
            title=item.title,
            objective=item.objective,
            status=item.status,
            status_label=_STATUS_LABELS[item.status],
            kind=item.kind,
            kind_label=_KIND_LABELS[item.kind],
            series_key=item.series_key,
            artifact_review_policy=item.artifact_review_policy,
            updated_at=item.updated_at,
            expected_deliverable=expected,
            attention=tuple(attention),
            timeline=tuple(timeline),
            artifact_count=len(detail.artifacts),
            unreviewed_artifact_count=len(unreviewed),
            required_review_count=len(required_review),
            optional_review_count=len(optional_review),
            primary_action=self._primary_action(
                item,
                pending_count=len(pending),
                has_draft_plan=bool(
                    detail.plan is not None and detail.plan.status == PlanStatus.DRAFT
                ),
                artifact_count=len(detail.artifacts),
            ),
        )

    @staticmethod
    def _latest_feedback(
        feedback_items: Iterable[ArtifactFeedback],
    ) -> Dict[str, ArtifactFeedback]:
        latest: Dict[str, ArtifactFeedback] = {}
        for feedback in feedback_items:
            previous = latest.get(feedback.artifact_id)
            if previous is None or feedback.created_at > previous.created_at:
                latest[feedback.artifact_id] = feedback
        return latest

    def _attention(
        self,
        detail: WorkItemDetail,
        pending: Sequence[ActionProposal],
        required_review: Sequence[Artifact],
        optional_review: Sequence[Artifact],
    ) -> List[AttentionItemView]:
        item = detail.work_item
        result: List[AttentionItemView] = []
        if detail.plan is not None and detail.plan.status == PlanStatus.DRAFT:
            result.append(
                AttentionItemView(
                    id=detail.plan.id,
                    kind=AttentionKind.PLAN,
                    level=AttentionLevel.REQUIRED,
                    title="确认执行计划",
                    summary=f"计划 v{detail.plan.version}：{detail.plan.summary}",
                    action_label="查看并确认",
                    occurred_at=detail.plan.created_at,
                )
            )
        for proposal in pending:
            result.append(
                AttentionItemView(
                    id=proposal.id,
                    kind=AttentionKind.APPROVAL,
                    level=AttentionLevel.REQUIRED,
                    title=f"审批 {proposal.tool_name}",
                    summary=proposal.impact or proposal.reason or "确认是否允许执行此动作",
                    action_label="处理审批",
                    occurred_at=proposal.created_at,
                )
            )
        if item.status == WorkItemStatus.FAILED:
            latest_error = next(
                (run.error for run in detail.runs if run.error),
                "最近一次执行失败，需要检查后重试。",
            )
            result.append(
                AttentionItemView(
                    id=f"{item.id}:failure",
                    kind=AttentionKind.FAILURE,
                    level=AttentionLevel.REQUIRED,
                    title="任务执行失败",
                    summary=latest_error,
                    action_label="检查并重试",
                    occurred_at=item.updated_at,
                )
            )
        if item.status == WorkItemStatus.COMPLETED and required_review:
            result.append(
                AttentionItemView(
                    id=f"{item.id}:artifacts",
                    kind=AttentionKind.ARTIFACT,
                    level=AttentionLevel.REQUIRED,
                    title="验收交付物",
                    summary=f"{len(required_review)} 个交付物等待你的反馈",
                    action_label="查看交付物",
                    occurred_at=max(artifact.created_at for artifact in required_review),
                )
            )
        if item.status == WorkItemStatus.COMPLETED and optional_review:
            result.append(
                AttentionItemView(
                    id=f"{item.id}:updates",
                    kind=AttentionKind.ARTIFACT,
                    level=AttentionLevel.NOTICE,
                    title="有新的自动化结果",
                    summary=f"{len(optional_review)} 个结果可查看，不阻塞其他任务",
                    action_label="查看新结果",
                    occurred_at=max(artifact.created_at for artifact in optional_review),
                )
            )
        return sorted(result, key=lambda entry: entry.occurred_at, reverse=True)

    def _timeline(
        self,
        detail: WorkItemDetail,
        pending: Sequence[ActionProposal],
        feedback: Dict[str, ArtifactFeedback],
    ) -> List[TimelineEntryView]:
        item = detail.work_item
        entries = [
            TimelineEntryView(
                id=f"{item.id}:objective",
                kind=TimelineKind.OBJECTIVE,
                title="目标",
                summary=item.objective,
                details=(),
                occurred_at=item.created_at,
            )
        ]
        expected = str(item.metadata.get("expected_deliverable") or "").strip()
        if expected:
            entries.append(
                TimelineEntryView(
                    id=f"{item.id}:deliverable",
                    kind=TimelineKind.DELIVERABLE,
                    title="预期交付",
                    summary=expected,
                    details=(),
                    occurred_at=item.created_at,
                )
            )
        if detail.plan is not None:
            plan = detail.plan
            steps = tuple(
                f"{step.position}. {step.title} · "
                f"{_STEP_STATUS_LABELS.get(step.status.value, step.status.value)}"
                for step in plan.steps
            )
            entries.append(
                TimelineEntryView(
                    id=plan.id,
                    kind=TimelineKind.PLAN,
                    title="执行计划",
                    summary=(
                        f"v{plan.version} · "
                        f"{_PLAN_STATUS_LABELS.get(plan.status.value, plan.status.value)}"
                        f" · {plan.summary}"
                    ),
                    details=steps,
                    occurred_at=plan.created_at,
                )
            )
        if pending:
            entries.append(
                TimelineEntryView(
                    id=f"{item.id}:approvals",
                    kind=TimelineKind.APPROVAL,
                    title="等待你的批准",
                    summary=f"{len(pending)} 个动作需要确认",
                    details=tuple(
                        f"{proposal.tool_name} · {proposal.impact or proposal.reason}"
                        for proposal in pending
                    ),
                    occurred_at=max(proposal.created_at for proposal in pending),
                )
            )
        if detail.runs:
            recent_runs = sorted(
                detail.runs,
                key=lambda run: run.created_at,
                reverse=True,
            )[:6]
            entries.append(
                TimelineEntryView(
                    id=f"{item.id}:runs",
                    kind=TimelineKind.ACTIVITY,
                    title="执行活动",
                    summary=f"共 {len(detail.runs)} 次执行",
                    details=tuple(
                        f"{_RUN_STATUS_LABELS.get(run.status.value, run.status.value)}"
                        f" · {_RUN_TYPE_LABELS.get(run.type.value, run.type.value)}"
                        f" · {run.created_at.astimezone().strftime('%m-%d %H:%M')}"
                        for run in recent_runs
                    ),
                    occurred_at=recent_runs[0].created_at,
                )
            )
        if detail.artifacts:
            entries.append(
                TimelineEntryView(
                    id=f"{item.id}:artifacts",
                    kind=TimelineKind.ARTIFACT,
                    title="交付结果",
                    summary=f"{len(detail.artifacts)} 个交付物",
                    details=tuple(
                        self._artifact_timeline_label(
                            item,
                            artifact,
                            feedback.get(artifact.id),
                        )
                        for artifact in detail.artifacts
                    ),
                    occurred_at=max(artifact.created_at for artifact in detail.artifacts),
                )
            )
        elif item.status == WorkItemStatus.COMPLETED:
            entries.append(
                TimelineEntryView(
                    id=f"{item.id}:no-artifact",
                    kind=TimelineKind.ARTIFACT,
                    title="交付结果",
                    summary="任务已完成，但没有登记可交付产物。",
                    details=(),
                    occurred_at=item.completed_at or item.updated_at,
                )
            )
        return entries

    @staticmethod
    def _feedback_label(
        feedback: Optional[ArtifactFeedback],
        policy: ArtifactReviewPolicy,
    ) -> str:
        if feedback is None:
            if policy == ArtifactReviewPolicy.OPTIONAL:
                return "可选反馈"
            if policy == ArtifactReviewPolicy.NONE:
                return "无需反馈"
            return "待验收"
        return _FEEDBACK_LABELS.get(feedback.decision, feedback.decision.value)

    def _artifact_timeline_label(
        self,
        item: WorkItem,
        artifact: Artifact,
        feedback: Optional[ArtifactFeedback],
    ) -> str:
        return (
            f"{artifact.name} · {_ARTIFACT_KIND_LABELS[artifact.kind]}"
            f" · {self._feedback_label(feedback, self._review_policy(item, artifact))}"
        )

    @staticmethod
    def _review_policy(item: WorkItem, artifact: Artifact) -> ArtifactReviewPolicy:
        override = str(artifact.metadata.get("review_policy") or "").strip()
        if override:
            try:
                return ArtifactReviewPolicy(override)
            except ValueError:
                pass
        return item.artifact_review_policy

    @staticmethod
    def _primary_action(
        item: WorkItem,
        *,
        pending_count: int,
        has_draft_plan: bool,
        artifact_count: int,
    ) -> PrimaryActionView:
        if pending_count:
            return PrimaryActionView("approval", "处理审批", True)
        if has_draft_plan:
            return PrimaryActionView("plan", "确认执行计划", True)
        if item.status in {WorkItemStatus.DRAFT, WorkItemStatus.READY}:
            return PrimaryActionView("start", "开始执行", True)
        if item.status == WorkItemStatus.PAUSED:
            return PrimaryActionView("resume", "继续执行", True)
        if item.status == WorkItemStatus.FAILED:
            return PrimaryActionView("retry", "检查并重试", True)
        if item.status == WorkItemStatus.COMPLETED and artifact_count:
            return PrimaryActionView("artifacts", "查看交付物", True)
        if item.status == WorkItemStatus.COMPLETED:
            return PrimaryActionView(None, "任务已完成", False)
        return PrimaryActionView(None, _STATUS_LABELS[item.status], False)


class TaskWorkspaceQueryService:
    """为所有前端提供一致的任务列表、待处理状态和详情投影。"""

    def __init__(
        self,
        *,
        work_items: WorkItemReader,
        actions: ActionReader,
        projector: Optional[TaskWorkspaceProjector] = None,
    ):
        self.work_items = work_items
        self.actions = actions
        self.projector = projector or TaskWorkspaceProjector()

    def get(self, work_item_id: str) -> TaskWorkspaceView:
        detail = self.work_items.detail(work_item_id)
        proposals = self._proposals_for(detail, self.actions.list(limit=2000))
        return self.projector.project(detail, proposals)

    def list(
        self,
        *,
        scope: TaskWorkspaceScope = TaskWorkspaceScope.ALL,
        query: str = "",
        limit: int = 100,
    ) -> List[TaskWorkspaceView]:
        if not isinstance(scope, TaskWorkspaceScope):
            scope = TaskWorkspaceScope(scope)
        normalized_query = query.strip().casefold()
        proposals = self.actions.list(limit=2000)
        views = []
        source_limit = max(limit, min(limit * 10, 2000))
        seen_series = set()
        for item in self.work_items.list(limit=source_limit):
            series_identity = self._series_identity(item)
            if series_identity and series_identity in seen_series:
                continue
            if series_identity:
                seen_series.add(series_identity)
            if normalized_query and normalized_query not in (
                f"{item.title}\n{item.objective}".casefold()
            ):
                continue
            detail = self.work_items.detail(item.id)
            view = self.projector.project(
                detail,
                self._proposals_for(detail, proposals),
            )
            if self._matches_scope(view, scope):
                views.append(view)
                if len(views) >= limit:
                    break
        return views

    @staticmethod
    def _series_identity(item: WorkItem) -> Optional[str]:
        if item.series_key:
            return item.series_key
        if item.kind != WorkItemKind.AUTOMATION:
            return None
        scheduled_task_id = str(item.metadata.get("scheduled_task_id") or "").strip()
        return f"scheduler:{scheduled_task_id}" if scheduled_task_id else None

    @staticmethod
    def _proposals_for(
        detail: WorkItemDetail,
        proposals: Sequence[ActionProposal],
    ) -> List[ActionProposal]:
        run_ids = {run.id for run in detail.runs}
        return [
            proposal
            for proposal in proposals
            if proposal.run_id in run_ids or proposal.execution_run_id in run_ids
        ]

    @staticmethod
    def _matches_scope(
        view: TaskWorkspaceView,
        scope: TaskWorkspaceScope,
    ) -> bool:
        if scope == TaskWorkspaceScope.ALL:
            return True
        if scope == TaskWorkspaceScope.ATTENTION:
            return view.requires_attention
        if scope == TaskWorkspaceScope.UPDATES:
            return view.has_updates
        if scope == TaskWorkspaceScope.FINISHED:
            return view.status.terminal
        return not view.status.terminal
