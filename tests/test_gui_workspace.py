from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from llm_chat.frontends.base import Message, MessageType  # noqa: E402
from llm_chat.frontends.gui import GUIFrontend  # noqa: E402
from llm_chat.frontends.subagent_panel import SubAgentPanel  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


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


def test_gui_uses_primary_chat_and_task_workspaces(qt_app):
    frontend = GUIFrontend()
    frontend.set_app(_fake_app())
    parent = QWidget()

    frontend._setup_ui(parent)
    qt_app.processEvents()

    assert frontend._workspace_stack.count() == 2
    assert frontend._workspace_stack.currentWidget() is frontend._chat_workspace
    assert frontend._chat_nav_button.isChecked()

    frontend._on_task_center()
    assert frontend._workspace_stack.currentWidget() is frontend._task_workspace
    assert frontend._task_nav_button.isChecked()

    frontend._on_chat_workspace()
    assert frontend._workspace_stack.currentWidget() is frontend._chat_workspace
    assert frontend._chat_nav_button.isChecked()

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
    assert frontend._input_field.maximumHeight() == 72
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
        label.text() == "想做什么？"
        for label in frontend._chat_container.findChildren(QLabel)
    )

    frontend.display_message(
        Message(content="后台任务已完成", role="assistant", msg_type=MessageType.TEXT)
    )
    qt_app.processEvents()

    assert not any(
        label.text() == "想做什么？"
        for label in frontend._chat_container.findChildren(QLabel)
        if not label.isHidden()
    )
    assert frontend._welcome_widgets == []

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
