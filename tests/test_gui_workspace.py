from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from llm_chat.frontends.gui import GUIFrontend  # noqa: E402


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
