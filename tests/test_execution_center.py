from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from llm_chat.frontends.execution_center import ExecutionCenterDialog  # noqa: E402
from llm_chat.runtime import (  # noqa: E402
    ActionProposalManager,
    ActionStatus,
    Capability,
    RunManager,
    RunType,
)


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_execution_center_lists_runs_and_pending_approvals(qt_app):
    runs = RunManager()
    run = runs.start(
        RunType.CHAT,
        conversation_id="conversation",
        input={"message": "检查架构"},
    )
    runs.emit(run.id, "model.started", {"model": "test"})
    runs.complete(run.id, "done")

    proposals = ActionProposalManager()
    proposal = proposals.propose(
        run_id=run.id,
        conversation_id="conversation",
        tool_name="write_file",
        arguments={"path": "report.md"},
        capabilities={Capability.WORKSPACE_WRITE},
    )
    fake_app = SimpleNamespace(
        run_manager=runs,
        action_proposals=proposals,
    )

    dialog = ExecutionCenterDialog(fake_app)
    qt_app.processEvents()

    assert dialog._runs_table.rowCount() == 1
    assert dialog._actions_table.rowCount() == 1
    assert dialog._tabs.tabText(1) == "审批 (1)"
    assert "检查架构" in dialog._runs_table.item(0, 3).text()
    assert proposal.id in dialog._format_action_detail(proposal)

    dialog.close()
    qt_app.processEvents()


def test_execution_center_refreshes_from_runtime_observer(qt_app):
    runs = RunManager()
    proposals = ActionProposalManager()
    dialog = ExecutionCenterDialog(SimpleNamespace(run_manager=runs, action_proposals=proposals))

    run = runs.start(RunType.WORKFLOW, input={"task": "生成报告"})
    proposals.propose(
        run_id=run.id,
        tool_name="shell_exec",
        arguments={"command": "true"},
        capabilities={Capability.PROCESS},
    )
    qt_app.processEvents()

    assert dialog._runs_table.rowCount() == 1
    assert dialog._actions_table.rowCount() == 1
    assert dialog._proposal_by_id
    assert next(iter(dialog._proposal_by_id.values())).status == ActionStatus.PENDING

    dialog.close()
    qt_app.processEvents()


def test_execution_center_enables_recovery_controls_for_graph_run(qt_app):
    runs = RunManager()
    run = runs.start(
        RunType.WORKFLOW,
        input={"task": "recover me"},
        metadata={
            "graph_runtime": "langgraph",
            "graph_name": "workflow",
        },
    )
    runs.checkpoint(
        run.id,
        cursor="approval",
        state={"thread_id": run.id},
    )
    runs.pause(run.id, "test")
    proposals = ActionProposalManager()
    fake_app = SimpleNamespace(
        run_manager=runs,
        action_proposals=proposals,
        resume_run=lambda run_id: runs.get(run_id),
        retry_run=lambda run_id: runs.get(run_id),
        replay_run=lambda run_id: runs.get(run_id),
    )

    dialog = ExecutionCenterDialog(fake_app)
    qt_app.processEvents()

    assert dialog._resume_run_button.isEnabled()
    assert not dialog._retry_run_button.isEnabled()
    assert not dialog._replay_run_button.isEnabled()
    assert "恢复点" in dialog._run_detail.toPlainText()

    dialog.close()
    qt_app.processEvents()
