from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QWidget  # noqa: E402

from llm_chat.frontends.tasks import TaskCenterDialog  # noqa: E402
from llm_chat.frontends.tasks.task_center import NewTaskDialog  # noqa: E402
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
    ArtifactReviewPolicy,
    GrantStatus,
    PlanRevision,
    PlanStatus,
    PlanStep,
    ResourceGrant,
    ResourceType,
    WorkItem,
    WorkItemDetail,
    WorkItemKind,
    WorkItemStatus,
)


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _detail(
    status=WorkItemStatus.COMPLETED,
    *,
    work_item_id="work_gui",
    title="生成产品规划",
    objective="生成一份完整的产品规划文档",
):
    now = datetime.now(timezone.utc)
    item = WorkItem(
        id=work_item_id,
        title=title,
        objective=objective,
        status=status,
        root_run_id=f"run_{work_item_id}",
        latest_run_id=f"run_{work_item_id}",
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
        id=f"run_{work_item_id}",
        work_item_id=item.id,
        type=RunType.WORKFLOW,
        status=run_status,
        created_at=now,
    )
    artifact = Artifact(
        id=f"artifact_{work_item_id}",
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
        continue_work_item=MagicMock(),
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
        export_artifact=MagicMock(),
        submit_artifact_feedback=MagicMock(),
        run_manager=MagicMock(),
        action_proposals=MagicMock(),
    )


def test_task_center_renders_product_task_runs_and_artifacts(qt_app):
    detail = _detail()
    dialog = TaskCenterDialog(_fake_app(detail))
    qt_app.processEvents()

    assert dialog._table.rowCount() == 1
    assert "生成产品规划" in dialog._table.item(0, 0).text()
    assert "1 待处理" in dialog._table.item(0, 0).text()
    assert dialog._runs_table.rowCount() == 1
    assert dialog._artifacts_table.rowCount() == 1
    assert dialog._tabs.count() == 3
    assert dialog._tabs.tabText(1) == "交付物 (1)"
    assert "生成一份完整的产品规划文档" in dialog._timeline.toPlainText()
    assert "生成一份完整的产品规划文档" in dialog._overview.toPlainText()
    assert not dialog._cancel_action.isEnabled()
    assert not dialog._retry_action.isEnabled()
    assert dialog._primary_button.text() == "查看交付物"
    assert dialog._open_artifact_button.isEnabled()
    assert dialog._follow_up_input.isEnabled()
    dialog._follow_up_input.setPlainText("增加一份风险清单")
    assert dialog._continue_button.isEnabled()

    dialog.close()
    qt_app.processEvents()


def test_empty_task_center_only_shows_the_next_step(qt_app):
    service = MagicMock()
    service.subscribe.return_value = lambda: None
    app = SimpleNamespace(
        work_items=service,
        list_work_items=lambda **_kwargs: [],
    )

    dialog = TaskCenterDialog(app)
    qt_app.processEvents()

    assert not dialog._empty_state.isHidden()
    assert dialog._splitter.isHidden()
    assert dialog._filters_bar.isHidden()
    assert dialog._empty_action.text() == "新建第一个任务"

    dialog.close()
    qt_app.processEvents()


def test_task_workspace_filters_attention_and_searches_objective(qt_app):
    detail = _detail()
    dialog = TaskCenterDialog(_fake_app(detail))
    qt_app.processEvents()

    dialog._scope_filter.setCurrentIndex(2)
    qt_app.processEvents()
    assert dialog._table.rowCount() == 1

    dialog._scope_filter.setCurrentIndex(1)
    qt_app.processEvents()
    assert dialog._table.rowCount() == 0
    assert not dialog._empty_state.isHidden()

    dialog._scope_filter.setCurrentIndex(0)
    dialog._task_search_input.setText("完整的产品规划")
    qt_app.processEvents()
    assert dialog._table.rowCount() == 1

    dialog._task_search_input.setText("不存在的任务")
    qt_app.processEvents()
    assert dialog._table.rowCount() == 0
    assert dialog._empty_action.text() == "清除筛选"

    dialog.close()
    qt_app.processEvents()


def test_task_workspace_filter_keeps_detail_in_sync(qt_app):
    first = _detail(
        work_item_id="work_hourly",
        title="每小时检查",
        objective="检查系统状态",
    )
    second = _detail(
        work_item_id="work_greeting",
        title="每日问候",
        objective="发送每日问候",
    )
    details = {
        first.work_item.id: first,
        second.work_item.id: second,
    }
    service = MagicMock()
    service.subscribe.return_value = lambda: None
    app = SimpleNamespace(
        work_items=service,
        list_work_items=lambda **_kwargs: [first.work_item, second.work_item],
        get_work_item_detail=lambda work_item_id: details[work_item_id],
        list_work_item_actions=lambda _work_item_id: [],
        can_retry_work_item=lambda _work_item_id: False,
        can_resume_work_item=lambda _work_item_id: False,
        can_pause_work_item=lambda _work_item_id: False,
    )

    dialog = TaskCenterDialog(app)
    qt_app.processEvents()
    assert dialog._detail_title.text() == "每小时检查"

    dialog._task_search_input.setText("每日问候")
    qt_app.processEvents()
    assert dialog._table.rowCount() == 1
    assert dialog._selected_work_item_id == "work_greeting"
    assert dialog._detail_title.text() == "每日问候"

    dialog._task_search_input.setText("不存在的任务")
    qt_app.processEvents()
    assert dialog._selected_work_item_id is None
    assert dialog._detail_title.text() == "选择一个任务"

    dialog.close()
    qt_app.processEvents()


def test_optional_automation_result_uses_updates_scope_not_attention(qt_app):
    detail = _detail()
    detail.work_item.kind = WorkItemKind.AUTOMATION
    detail.work_item.artifact_review_policy = ArtifactReviewPolicy.OPTIONAL
    dialog = TaskCenterDialog(_fake_app(detail))
    qt_app.processEvents()

    assert "1 新结果" in dialog._table.item(0, 0).text()
    assert dialog._tabs.tabText(0) == "进展 · 1 新结果"
    assert dialog._attention_panel.title() == "新结果"
    assert "可选反馈" == dialog._artifacts_table.item(0, 2).text()

    dialog._scope_filter.setCurrentIndex(2)
    qt_app.processEvents()
    assert dialog._table.rowCount() == 0

    dialog._scope_filter.setCurrentIndex(3)
    qt_app.processEvents()
    assert dialog._table.rowCount() == 1

    dialog.close()
    qt_app.processEvents()


def test_failed_task_enables_retry(qt_app):
    detail = _detail(WorkItemStatus.FAILED)
    app = _fake_app(detail)
    dialog = TaskCenterDialog(app)
    qt_app.processEvents()

    assert dialog._retry_action.isEnabled()
    assert not dialog._cancel_action.isEnabled()
    assert dialog._primary_button.text() == "重试任务"

    dialog.close()
    qt_app.processEvents()


def test_running_task_enables_cancel(qt_app):
    detail = _detail(WorkItemStatus.RUNNING)
    app = _fake_app(detail)
    dialog = TaskCenterDialog(app)
    qt_app.processEvents()

    assert dialog._cancel_action.isEnabled()
    assert not dialog._retry_action.isEnabled()
    assert dialog._primary_button.text() == "执行中"

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
    assert dialog._tabs.tabText(0) == "进展 · 1 待处理"
    assert dialog._approve_button.isEnabled()
    assert dialog._reject_button.isEnabled()
    assert dialog._primary_button.text() == "处理审批"
    assert "写入 report.md" in dialog._timeline.toPlainText()
    assert "report.md" in dialog._action_detail_text(proposal)

    dialog.close()
    qt_app.processEvents()


def test_paused_task_enables_resume_when_handler_supports_it(qt_app):
    detail = _detail(WorkItemStatus.PAUSED)
    dialog = TaskCenterDialog(_fake_app(detail, can_resume=True))
    qt_app.processEvents()

    assert dialog._resume_action.isEnabled()
    assert not dialog._retry_action.isEnabled()
    assert dialog._primary_button.text() == "继续执行"

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

    assert dialog._detail_tabs.tabText(1) == "计划 (v2)"
    assert dialog._plan_table.rowCount() == 1
    assert dialog._approve_plan_button.isEnabled()
    assert dialog._detail_tabs.tabText(2) == "权限 (1)"
    assert dialog._grants_table.rowCount() == 1
    assert dialog._revoke_grant_button.isEnabled()
    assert dialog._primary_button.text() == "确认执行计划"
    assert "分析代码" in dialog._timeline.toPlainText()

    dialog.close()
    qt_app.processEvents()


def test_task_center_can_be_embedded_as_main_workspace(qt_app):
    detail = _detail()
    parent = QWidget()
    workspace = TaskCenterDialog(_fake_app(detail), parent, embedded=True)
    qt_app.processEvents()

    assert not workspace.isWindow()
    assert workspace._tabs.tabText(0) == "进展 · 1 待处理"
    assert workspace._tabs.tabText(2) == "详细信息"

    workspace.close()
    parent.close()
    qt_app.processEvents()


def test_new_task_dialog_collects_execution_context(qt_app):
    dialog = NewTaskDialog()
    cancel_button = dialog.findChild(QDialogButtonBox).button(
        QDialogButtonBox.StandardButton.Cancel
    )
    assert cancel_button.text() == "取消"
    assert dialog._optional_fields.isHidden()
    dialog._more_options_button.setChecked(True)
    assert not dialog._optional_fields.isHidden()
    dialog.objective_input.setPlainText("审查项目并输出报告")
    dialog.title_input.setText("项目审查")
    dialog.workspace_input.setText("/workspace/project")
    dialog.deliverable_input.setText("Markdown 报告")

    assert dialog.objective == "审查项目并输出报告"
    assert dialog.title == "项目审查"
    assert dialog.workspace == "/workspace/project"
    assert dialog.expected_deliverable == "Markdown 报告"
    assert dialog.start_immediately.isChecked()

    dialog.close()
    qt_app.processEvents()
