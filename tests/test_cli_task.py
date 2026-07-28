from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from llm_chat.cli import cli
from llm_chat.runtime import Run, RunStatus, RunType
from llm_chat.work import (
    Artifact,
    ArtifactKind,
    WorkItem,
    WorkItemDetail,
    WorkItemStatus,
)


def _detail(*, status=WorkItemStatus.COMPLETED, content="任务完成"):
    now = datetime.now(timezone.utc)
    item = WorkItem(
        id="work_test",
        title="测试任务",
        objective="完成一个测试任务",
        status=status,
        root_run_id="run_test",
        latest_run_id="run_test",
        created_at=now,
        updated_at=now,
        completed_at=now if status.terminal else None,
    )
    run = Run(
        id="run_test",
        work_item_id=item.id,
        type=RunType.WORKFLOW,
        status=(
            RunStatus.COMPLETED
            if status == WorkItemStatus.COMPLETED
            else RunStatus.RUNNING
        ),
        result=content,
        created_at=now,
    )
    artifacts = (
        [
            Artifact(
                id="artifact_test",
                work_item_id=item.id,
                run_id=run.id,
                kind=ArtifactKind.TEXT,
                name="测试结果",
                content=content,
                content_preview=content,
            )
        ]
        if status == WorkItemStatus.COMPLETED
        else []
    )
    return WorkItemDetail(work_item=item, runs=[run], artifacts=artifacts)


def test_task_start_executes_and_prints_primary_artifact():
    app = MagicMock()
    detail = _detail(content="可交付结果")
    app.create_work_item.return_value = detail.work_item
    app.execute_work_item.return_value = detail

    with patch("llm_chat.cli.task._build_app", return_value=app):
        result = CliRunner().invoke(cli, ["task", "start", "完成一个测试任务"])

    assert result.exit_code == 0
    assert "可交付结果" in result.output
    app.create_work_item.assert_called_once()
    app.execute_work_item.assert_called_once_with("work_test")
    app.stop.assert_called_once()


def test_task_list_filters_and_renders_status():
    app = MagicMock()
    app.list_work_items.return_value = [_detail().work_item]

    with patch("llm_chat.cli.task._build_app", return_value=app):
        result = CliRunner().invoke(
            cli,
            ["task", "list", "--status", "completed", "--kind", "task"],
        )

    assert result.exit_code == 0
    assert "work_test" in result.output
    assert "测试任务" in result.output
    app.list_work_items.assert_called_once()


def test_task_show_json_contains_runs_and_artifacts():
    app = MagicMock()
    app.get_work_item_detail.return_value = _detail()

    with patch("llm_chat.cli.task._build_app", return_value=app):
        result = CliRunner().invoke(
            cli,
            ["task", "show", "work_test", "--json-output"],
        )

    assert result.exit_code == 0
    assert '"work_item"' in result.output
    assert '"artifact_test"' in result.output


def test_task_show_unknown_id_is_click_error():
    app = MagicMock()
    app.get_work_item_detail.side_effect = KeyError("Unknown work item: missing")

    with patch("llm_chat.cli.task._build_app", return_value=app):
        result = CliRunner().invoke(cli, ["task", "show", "missing"])

    assert result.exit_code != 0
    assert "Unknown work item" in result.output
    app.stop.assert_called_once()


def test_task_cancel_uses_application_service():
    app = MagicMock()
    app.cancel_work_item.return_value = _detail(status=WorkItemStatus.CANCELLED)

    with patch("llm_chat.cli.task._build_app", return_value=app):
        result = CliRunner().invoke(cli, ["task", "cancel", "work_test"])

    assert result.exit_code == 0
    app.cancel_work_item.assert_called_once_with("work_test")


def test_task_resume_uses_persistent_checkpoint():
    app = MagicMock()
    app.resume_work_item.return_value = _detail(status=WorkItemStatus.RUNNING)

    with patch("llm_chat.cli.task._build_app", return_value=app):
        result = CliRunner().invoke(cli, ["task", "resume", "work_test"])

    assert result.exit_code == 0
    app.resume_work_item.assert_called_once_with("work_test")
    app.stop.assert_called_once()


def test_task_pause_requests_safe_checkpoint():
    app = MagicMock()
    app.pause_work_item.return_value = _detail(status=WorkItemStatus.PAUSING)

    with patch("llm_chat.cli.task._build_app", return_value=app):
        result = CliRunner().invoke(cli, ["task", "pause", "work_test"])

    assert result.exit_code == 0
    assert "pausing" in result.output
    app.pause_work_item.assert_called_once_with("work_test")
    app.stop.assert_called_once()
