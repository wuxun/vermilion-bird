import threading

from ember_core.tools import BaseTool

from llm_chat.app import App
from llm_chat.runtime import (
    ActionProposalManager,
    ActionStatus,
    Capability,
    DurableActionCoordinator,
    GraphExecutionService,
    LangGraphRuntime,
    RunManager,
    RunStatus,
    RunType,
    build_tool_approval_graph,
)
from llm_chat.storage import Storage
from llm_chat.tools.registry import ToolRegistry


class RecordingTool(BaseTool):
    def __init__(self):
        self.calls = []

    @property
    def name(self):
        return "write_file"

    @property
    def description(self):
        return "record a durable write"

    def get_parameters_schema(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return "written"


def _build_coordinator(db_path, tool):
    Storage.set_instance(None)
    storage = Storage(str(db_path))
    runs = RunManager(repository=storage)
    proposals = ActionProposalManager(repository=storage)
    registry = ToolRegistry.create_isolated()
    registry.register(tool)
    graph_runtime = LangGraphRuntime(str(db_path))
    service = GraphExecutionService(
        run_manager=runs,
        graph_runtime=graph_runtime,
    )
    coordinator = DurableActionCoordinator(
        proposals=proposals,
        execution_service=service,
        tool_registry=registry,
    )
    graph_runtime.register_builder(
        coordinator.GRAPH_NAME,
        build_tool_approval_graph(coordinator.execute_approved),
    )
    return storage, runs, proposals, graph_runtime, service, coordinator


def test_tool_waits_for_approval_and_resumes_after_restart(tmp_path):
    db_path = tmp_path / "durable-action.db"
    tool = RecordingTool()
    _, runs, proposals, graph_runtime, _, coordinator = _build_coordinator(
        db_path,
        tool,
    )
    origin = runs.start(
        run_type=RunType.CHAT,
        conversation_id="conv",
    )
    proposal = proposals.propose(
        run_id=origin.id,
        conversation_id="conv",
        tool_name=tool.name,
        arguments={"path": "report.md"},
        capabilities={Capability.WORKSPACE_WRITE},
    )
    prepared = coordinator.prepare(proposal)
    execution_run_id = prepared.execution_run_id

    assert execution_run_id is not None
    assert runs.get(execution_run_id).status == RunStatus.PAUSED
    assert tool.calls == []
    graph_runtime.close()

    _, restored_runs, restored_proposals, restored_graph, _, restored = _build_coordinator(
        db_path,
        tool,
    )
    restored_proposal = restored_proposals.get(proposal.id)
    assert restored_proposal is not None
    assert restored_proposal.execution_run_id == execution_run_id
    assert restored_runs.get(execution_run_id).status == RunStatus.PAUSED

    completed = restored.approve(proposal.id, conversation_id="conv")

    assert completed.status == ActionStatus.COMPLETED
    assert tool.calls == [{"path": "report.md"}]
    assert restored_runs.get(execution_run_id).status == RunStatus.COMPLETED
    restored_graph.close()
    Storage.set_instance(None)


def test_rejection_completes_graph_without_executing_tool(tmp_path):
    db_path = tmp_path / "rejected-action.db"
    tool = RecordingTool()
    _, runs, proposals, graph_runtime, _, coordinator = _build_coordinator(
        db_path,
        tool,
    )
    origin = runs.start(run_type=RunType.CHAT)
    proposal = coordinator.prepare(
        proposals.propose(
            run_id=origin.id,
            tool_name=tool.name,
            arguments={"path": "nope.md"},
            capabilities={Capability.WORKSPACE_WRITE},
        )
    )

    rejected = coordinator.reject(proposal.id)

    assert rejected.status == ActionStatus.REJECTED
    assert tool.calls == []
    durable_run = runs.get(proposal.execution_run_id)
    assert durable_run.status == RunStatus.COMPLETED
    assert durable_run.result["outcome"] == "rejected"
    graph_runtime.close()
    Storage.set_instance(None)


def test_app_shared_approval_api_uses_durable_graph(tmp_path):
    Storage.set_instance(None)
    storage = Storage(str(tmp_path / "app-action.db"))
    registry = ToolRegistry.create_isolated()
    tool = RecordingTool()
    registry.register(tool)

    app = object.__new__(App)
    app.storage = storage
    app.tool_registry = registry
    app.run_manager = RunManager(repository=storage)
    app.action_proposals = ActionProposalManager(repository=storage)
    app._graph_lock = threading.RLock()
    app.graph_runtime = None
    app.graph_execution = None
    app._action_coordinator = None

    origin = app.run_manager.start(
        RunType.CHAT,
        conversation_id="conv",
    )
    proposal = app.action_proposals.propose(
        run_id=origin.id,
        conversation_id="conv",
        tool_name=tool.name,
        arguments={"path": "app.md"},
        capabilities={Capability.WORKSPACE_WRITE},
    )
    prepared = app.prepare_action(proposal)

    completed = app.approve_action(
        prepared.id,
        conversation_id="conv",
    )

    assert completed.status == ActionStatus.COMPLETED
    assert tool.calls == [{"path": "app.md"}]
    assert app.run_manager.get(prepared.execution_run_id).status == RunStatus.COMPLETED
    app.graph_runtime.close()
    Storage.set_instance(None)
