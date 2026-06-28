"""ToolRegistry — global tool registry with singleton support.

Thread-safe registration and lookup of BaseTool instances.
Supports DI injection for testing via set_instance().
"""

from typing import Dict, List, Optional, Any
from .base import BaseTool


class ToolRegistry:
    """Thread-safe registry for tool instances.

    Default behavior: global singleton via __new__.
    Test isolation: call set_instance(mock) before tests.
    """

    _instance: Optional["ToolRegistry"] = None

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools: Dict[str, BaseTool] = {}
        return cls._instance

    @classmethod
    def set_instance(cls, instance: Optional["ToolRegistry"]) -> None:
        """Inject a custom instance (for app init or test mock)."""
        cls._instance = instance

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        """Get the current instance (injected or default singleton)."""
        return cls()

    def register(self, tool: BaseTool) -> None:
        """Register a tool by its name."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """Remove a tool. Returns True if it existed."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Look up a tool by name."""
        return self._tools.get(name)

    def get_all_tools(self) -> List[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def get_tools_for_openai(self) -> List[Dict[str, Any]]:
        """Serialize all tools to OpenAI format."""
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def get_tools_for_anthropic(self) -> List[Dict[str, Any]]:
        """Serialize all tools to Anthropic format."""
        return [tool.to_anthropic_tool() for tool in self._tools.values()]

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def clear(self) -> None:
        """Remove all tools."""
        self._tools.clear()

    def execute_tool(
        self, name: str, arguments: Optional[Dict[str, Any]] = None, **kwargs
    ) -> str:
        """Look up and execute a tool by name.

        Supports two call styles:
            execute_tool("my_tool", {"arg": "val"})
            execute_tool("my_tool", arg="val")
        """
        tool = self.get_tool(name)
        if tool is None:
            raise ValueError(f"Tool not found: {name}")
        if arguments is not None:
            try:
                return tool.execute(**arguments)
            except TypeError as e:
                # LLM passed mismatched args → friendly message for self-correction
                required = getattr(tool, '_required_params', None)
                if required is None:
                    import inspect
                    sig = inspect.signature(tool.execute)
                    required = [
                        p.name for p in sig.parameters.values()
                        if p.default is inspect.Parameter.empty and p.name != 'self'
                    ]
                msg = (
                    f"参数错误：{e}。请检查并重新调用。"
                    f"必填参数：{', '.join(required)}。"
                )
                raise ValueError(msg) from e
        return tool.execute(**kwargs)

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for test teardown)."""
        if cls._instance is not None:
            cls._instance._tools.clear()
            cls._instance = None


def get_tool_registry() -> ToolRegistry:
    """Convenience: get the current ToolRegistry instance."""
    return ToolRegistry()
