"""Capability policy and explicit action approval regressions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from ember_core.tools import BaseTool
from langgraph.runtime import Runtime

from llm_chat.app import App
from llm_chat.chat_core_graph import (
    ChatCoreGraph,
    ChatGraphState,
    _execute_tools_node,
)
from llm_chat.pipeline.stage import PipelineContext
from llm_chat.runtime import (
    ActionProposalManager,
    ActionStatus,
    Capability,
    CapabilityPolicy,
    PolicyDecision,
    RunManager,
    RunStatus,
    RunType,
)
from llm_chat.runtime.chat_execution import ChatRuntimeContext, SerializableToolCall
from llm_chat.tools.registry import ToolRegistry


class RecordingWriteTool(BaseTool):
    def __init__(self):
        self.calls = []

    @property
    def name(self):
        return "write_file"

    @property
    def description(self):
        return "write a file"

    def get_parameters_schema(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return "written"


def test_default_policy_requires_approval_for_side_effects():
    policy = CapabilityPolicy()

    decision, capabilities = policy.evaluate("write_file")
    assert decision == PolicyDecision.REQUIRE_APPROVAL
    assert capabilities == {Capability.WORKSPACE_WRITE}
    assert policy.evaluate("web_search")[0] == PolicyDecision.ALLOW
    assert policy.evaluate("calculator")[0] == PolicyDecision.ALLOW

    deny_all = CapabilityPolicy(allowed=set(), require_approval=set())
    assert deny_all.evaluate("calculator")[0] == PolicyDecision.DENY


def test_graph_proposes_instead_of_executing_high_impact_tool():
    registry = ToolRegistry.create_isolated()
    tool = RecordingWriteTool()
    registry.register(tool)
    ToolRegistry.set_instance(registry)

    runs = RunManager()
    run = runs.start(RunType.CHAT)
    proposals = ActionProposalManager()
    ctx = PipelineContext(conversation_id="conv", user_message="write")
    ctx._extra = {
        "capability_policy": CapabilityPolicy(),
        "action_proposals": proposals,
        "run_manager": runs,
        "run_id": run.id,
        "tool_registry": registry,
    }
    state = ChatGraphState.from_pipeline_context(ctx).model_copy(
        update={
            "pending_tool_calls": [
                SerializableToolCall(
                    id="call-1",
                    name="write_file",
                    arguments={"file_path": "a.txt", "content": "hello"},
                )
            ]
        }
    )
    runtime = Runtime(context=ChatRuntimeContext.from_pipeline_context(ctx))
    try:
        update = asyncio.run(_execute_tools_node(state, runtime))
    finally:
        ToolRegistry.reset()

    pending = proposals.list(status=ActionStatus.PENDING)
    assert tool.calls == []
    assert len(pending) == 1
    assert pending[0].tool_name == "write_file"
    assert "requires user approval" in update["tool_messages"][0]["content"]
    assert any(event.type == "action.proposed" for event in runs.get(run.id).events)


def test_approval_command_executes_once_in_a_child_tool_run():
    registry = ToolRegistry.create_isolated()
    tool = RecordingWriteTool()
    registry.register(tool)
    ToolRegistry.set_instance(registry)
    runs = RunManager()
    origin = runs.start(RunType.CHAT)
    proposals = ActionProposalManager()
    proposal = proposals.propose(
        run_id=origin.id,
        tool_name="write_file",
        arguments={"file_path": "a.txt", "content": "hello"},
        capabilities={Capability.WORKSPACE_WRITE},
    )

    core = object.__new__(ChatCoreGraph)
    core.action_proposals = proposals
    core.run_manager = runs
    core.conversation_manager = MagicMock()
    command_run = runs.start(RunType.CHAT)
    try:
        response = core._handle_action_command(
            "conv",
            f"/approve-action {proposal.id}",
            command_run_id=command_run.id,
        )
    finally:
        ToolRegistry.reset()

    assert "执行完成" in response
    assert tool.calls == [{"file_path": "a.txt", "content": "hello"}]
    assert proposals.get(proposal.id).status == ActionStatus.COMPLETED
    child = runs.children(command_run.id)[0]
    assert child.type == RunType.TOOL
    assert child.status == RunStatus.COMPLETED

    second = core._handle_action_command(
        "conv",
        f"/approve-action {proposal.id}",
        command_run_id=command_run.id,
    )
    assert "not pending" in second
    assert len(tool.calls) == 1


def test_action_cannot_be_approved_from_another_conversation():
    manager = ActionProposalManager()
    proposal = manager.propose(
        run_id="run-origin",
        conversation_id="conv-a",
        tool_name="write_file",
        arguments={},
        capabilities={Capability.WORKSPACE_WRITE},
    )

    try:
        manager.reject(proposal.id, conversation_id="conv-b")
    except ValueError as exc:
        assert "another conversation" in str(exc)
    else:
        raise AssertionError("cross-conversation action approval was accepted")


def test_app_exposes_shared_approval_api_for_gui():
    registry = ToolRegistry.create_isolated()
    tool = RecordingWriteTool()
    registry.register(tool)
    runs = RunManager()
    origin = runs.start(RunType.CHAT, conversation_id="conv")
    proposals = ActionProposalManager()

    approved = proposals.propose(
        run_id=origin.id,
        conversation_id="conv",
        tool_name="write_file",
        arguments={"file_path": "approved.txt"},
        capabilities={Capability.WORKSPACE_WRITE},
    )
    rejected = proposals.propose(
        run_id=origin.id,
        conversation_id="conv",
        tool_name="write_file",
        arguments={"file_path": "rejected.txt"},
        capabilities={Capability.WORKSPACE_WRITE},
    )

    app = object.__new__(App)
    app.tool_registry = registry
    app.run_manager = runs
    app.action_proposals = proposals

    completed = app.approve_action(approved.id, conversation_id="conv")
    denied = app.reject_action(rejected.id, conversation_id="conv")

    assert completed.status == ActionStatus.COMPLETED
    assert denied.status == ActionStatus.REJECTED
    assert tool.calls == [{"file_path": "approved.txt"}]
    event_types = [event.type for event in runs.get(origin.id).events]
    assert "action.completed" in event_types
    assert "action.rejected" in event_types
