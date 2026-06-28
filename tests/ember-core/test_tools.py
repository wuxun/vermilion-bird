"""Tests for ember-core tools module — BaseTool, ToolRegistry, ToolExecutor."""

import json
import pytest
from ember_core.tools import BaseTool, ToolRegistry, get_tool_registry, ToolExecutor


# ── Test Tool ──────────────────────────────────────────────────

class EchoTool(BaseTool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo back the input"

    def get_parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
            },
            "required": ["message"],
        }

    def execute(self, message: str = "", **kwargs) -> str:
        return f"echo: {message}"


class FailingTool(BaseTool):
    @property
    def name(self) -> str:
        return "failer"

    @property
    def description(self) -> str:
        return "Always fails"

    def get_parameters_schema(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> str:
        raise RuntimeError("deliberate failure")


# ── ToolRegistry tests ─────────────────────────────────────────

class TestToolRegistry:
    def test_register_and_get(self):
        ToolRegistry.reset()
        reg = ToolRegistry()
        tool = EchoTool()
        reg.register(tool)
        assert reg.has_tool("echo")
        assert reg.get_tool("echo") is tool
        assert len(reg.get_all_tools()) == 1

    def test_unregister(self):
        ToolRegistry.reset()
        reg = ToolRegistry()
        reg.register(EchoTool())
        assert reg.unregister("echo") is True
        assert reg.unregister("nonexistent") is False
        assert not reg.has_tool("echo")

    def test_execute_tool(self):
        ToolRegistry.reset()
        reg = ToolRegistry()
        reg.register(EchoTool())
        result = reg.execute_tool("echo", {"message": "hello"})
        assert result == "echo: hello"

    def test_execute_tool_not_found(self):
        ToolRegistry.reset()
        reg = ToolRegistry()
        with pytest.raises(ValueError, match="Tool not found"):
            reg.execute_tool("nonexistent", {})

    def test_execute_tool_kwargs(self):
        ToolRegistry.reset()
        reg = ToolRegistry()
        reg.register(EchoTool())
        result = reg.execute_tool("echo", message="world")
        assert result == "echo: world"

    def test_openai_format(self):
        ToolRegistry.reset()
        reg = ToolRegistry()
        reg.register(EchoTool())
        tools = reg.get_tools_for_openai()
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "echo"

    def test_singleton(self):
        ToolRegistry.reset()
        r1 = ToolRegistry()
        r2 = ToolRegistry()
        assert r1 is r2

    def test_set_instance(self):
        ToolRegistry.reset()
        mock = ToolRegistry()
        ToolRegistry.set_instance(mock)
        assert ToolRegistry.get_instance() is mock
        ToolRegistry.set_instance(None)

    def test_clear(self):
        ToolRegistry.reset()
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.clear()
        assert len(reg.get_all_tools()) == 0


# ── ToolExecutor tests ─────────────────────────────────────────

class TestToolExecutor:
    def setup_method(self):
        ToolRegistry.reset()
        self.reg = ToolRegistry()
        self.reg.register(EchoTool())

    def test_single_tool(self):
        executor = ToolExecutor(self.reg)
        results = executor.execute_tools_parallel([{
            "id": "call_1",
            "function": {"name": "echo", "arguments": json.dumps({"message": "hi"})},
        }])
        assert len(results) == 1
        assert results[0]["tool_call_id"] == "call_1"
        assert results[0]["content"] == "echo: hi"
        assert not results[0]["is_error"]

    def test_parallel_tools(self):
        executor = ToolExecutor(self.reg, max_workers=4)
        calls = [
            {"id": f"call_{i}", "function": {"name": "echo", "arguments": json.dumps({"message": f"msg{i}"})}}
            for i in range(3)
        ]
        results = executor.execute_tools_parallel(calls)
        assert len(results) == 3
        # Order preserved
        assert [r["tool_call_id"] for r in results] == ["call_0", "call_1", "call_2"]
        for r in results:
            assert not r["is_error"]

    def test_unknown_tool(self):
        executor = ToolExecutor(self.reg)
        results = executor.execute_tools_parallel([{
            "id": "c1",
            "function": {"name": "ghost", "arguments": "{}"},
        }])
        assert results[0]["is_error"]

    def test_invalid_json_args(self):
        executor = ToolExecutor(self.reg)
        results = executor.execute_tools_parallel([{
            "id": "c1",
            "function": {"name": "echo", "arguments": "not json"},
        }])
        assert results[0]["is_error"]

    def test_empty_calls(self):
        executor = ToolExecutor(self.reg)
        assert executor.execute_tools_parallel([]) == []

    def test_shutdown(self):
        executor = ToolExecutor(self.reg)
        executor.shutdown()
        assert executor._executor is None
