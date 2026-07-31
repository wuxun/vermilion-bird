from datetime import datetime, timedelta, timezone

from llm_chat.runtime import (
    ActionProposal,
    ActionStatus,
    Capability,
    Run,
    RunStatus,
    RunType,
)
from llm_chat.work import (
    Artifact,
    ArtifactFeedback,
    ArtifactFeedbackDecision,
    ArtifactKind,
    ArtifactReviewPolicy,
    ArtifactRelation,
    AttentionKind,
    AttentionLevel,
    PlanRevision,
    PlanStatus,
    PlanStep,
    TaskWorkspaceProjector,
    TaskWorkspaceQueryService,
    TaskWorkspaceScope,
    TimelineKind,
    WorkItem,
    WorkItemDetail,
    WorkItemKind,
    WorkItemStatus,
)


def _detail(
    item_id: str = "work_projection",
    *,
    status: WorkItemStatus = WorkItemStatus.COMPLETED,
    with_artifact: bool = True,
    kind: WorkItemKind = WorkItemKind.TASK,
    review_policy: ArtifactReviewPolicy = ArtifactReviewPolicy.REQUIRED,
    scheduled_task_id: str = "",
) -> WorkItemDetail:
    now = datetime.now(timezone.utc)
    item = WorkItem(
        id=item_id,
        title="生成产品规划",
        objective="分析项目并交付可执行的产品规划",
        kind=kind,
        status=status,
        root_run_id=f"run_{item_id}",
        latest_run_id=f"run_{item_id}",
        artifact_review_policy=review_policy,
        metadata={
            "expected_deliverable": "Markdown 规划文档",
            **(
                {"source": "scheduler", "scheduled_task_id": scheduled_task_id}
                if scheduled_task_id
                else {}
            ),
        },
        created_at=now - timedelta(minutes=10),
        updated_at=now,
        completed_at=now if status.terminal else None,
    )
    run_status = {
        WorkItemStatus.COMPLETED: RunStatus.COMPLETED,
        WorkItemStatus.FAILED: RunStatus.FAILED,
        WorkItemStatus.RUNNING: RunStatus.RUNNING,
    }.get(status, RunStatus.PAUSED)
    run = Run(
        id=f"run_{item_id}",
        work_item_id=item_id,
        type=RunType.WORKFLOW,
        status=run_status,
        created_at=now - timedelta(minutes=8),
        error="模型服务暂时不可用" if status == WorkItemStatus.FAILED else None,
    )
    artifacts = []
    if with_artifact:
        artifacts.append(
            Artifact(
                id=f"artifact_{item_id}",
                work_item_id=item_id,
                run_id=run.id,
                kind=ArtifactKind.REPORT,
                name="product-plan.md",
                created_at=now - timedelta(minutes=1),
            )
        )
    return WorkItemDetail(work_item=item, runs=[run], artifacts=artifacts)


def test_projector_builds_attention_timeline_and_primary_action():
    detail = _detail()

    view = TaskWorkspaceProjector().project(detail)

    assert view.status_label == "已完成"
    assert view.expected_deliverable == "Markdown 规划文档"
    assert view.unreviewed_artifact_count == 1
    assert [item.kind for item in view.attention] == [AttentionKind.ARTIFACT]
    assert view.primary_action.action == "artifacts"
    assert {entry.kind for entry in view.timeline} >= {
        TimelineKind.OBJECTIVE,
        TimelineKind.DELIVERABLE,
        TimelineKind.ACTIVITY,
        TimelineKind.ARTIFACT,
    }


def test_projector_prioritizes_plan_and_action_approval():
    detail = _detail(status=WorkItemStatus.RUNNING, with_artifact=False)
    now = datetime.now(timezone.utc)
    detail.plan = PlanRevision(
        id="plan_projection",
        work_item_id=detail.work_item.id,
        version=1,
        summary="先审计，再输出报告",
        status=PlanStatus.DRAFT,
        steps=[
            PlanStep(
                id="step_projection",
                plan_revision_id="plan_projection",
                position=1,
                title="审计代码",
            )
        ],
        created_at=now - timedelta(minutes=2),
    )
    proposal = ActionProposal(
        id="action_projection",
        run_id=detail.runs[0].id,
        tool_name="write_file",
        arguments={"path": "report.md"},
        capabilities={Capability.WORKSPACE_WRITE},
        reason="生成规划报告",
        impact="写入 report.md",
        status=ActionStatus.PENDING,
        created_at=now,
    )

    view = TaskWorkspaceProjector().project(detail, [proposal])

    assert {item.kind for item in view.attention} == {
        AttentionKind.PLAN,
        AttentionKind.APPROVAL,
    }
    assert view.primary_action.action == "approval"
    assert any("审计代码" in detail for entry in view.timeline for detail in entry.details)
    assert any("report.md" in detail for entry in view.timeline for detail in entry.details)


def test_feedback_removes_artifact_from_attention():
    detail = _detail()
    artifact = detail.artifacts[0]
    detail.artifact_feedback = [
        ArtifactFeedback(
            artifact_id=artifact.id,
            work_item_id=detail.work_item.id,
            decision=ArtifactFeedbackDecision.ACCEPTED,
        )
    ]

    view = TaskWorkspaceProjector().project(detail)

    assert view.unreviewed_artifact_count == 0
    assert not view.requires_attention
    artifact_entry = next(
        entry for entry in view.timeline if entry.kind == TimelineKind.ARTIFACT
    )
    assert any("已接受" in line for line in artifact_entry.details)


def test_projector_only_requires_review_for_latest_artifact_version():
    detail = _detail()
    original = detail.artifacts[0]
    revision = Artifact(
        id="artifact_revision_v2",
        work_item_id=detail.work_item.id,
        name=original.name,
        lineage_id=original.lineage_id,
        version=2,
        parent_artifact_id=original.id,
        relation=ArtifactRelation.REVISION,
    )
    detail.artifacts = [revision, original]
    detail.artifact_feedback = [
        ArtifactFeedback(
            artifact_id=original.id,
            work_item_id=detail.work_item.id,
            decision=ArtifactFeedbackDecision.NEEDS_REVISION,
        ),
        ArtifactFeedback(
            artifact_id=revision.id,
            work_item_id=detail.work_item.id,
            decision=ArtifactFeedbackDecision.ACCEPTED,
        ),
    ]

    view = TaskWorkspaceProjector().project(detail)

    assert view.artifact_count == 1
    assert view.unreviewed_artifact_count == 0
    assert not view.requires_attention


def test_optional_automation_result_is_an_update_not_a_todo():
    detail = _detail(
        "work_automation",
        kind=WorkItemKind.AUTOMATION,
        review_policy=ArtifactReviewPolicy.OPTIONAL,
        scheduled_task_id="daily-digest",
    )

    view = TaskWorkspaceProjector().project(detail)

    assert view.unreviewed_artifact_count == 1
    assert view.required_review_count == 0
    assert view.optional_review_count == 1
    assert not view.requires_attention
    assert view.has_updates
    assert view.action_required_count == 0
    assert view.notice_count == 1
    assert view.attention[0].level == AttentionLevel.NOTICE
    assert "可选反馈" in next(
        entry for entry in view.timeline if entry.kind == TimelineKind.ARTIFACT
    ).details[0]


def test_artifact_review_override_can_suppress_all_notifications():
    detail = _detail(
        "work_silent_automation",
        kind=WorkItemKind.AUTOMATION,
        review_policy=ArtifactReviewPolicy.OPTIONAL,
    )
    detail.artifacts[0].metadata["review_policy"] = ArtifactReviewPolicy.NONE.value

    view = TaskWorkspaceProjector().project(detail)

    assert not view.requires_attention
    assert not view.has_updates
    assert view.attention == ()
    assert "无需反馈" in next(
        entry for entry in view.timeline if entry.kind == TimelineKind.ARTIFACT
    ).details[0]


class _WorkItems:
    def __init__(self, details):
        self._details = {detail.work_item.id: detail for detail in details}

    def list(self, limit=50, **_kwargs):
        return [detail.work_item for detail in self._details.values()][:limit]

    def detail(self, work_item_id):
        return self._details[work_item_id]


class _Actions:
    def __init__(self, proposals=()):
        self._proposals = list(proposals)

    def list(self, **_kwargs):
        return list(self._proposals)


def test_query_service_filters_attention_and_search_without_frontend_logic():
    completed = _detail("work_completed")
    running = _detail(
        "work_running",
        status=WorkItemStatus.RUNNING,
        with_artifact=False,
    )
    running.work_item.title = "后台同步"
    service = TaskWorkspaceQueryService(
        work_items=_WorkItems([completed, running]),
        actions=_Actions(),
    )

    attention = service.list(scope=TaskWorkspaceScope.ATTENTION)
    search = service.list(query="后台")

    assert [view.work_item_id for view in attention] == ["work_completed"]
    assert [view.work_item_id for view in search] == ["work_running"]


def test_query_service_separates_updates_and_collapses_legacy_automation_series():
    latest = _detail(
        "work_latest",
        kind=WorkItemKind.AUTOMATION,
        review_policy=ArtifactReviewPolicy.OPTIONAL,
        scheduled_task_id="hourly-check",
    )
    legacy = _detail(
        "work_legacy",
        kind=WorkItemKind.AUTOMATION,
        review_policy=ArtifactReviewPolicy.OPTIONAL,
        scheduled_task_id="hourly-check",
    )
    latest.work_item.updated_at = datetime.now(timezone.utc)
    legacy.work_item.updated_at = latest.work_item.updated_at - timedelta(hours=1)
    service = TaskWorkspaceQueryService(
        work_items=_WorkItems([latest, legacy]),
        actions=_Actions(),
    )

    all_views = service.list()
    attention = service.list(scope=TaskWorkspaceScope.ATTENTION)
    updates = service.list(scope=TaskWorkspaceScope.UPDATES)

    assert [view.work_item_id for view in all_views] == ["work_latest"]
    assert attention == []
    assert [view.work_item_id for view in updates] == ["work_latest"]
