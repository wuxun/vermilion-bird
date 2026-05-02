from typing import Dict, Any, List, Optional
from .base import BaseTool


class ToolRegistry:
    """工具注册表。

    默认使用全局单例（get_tool_registry()）。
    App 通过 set_instance() 注入统一实例；
    测试可通过 set_instance(mock) 隔离。
    """

    _instance: Optional["ToolRegistry"] = None

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools: Dict[str, BaseTool] = {}
        return cls._instance

    @classmethod
    def set_instance(cls, instance: Optional["ToolRegistry"]) -> None:
        """注入自定义实例（App 初始化 / 测试 mock）。"""
        cls._instance = instance

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        """获取当前实例（优先返回注入的，否则创建默认单例）。"""
        return cls()

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
