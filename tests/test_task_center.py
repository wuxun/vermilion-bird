from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from llm_chat.frontends.tasks import TaskCenterDialog  # noqa: E402
from llm_chat.runtime import Run, RunStatus, RunType  # noqa: E402
from llm_chat.work import (  # noqa: E402
    Artifact,
    ArtifactKind,
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


def _fake_app(detail):
    service = MagicMock()
    service.subscribe.return_value = lambda: None
    return SimpleNamespace(
        work_items=service,
        list_work_items=lambda **_kwargs: [detail.work_item],
        get_work_item_detail=lambda _work_item_id: detail,
        create_work_item=MagicMock(),
        execute_work_item=MagicMock(),
        cancel_work_item=MagicMock(),
        retry_work_item=MagicMock(),
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
    assert dialog._tabs.tabText(2) == "产物 (1)"
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
