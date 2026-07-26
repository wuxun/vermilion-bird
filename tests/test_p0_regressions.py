"""Cross-cutting regressions for the Phase 0 architecture baseline."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from llm_chat.client._base import LLMClientBase
from llm_chat.exceptions import ContentModerationError
from llm_chat.scheduler.models import Task, TaskType
from llm_chat.scheduler.scheduler import SchedulerService
from llm_chat.skills.task_delegator.context import make_agent_context
from llm_chat.skills.task_delegator.tools import SpawnSubagentTool


def test_successful_moderation_fallback_restores_shared_client_config():
    client = object.__new__(LLMClientBase)
    original = SimpleNamespace(
        model="primary",
        base_url="https://primary.example/v1",
        api_key="primary-key",
        protocol="openai",
        fallback_models=["fallback"],
        available_models=[
            SimpleNamespace(
                id="fallback",
                base_url="https://fallback.example/v1",
                api_key="fallback-key",
                protocol="anthropic",
            )
        ],
    )
    client.config = SimpleNamespace(llm=original)
    client._log_moderation_request = MagicMock()
    client.reconfigure = MagicMock()
    client._http_post_json_with_retry = MagicMock(return_value={"provider": "fallback"})

    result = client._handle_content_moderation_fallback(
        ContentModerationError("blocked"),
        lambda: ("https://request", {}, {}),
        "chat",
    )

    assert result == {"provider": "fallback"}
    assert original.model == "primary"
    assert original.base_url == "https://primary.example/v1"
    assert original.api_key == "primary-key"
    assert original.protocol == "openai"


def _webhook_task():
    now = datetime.now()
    return Task(
        id="webhook-1",
        name="Webhook",
        task_type=TaskType.WEBHOOK,
        trigger_config={},
        params={"message": "Analyze event"},
        enabled=True,
        created_at=now,
        updated_at=now,
    )


def test_webhook_passes_payload_snapshot_to_execution():
    service = object.__new__(SchedulerService)
    service._storage = MagicMock()
    service._storage.load_task.return_value = _webhook_task()
    service._execute_task = MagicMock()

    service._execute_webhook_task("webhook-1", {"event": "push"})

    task = service._execute_task.call_args.kwargs["task_override"]
    assert task.params["webhook_payload"] == {"event": "push"}


def test_webhook_converts_trigger_to_chat_input():
    service = object.__new__(SchedulerService)
    service._run_llm_chat_task = MagicMock(return_value="handled")
    task = _webhook_task()
    task.params["webhook_payload"] = {"event": "push"}

    result = service._run_webhook_task(task)

    delegated = service._run_llm_chat_task.call_args.args[0]
    assert result == "handled"
    assert delegated.task_type == TaskType.LLM_CHAT
    assert '"event": "push"' in delegated.params["message"]


def test_subagent_capabilities_are_a_strict_allowlist():
    config = SimpleNamespace(
        tools=SimpleNamespace(
            subagent_max_retries=0,
            subagent_retry_delay=0,
        )
    )
    registry = MagicMock()
    tool = SpawnSubagentTool(registry=registry, config=config)
    client = MagicMock()
    client.config.llm.model = "test-model"
    client.config.llm.protocol = "openai"
    client.get_builtin_tools.return_value = [
        {"type": "function", "function": {"name": "web_search"}},
        {"type": "function", "function": {"name": "file_writer"}},
    ]
    captured = {}

    def fake_call(_client, _agent_id, _task, tool_defs, *_args):
        captured["names"] = {definition["function"]["name"] for definition in tool_defs}
        return "done"

    tool._call_llm_with_retry = fake_call
    context = make_agent_context(
        agent_id="sub-1",
        parent_id=None,
        depth=0,
        allowed_tools={"web_search"},
        conversation_id="conv-1",
    )

    result = tool._execute_async_inner(
        "sub-1",
        "research",
        ["web_search"],
        60,
        context,
        parent_client=client,
    )

    assert result == "done"
    assert captured["names"] == {"web_search"}
