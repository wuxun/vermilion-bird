from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from llm_chat.app import App
from llm_chat.runtime import RunType
from llm_chat.work import WorkItem, WorkItemKind, WorkItemStatus


def _app_for_item(item):
    app = App.__new__(App)
    app.work_items = MagicMock()
    app.work_items.get.return_value = item
    app.chat_core = MagicMock()
    app.storage = MagicMock()
    app.storage.get_conversation.return_value = object()
    app.conversation_manager = MagicMock()
    app._materialize_work_item_result = MagicMock(return_value="detail")
    return app


def test_continue_work_item_reuses_task_context_and_creates_follow_up_run():
    item = WorkItem(
        id="work_follow_up",
        title="产品规划",
        objective="生成产品规划",
        status=WorkItemStatus.COMPLETED,
        conversation_id="conversation_follow_up",
    )
    app = _app_for_item(item)

    result = app.continue_work_item(item.id, "增加风险清单")

    assert result == "detail"
    call = app.chat_core.send_message.call_args
    assert call.kwargs["conversation_id"] == item.conversation_id
    assert call.kwargs["work_item_id"] == item.id
    assert call.kwargs["run_type"] == RunType.WORKFLOW
    assert "生成产品规划" in call.kwargs["message"]
    assert "增加风险清单" in call.kwargs["message"]
    app.work_items.reconcile.assert_called_once_with()
    app._materialize_work_item_result.assert_called_once_with(item.id)


def test_continue_work_item_rejects_concurrent_execution():
    item = WorkItem(
        id="work_running",
        title="运行中任务",
        objective="保持运行",
        status=WorkItemStatus.RUNNING,
    )
    app = _app_for_item(item)

    with pytest.raises(ValueError, match="仍在运行"):
        app.continue_work_item(item.id, "改变方向")

    app.chat_core.send_message.assert_not_called()


def test_continue_work_item_binds_a_conversation_when_missing():
    item = WorkItem(
        id="work_without_conversation",
        title="无会话任务",
        objective="生成报告",
        status=WorkItemStatus.FAILED,
    )
    app = _app_for_item(item)
    app.conversation_manager.create_conversation.return_value = SimpleNamespace(
        conversation_id="conversation_created"
    )
    bound = item.model_copy(update={"conversation_id": "conversation_created"})
    app.work_items.bind_conversation.return_value = bound

    app.continue_work_item(item.id, "修复后重试")

    app.work_items.bind_conversation.assert_called_once_with(
        item.id,
        "conversation_created",
    )
    assert app.chat_core.send_message.call_args.kwargs["conversation_id"] == "conversation_created"


def test_promote_conversation_to_work_item_reuses_history_and_is_idempotent():
    app = App.__new__(App)
    app.storage = MagicMock()
    app.storage.get_conversation.return_value = {
        "id": "conversation_goal",
        "title": "架构讨论",
    }
    app.work_items = MagicMock()
    app.work_items.list.return_value = []
    created = WorkItem(
        id="work_goal",
        title="架构讨论",
        objective="完成架构评审",
        conversation_id="conversation_goal",
    )
    app.work_items.create.return_value = created

    result = app.promote_conversation_to_work_item(
        "conversation_goal",
        "完成架构评审",
        expected_deliverable="评审报告",
    )

    assert result == created
    app.work_items.create.assert_called_once_with(
        objective="完成架构评审",
        title="架构讨论",
        kind=WorkItemKind.TASK,
        conversation_id="conversation_goal",
        series_key=None,
        artifact_review_policy=created.artifact_review_policy,
        workspace=None,
        idempotency_key="conversation-goal:conversation_goal",
        metadata={
            "source": "conversation_goal",
            "promoted_from_conversation": True,
            "expected_deliverable": "评审报告",
        },
    )

    app.work_items.list.return_value = [created]
    assert (
        app.promote_conversation_to_work_item(
            "conversation_goal",
            "不会创建第二个目标",
        )
        == created
    )
    app.work_items.create.assert_called_once()


def test_create_conversation_goal_binds_new_chat_before_execution():
    app = App.__new__(App)
    app.conversation_manager = MagicMock()
    app.conversation_manager.create_conversation.return_value = SimpleNamespace(
        conversation_id="conversation_created"
    )
    app.promote_conversation_to_work_item = MagicMock(
        return_value=WorkItem(
            id="work_created",
            title="生成报告",
            objective="生成报告",
            conversation_id="conversation_created",
        )
    )
    app.current_frontend = MagicMock()

    item = app.create_conversation_goal("生成报告")

    assert item.conversation_id == "conversation_created"
    app.conversation_manager.create_conversation.assert_called_once_with(title="生成报告")
    app.promote_conversation_to_work_item.assert_called_once_with(
        "conversation_created",
        "生成报告",
        title="生成报告",
        workspace=None,
        expected_deliverable=None,
    )
    app.current_frontend.request_conversation_list_refresh.assert_called_once_with()
