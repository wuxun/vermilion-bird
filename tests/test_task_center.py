from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from llm_chat.frontends.tasks import TaskCenterDialog  # noqa: E402
from llm_chat.runtime import (  # noqa: E402
    ActionProposal,
    ActionStatus,
    Capability,
    Run,
    RunStatus,
    RunType,
)
from llm_chat.work import (  # noqa: E402
    Artifact,
    ArtifactKind,
    GrantStatus,
    PlanRevision,
    PlanStatus,
    PlanStep,
    ResourceGrant,
    ResourceType,
    WorkItem,
    WorkItemDetail,
    WorkItemStatus,
)


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _detail(status=WorkItemStatus.COMPLETED):
    now = datetime.now(timezone.utc)
    item = WorkItem(
        id="work_gui",
        title="生成产品规划",
        objective="生成一份完整的产品规划文档",
        status=status,
        root_run_id="run_gui",
        latest_run_id="run_gui",
        created_at=now,
        updated_at=now,
        completed_at=now if status.terminal else None,
    )
    run_status = {
        WorkItemStatus.COMPLETED: RunStatus.COMPLETED,
        WorkItemStatus.FAILED: RunStatus.FAILED,
        WorkItemStatus.RUNNING: RunStatus.RUNNING,
    }.get(status, RunStatus.PAUSED)
    run = Run(
        id="run_gui",
        work_item_id=item.id,
        type=RunType.WORKFLOW,
        status=run_status,
        created_at=now,
    )
    artifact = Artifact(
        id="artifact_gui",
        work_item_id=item.id,
        run_id=run.id,
        kind=ArtifactKind.REPORT,
        name="product-plan.md",
        uri="/tmp/product-plan.md",
    )
    return WorkItemDetail(work_item=item, runs=[run], artifacts=[artifact])


def _fake_app(detail, *, actions=None, can_retry=None, can_resume=False):
    service = MagicMock()
    service.subscribe.return_value = lambda: None
    if can_retry is None:
        can_retry = detail.work_item.status == WorkItemStatus.FAILED
    return SimpleNamespace(
        work_items=service,
        list_work_items=lambda **_kwargs: [detail.work_item],
        get_work_item_detail=lambda _work_item_id: detail,
        list_work_item_actions=lambda _work_item_id: list(actions or []),
        create_work_item=MagicMock(),
        execute_work_item=MagicMock(),
        cancel_work_item=MagicMock(),
        retry_work_item=MagicMock(),
        resume_work_item=MagicMock(),
        can_retry_work_item=lambda _work_item_id: can_retry,
        can_resume_work_item=lambda _work_item_id: can_resume,
        can_pause_work_item=lambda _work_item_id: False,
        approve_action=MagicMock(),
        reject_action=MagicMock(),
        approve_work_item_plan=MagicMock(),
        create_resource_grant=MagicMock(),
        revoke_resource_grant=MagicMock(),
        run_manager=MagicMock(),
        action_proposals=MagicMock(),
    )


def test_task_center_renders_product_task_runs_and_artifacts(qt_app):
    detail = _detail()
    dialog = TaskCenterDialog(_fake_app(detail))
    qt_app.processEvents()

    assert dialog._table.rowCount() == 1
    assert dialog._table.item(0, 1).text() == "生成产品规划"
    assert dialog._runs_table.rowCount() == 1
    assert dialog._artifacts_table.rowCount() == 1
    assert dialog._tabs.tabText(3) == "产物 (1)"
    assert "生成一份完整的产品规划文档" in dialog._overview.toPlainText()
    assert not dialog._cancel_button.isEnabled()
    assert not dialog._retry_button.isEnabled()
    assert dialog._open_artifact_button.isEnabled()

    dialog.close()
    qt_app.processEvents()


def test_failed_task_enables_retry(qt_app):
    detail = _detail(WorkItemStatus.FAILED)
    app = _fake_app(detail)
    dialog = TaskCenterDialog(app)
    qt_app.processEvents()

    assert dialog._retry_button.isEnabled()
    assert not dialog._cancel_button.isEnabled()

    dialog.close()
    qt_app.processEvents()


def test_running_task_enables_cancel(qt_app):
    detail = _detail(WorkItemStatus.RUNNING)
    app = _fake_app(detail)
    dialog = TaskCenterDialog(app)
    qt_app.processEvents()

    assert dialog._cancel_button.isEnabled()
    assert not dialog._retry_button.isEnabled()

    dialog.close()
    qt_app.processEvents()


def test_task_center_shows_inline_pending_approval(qt_app):
    detail = _detail(WorkItemStatus.WAITING_APPROVAL)
    proposal = ActionProposal(
        id="action_gui",
        run_id="run_gui",
        tool_name="write_file",
        arguments={"path": "report.md"},
        capabilities={Capability.WORKSPACE_WRITE},
        reason="生成报告",
        impact="写入 report.md",
        status=ActionStatus.PENDING,
    )
    dialog = TaskCenterDialog(_fake_app(detail, actions=[proposal]))
    qt_app.processEvents()

    assert dialog._approvals_table.rowCount() == 1
    assert dialog._tabs.tabText(2) == "审批 (1 待处理)"
    assert dialog._approve_button.isEnabled()
    assert dialog._reject_button.isEnabled()
    assert "report.md" in dialog._action_detail_text(proposal)

    dialog.close()
    qt_app.processEvents()


def test_paused_task_enables_resume_when_handler_supports_it(qt_app):
    detail = _detail(WorkItemStatus.PAUSED)
    dialog = TaskCenterDialog(_fake_app(detail, can_resume=True))
    qt_app.processEvents()

    assert dialog._resume_button.isEnabled()
    assert not dialog._retry_button.isEnabled()

    dialog.close()
    qt_app.processEvents()


def test_task_center_renders_plan_and_resource_grants(qt_app):
    detail = _detail(WorkItemStatus.RUNNING)
    detail.plan = PlanRevision(
        id="plan_gui",
        work_item_id=detail.work_item.id,
        version=2,
        summary="先分析再交付",
        status=PlanStatus.DRAFT,
        steps=[
            PlanStep(
                id="step_gui",
                plan_revision_id="plan_gui",
                position=1,
                title="分析代码",
            )
        ],
    )
    detail.grants = [
        ResourceGrant(
            id="grant_gui",
            work_item_id=detail.work_item.id,
            capability=Capability.WORKSPACE_WRITE.value,
            resource_type=ResourceType.DIRECTORY,
            resource="/workspace/reports",
            status=GrantStatus.ACTIVE,
        )
    ]
    dialog = TaskCenterDialog(_fake_app(detail))
    qt_app.processEvents()

    assert dialog._tabs.tabText(4) == "计划 (v2)"
    assert dialog._plan_table.rowCount() == 1
    assert dialog._approve_plan_button.isEnabled()
    assert dialog._tabs.tabText(5) == "授权 (1)"
    assert dialog._grants_table.rowCount() == 1
    assert dialog._revoke_grant_button.isEnabled()

    dialog.close()
    qt_app.processEvents()
