import asyncio
import logging
import threading
from typing import Any, Callable, Dict, List, Optional
from concurrent.futures import Future

from .config import MCPConfig
from .types import MCPServerConfig, MCPServerInfo, MCPServerStatus, MCPTool, MCPResource
from .client import MCPClient, MCPClientError

logger = logging.getLogger(__name__)


class MCPManager:
    _instance: Optional["MCPManager"] = None

    @classmethod
    def set_instance(cls, instance: Optional["MCPManager"]) -> None:
        """注入自定义实例（App 初始化/测试 mock）。"""
        cls._instance = instance

    @classmethod
    def get_instance(cls) -> "MCPManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._config: MCPConfig = MCPConfig()
        self._clients: Dict[str, MCPClient] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._status_callbacks: List[Callable[[str, MCPServerStatus], None]] = []

    def add_status_callback(self, callback: Callable[[str, MCPServerStatus], None]):
        self._status_callbacks.append(callback)

    def remove_status_callback(self, callback: Callable[[str, MCPServerStatus], None]):
        if callback in self._status_callbacks:
            self._status_callbacks.remove(callback)

    def _notify_status(self, server_name: str, status: MCPServerStatus):
        for callback in self._status_callbacks:
            try:
                callback(server_name, status)
            except Exception:
                pass

    def _ensure_event_loop(self):
        if self._loop is None or not self._loop.is_running():
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
            self._thread.start()

    def _run_event_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_async(self, coro) -> Future:
        self._ensure_event_loop()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future

    def shutdown(self):
        """关闭事件循环和线程（App.stop() 时调用）。"""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                logger.warning("MCP event loop thread did not stop in time")
        self._loop = None
        self._thread = None

    def load_config(self, config: MCPConfig):
        self._config = config

    def get_config(self) -> MCPConfig:
        return self._config

    def add_server(self, server_config: MCPServerConfig):
        self._config.add_server(server_config)

    def remove_server(self, name: str) -> bool:
        if name in self._clients:
            self.disconnect_server(name)
        return self._config.remove_server(name)

    def connect_server(self, name: str) -> Future:
        """连接单个服务器 — 委托给 _connect_server_async。"""
        async def _connect():
            return await self._connect_server_async(name)
        return self._run_async(_connect())

    def disconnect_server(self, name: str) -> Future:
        async def _disconnect():
            if name in self._clients:
                client = self._clients[name]
                await client.disconnect()
                del self._clients[name]
            self._notify_status(name, MCPServerStatus.DISCONNECTED)
            return True

        return self._run_async(_disconnect())

    async def _connect_server_async(self, name: str) -> bool:
        server_config = self._config.get_server(name)
        if not server_config:
            logger.error(f"服务器配置不存在: {name}")
            return False

        if name in self._clients:
            client = self._clients[name]
            if client.is_connected():
                return True
            else:
                # 已有实例但未连接，先移除
                del self._clients[name]

        try:
            client = MCPClient(server_config)
            self._clients[name] = client

            self._notify_status(name, MCPServerStatus.CONNECTING)

            success = await client.connect()
            if success:
                self._notify_status(name, MCPServerStatus.CONNECTED)
                logger.info(f"服务器 {name} 连接成功")
                server_info = self.get_server_info(name)
                if server_info:
                    logger.info(f"  - 工具数量: {len(server_info.tools)}")
                    logger.info(f"  - 资源数量: {len(server_info.resources)}")
            else:
                self._notify_status(name, MCPServerStatus.ERROR)
                logger.error(f"服务器 {name} 连接失败")
                server_info = self.get_server_info(name)
                if server_info and server_info.error_message:
                    logger.error(f"  - 错误信息: {server_info.error_message}")
                # 失败时清理client
                if name in self._clients:
                    del self._clients[name]

            return success
        except Exception as e:
            logger.error(f"服务器 {name} 连接异常: {e}", exc_info=True)
            # 异常时清理client
            if name in self._clients:
                del self._clients[name]
            return False

    def connect_all(self) -> Future:
        async def _connect_all():
            results = {}
            enabled_servers = self._config.get_enabled_servers()
            logger.info(f"开始连接 {len(enabled_servers)} 个 MCP 服务器")

            tasks = []
            for server in enabled_servers:
                logger.info(
                    f"准备连接服务器: {server.name} (transport={server.transport})"
                )
                tasks.append(self._connect_server_async(server.name))

            try:
                connection_results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=180
                )
            except asyncio.TimeoutError:
                logger.error("MCP 连接超时")
                connection_results = [False] * len(tasks)

            for server, result in zip(enabled_servers, connection_results):
                if isinstance(result, Exception):
                    results[server.name] = False
                    logger.error(
                        f"服务器 {server.name} 连接异常: {result}", exc_info=True
                    )
                else:
                    results[server.name] = result

            logger.info(f"MCP 连接全部完成，结果: {results}")
            return results

        return self._run_async(_connect_all())

    async def _disconnect_server_async(self, name: str) -> bool:
        try:
            if name in self._clients:
                client = self._clients[name]
                await client.disconnect()
                del self._clients[name]
                logger.info(f"服务器 {name} 已断开连接")
                return True
            return False
        except Exception as e:
            logger.error(f"服务器 {name} 断开连接异常: {e}", exc_info=True)
            if name in self._clients:
                del self._clients[name]
            return False

    def disconnect_all(self) -> Future:
        async def _disconnect_all():
            names = list(self._clients.keys())
            logger.info(f"开始断开 {len(names)} 个 MCP 服务器连接: {names}")
            for name in names:
                await self._disconnect_server_async(name)
            logger.info(f"MCP 断开连接完成，剩余客户端: {list(self._clients.keys())}")
            return True

        return self._run_async(_disconnect_all())

    def get_server_info(self, name: str) -> Optional[MCPServerInfo]:
        if name in self._clients:
            return self._clients[name].info
        return None

    def get_all_server_infos(self) -> Dict[str, MCPServerInfo]:
        result = {}
        for name, client in self._clients.items():
            result[name] = client.info
        return result

    def get_all_tools(self) -> List[MCPTool]:
        tools = []
        for client in self._clients.values():
            if client.is_connected():
                tools.extend(client.get_tools())
        return tools

    def get_tools_for_openai(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self.get_all_tools()]

    def get_tools_for_anthropic(self) -> List[Dict[str, Any]]:
        return [tool.to_anthropic_tool() for tool in self.get_all_tools()]

    def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        server_name: Optional[str] = None,
    ) -> Future:
        target_client: Optional[MCPClient] = None

        if server_name:
            if server_name in self._clients:
                target_client = self._clients[server_name]
        else:
            for client in self._clients.values():
                if client.is_connected():
                    for tool in client.get_tools():
                        if tool.name == tool_name:
                            target_client = client
                            break
                if target_client:
                    break

        if not target_client:
            future = Future()
            future.set_exception(MCPClientError(f"未找到工具: {tool_name}"))
            return future

        async def _call():
            return await target_client.call_tool(tool_name, arguments)

        return self._run_async(_call())

    def get_all_resources(self) -> List[MCPResource]:
        resources = []
        for client in self._clients.values():
            if client.is_connected():
                resources.extend(client.get_resources())
        return resources

    def read_resource(self, uri: str, server_name: Optional[str] = None) -> Future:
        target_client: Optional[MCPClient] = None

        if server_name:
            if server_name in self._clients:
                target_client = self._clients[server_name]
        else:
            for client in self._clients.values():
                if client.is_connected():
                    for resource in client.get_resources():
                        if resource.uri == uri:
                            target_client = client
                            break
                if target_client:
                    break

        if not target_client:
            future = Future()
            future.set_exception(MCPClientError(f"未找到资源: {uri}"))
            return future

        async def _read():
            return await target_client.read_resource(uri)

        return self._run_async(_read())


def get_mcp_manager() -> MCPManager:
    """向后兼容的便捷函数 — 优先从 DI 实例获取。"""
    return MCPManager.get_instance()


# ------------------------------------------------------------------
# MCP Tool Adapter — wraps MCP tools as BaseTool for ToolRegistry
# ------------------------------------------------------------------

from typing import Callable as _Callable
from llm_chat.tools.base import BaseTool as _BaseTool


class MCPToolAdapter(_BaseTool):
    """将 MCPTool 包装为 BaseTool，使其可被 ToolRegistry 发现。

    子 agent 的 LLMClient (skip_skills_setup) 只从 ToolRegistry
    获取工具列表。通过此类将 MCP 工具注册到 ToolRegistry，
    子 agent 即可自动发现和使用 MCP 工具。
    """

    def __init__(
        self,
        tool_name: str,
        description: str,
        input_schema: Dict[str, Any],
        executor: _Callable[[str, Dict[str, Any]], Future],
    ):
        self._name = tool_name
        self._description = description or ""
        self._input_schema = input_schema or {}
        self._executor = executor  # (tool_name, args) -> Future[str]

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def get_parameters_schema(self) -> Dict[str, Any]:
        return self._input_schema

    def execute(self, **kwargs) -> str:
        future = self._executor(self._name, kwargs)
        return future.result(timeout=300)
