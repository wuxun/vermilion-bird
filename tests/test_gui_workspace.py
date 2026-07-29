from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QLabel, QMainWindow, QWidget  # noqa: E402

from llm_chat.frontends.base import Message, MessageType  # noqa: E402
from llm_chat.frontends.gui import GUIFrontend  # noqa: E402
from llm_chat.frontends.subagent_panel import SubAgentPanel  # noqa: E402
from llm_chat.runtime import RunType  # noqa: E402
from llm_chat.work import WorkItem, WorkItemStatus  # noqa: E402

def _fake_app():
    work_items = MagicMock()
    work_items.subscribe.return_value = lambda: None
    action_proposals = MagicMock()
    action_proposals.list.return_value = []
    return SimpleNamespace(
        work_items=work_items,
        action_proposals=action_proposals,
        list_work_items=lambda **_kwargs: [],
    )


def test_gui_uses_chat_as_primary_workspace_and_work_overview_as_aggregate(qt_app):
    frontend = GUIFrontend()
    frontend.set_app(_fake_app())
    parent = QWidget()

    frontend._setup_ui(parent)
    qt_app.processEvents()

    assert frontend._workspace_stack.count() == 2
    assert frontend._workspace_stack.currentWidget() is frontend._chat_workspace
    assert frontend._chat_nav_button is None
    assert not frontend._task_nav_button.isChecked()

    frontend._on_task_center()
    assert frontend._workspace_stack.currentWidget() is frontend._task_workspace
    assert frontend._task_nav_button.isChecked()
    assert frontend._conversation_list.selectedItems() == []

    frontend._on_chat_workspace()
    assert frontend._workspace_stack.currentWidget() is frontend._chat_workspace
    assert not frontend._task_nav_button.isChecked()

    parent.close()
    qt_app.processEvents()


def test_workspace_shortcut_is_retained_and_opens_work_overview(qt_app):
    frontend = GUIFrontend()
    frontend.set_app(_fake_app())
    main_window = QMainWindow()
    parent = QWidget()
    main_window.setCentralWidget(parent)
    frontend._main_window = main_window

    frontend._setup_ui(parent)
    frontend._setup_shortcuts()
    frontend._shortcuts["Ctrl+Shift+T"].activated.emit()
    qt_app.processEvents()

    assert len(frontend._shortcuts) == 7
    assert frontend._workspace_stack.currentWidget() is frontend._task_workspace
    assert frontend._task_nav_button.isChecked()

    main_window.close()
    qt_app.processEvents()


def test_task_navigation_surfaces_attention_count(qt_app):
    frontend = GUIFrontend()
    app = _fake_app()
    app.list_task_workspace_views = lambda **_kwargs: []
    frontend.set_app(app)
    parent = QWidget()

    frontend._setup_ui(parent)
    app.list_task_workspace_views = lambda **_kwargs: [object(), object()]
    frontend._update_execution_center_indicator()

    assert frontend._task_nav_button.text() == "◎  工作概览    2"
    assert "2 项待处理" in frontend._task_nav_button.toolTip()

    parent.close()
    qt_app.processEvents()


def test_chat_workspace_keeps_idle_runtime_details_out_of_view(qt_app):
    frontend = GUIFrontend()
    frontend.set_app(_fake_app())
    parent = QWidget()

    frontend._setup_ui(parent)
    qt_app.processEvents()

    assert frontend._subagent_panel.isHidden()
    assert frontend._context_label.isHidden()
    assert frontend._cost_label.isHidden()
    assert frontend._send_button.text() == "↑"
    assert frontend._input_field.maximumHeight() == 132
    assert frontend._input_field.placeholderText() == "输入消息，或描述想完成的工作"
    assert (
        frontend._conversation_list.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )

    parent.close()
    qt_app.processEvents()


def test_first_real_message_replaces_welcome_state(qt_app):
    frontend = GUIFrontend()
    frontend.set_app(_fake_app())
    parent = QWidget()

    frontend._setup_ui(parent)
    frontend._show_welcome_state()
    assert any(
        label.text() == "今天想完成什么？"
        for label in frontend._chat_container.findChildren(QLabel)
    )

    frontend.display_message(
        Message(content="后台任务已完成", role="assistant", msg_type=MessageType.TEXT)
    )
    qt_app.processEvents()

    assert not any(
        label.text() == "今天想完成什么？"
        for label in frontend._chat_container.findChildren(QLabel)
        if not label.isHidden()
    )
    assert frontend._welcome_widgets == []

    parent.close()
    qt_app.processEvents()


def test_codex_like_shell_uses_single_sidebar_and_contextual_composer(qt_app):
    frontend = GUIFrontend()
    frontend.set_app(_fake_app())
    parent = QWidget()

    frontend._setup_ui(parent)
    qt_app.processEvents()

    assert frontend._sidebar.width() == 260
    assert parent.findChildren(QWidget, "navigationRail") == []
    assert frontend._new_conv_button.text() == "✎  新建对话"
    assert frontend._chat_title_label.text() == "新对话"
    assert frontend._composer_add_button.toolTip() == "添加上下文或文件"

    frontend._toggle_sidebar()
    assert frontend._sidebar.width() == 54
    assert frontend._task_nav_button.text() == "◎"
    assert frontend._conversation_list.isHidden()

    frontend._toggle_sidebar()
    assert frontend._sidebar.width() == 260
    assert frontend._task_nav_button.text() == "◎  工作概览"

    parent.close()
    qt_app.processEvents()


def test_untitled_conversation_uses_human_label(qt_app):
    frontend = GUIFrontend(conversation_id="conv_empty")
    frontend.set_app(_fake_app())
    parent = QWidget()

    frontend._setup_ui(parent)
    frontend.update_conversation_list([{"id": "conv_empty", "title": None}])

    assert frontend._conversation_list.item(0).text() == "新对话"
    assert frontend._conversation_list.item(0).data(Qt.ItemDataRole.UserRole) == "conv_empty"

    parent.close()
    qt_app.processEvents()


def test_conversation_goal_is_progressively_disclosed_in_chat(qt_app):
    frontend = GUIFrontend(conversation_id="conv_goal")
    app = _fake_app()
    goal = WorkItem(
        id="work_goal",
        title="完成架构评审",
        objective="评审架构并交付修改建议",
        status=WorkItemStatus.RUNNING,
        conversation_id="conv_goal",
    )
    app.get_conversation_work_item = lambda _conversation_id: goal
    frontend.set_app(app)
    parent = QWidget()

    frontend._setup_ui(parent)
    frontend._refresh_goal_state()

    assert not frontend._goal_frame.isHidden()
    assert frontend._goal_title_label.text() == "完成架构评审"
    assert frontend._goal_status_label.text() == "目标 · 执行中"
    assert frontend._goal_menu_action.text() == "查看目标进展"

    parent.close()
    qt_app.processEvents()


def test_goal_turn_uses_workflow_run_and_materializes_result(qt_app, monkeypatch):
    class InlineThread:
        """Run the worker inline so Qt teardown cannot race a test thread."""

        def __init__(self, *, target, daemon):
            self._target = target
            self.daemon = daemon

        def start(self):
            self._target()

        def join(self, timeout=None):
            return None

    monkeypatch.setattr("llm_chat.frontends.gui.threading.Thread", InlineThread)
    frontend = GUIFrontend(conversation_id="conv_goal")
    app = _fake_app()
    goal = WorkItem(
        id="work_goal",
        title="完成架构评审",
        objective="评审架构并交付修改建议",
        status=WorkItemStatus.READY,
        conversation_id="conv_goal",
    )
    app.get_conversation_work_item = lambda _conversation_id: goal
    app.finalize_work_item_result = MagicMock()
    frontend.set_app(app)
    frontend._chat_core = MagicMock()
    frontend._chat_core.send_message_stream.return_value = "执行完成"
    frontend._stream_signals = MagicMock()
    frontend._card_signals = MagicMock()
    parent = QWidget()
    frontend._setup_ui(parent)

    frontend._start_streaming("继续执行")
    frontend._worker_thread.join(timeout=5)

    call = frontend._chat_core.send_message_stream.call_args
    assert call.kwargs["conversation_id"] == "conv_goal"
    assert call.kwargs["work_item_id"] == "work_goal"
    assert call.kwargs["run_type"] == RunType.WORKFLOW
    app.finalize_work_item_result.assert_called_once_with("work_goal")

    parent.close()
    qt_app.processEvents()


def test_subagent_panel_only_appears_when_work_exists(qt_app):
    registry = MagicMock()
    panel = SubAgentPanel()

    panel.connect_registry(registry)
    assert panel.isHidden()

    panel._on_status("agent-1", "running", "检查项目", "", "{}")
    assert not panel.isHidden()

    panel._remove_entry("agent-1")
    assert panel.isHidden()
    panel.close()
