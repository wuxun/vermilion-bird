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
    AttentionKind,
    PlanRevision,
    PlanStatus,
    PlanStep,
    TaskWorkspaceProjector,
    TaskWorkspaceQueryService,
    TaskWorkspaceScope,
    TimelineKind,
    WorkItem,
    WorkItemDetail,
    WorkItemStatus,
)


def _detail(
    item_id: str = "work_projection",
    *,
    status: WorkItemStatus = WorkItemStatus.COMPLETED,
    with_artifact: bool = True,
) -> WorkItemDetail:
    now = datetime.now(timezone.utc)
    item = WorkItem(
        id=item_id,
        title="生成产品规划",
        objective="分析项目并交付可执行的产品规划",
        status=status,
        root_run_id=f"run_{item_id}",
        latest_run_id=f"run_{item_id}",
        metadata={"expected_deliverable": "Markdown 规划文档"},
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
