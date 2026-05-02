from typing import Dict, Any, List, Optional
from .base import BaseTool


class ToolRegistry:
    _instance: Optional["ToolRegistry"] = None

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools: Dict[str, BaseTool] = {}
        return cls._instance

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def get_all_tools(self) -> List[BaseTool]:
        return list(self._tools.values())

    def get_tools_for_openai(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def get_tools_for_anthropic(self) -> List[Dict[str, Any]]:
        return [tool.to_anthropic_tool() for tool in self._tools.values()]

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def clear(self):
        self._tools.clear()

    def execute_tool(
        self, name: str, arguments: Optional[Dict[str, Any]] = None, **kwargs
    ) -> str:
        tool = self.get_tool(name)
        if tool is None:
            raise ValueError(f"Tool not found: {name}")
        if arguments is not None:
            return tool.execute(**arguments)
        return tool.execute(**kwargs)

    @classmethod
    def reset(cls):
        """重置单例 — 供测试使用。"""
        if cls._instance is not None:
            cls._instance._tools.clear()
            cls._instance = None


def get_tool_registry() -> ToolRegistry:
    return ToolRegistry()
