import asyncio
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

from .types import (
    MCPServerConfig, MCPServerInfo, MCPServerStatus,
    MCPTool, MCPResource, TransportType
)

logger = logging.getLogger(__name__)

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


class MCPClientError(Exception):
    pass


class MCPClient:
    def __init__(self, config: MCPServerConfig):
        if not MCP_AVAILABLE:
            raise MCPClientError(
                "mcp 包未安装。请运行: pip install mcp\n"
                "或使用 Poetry: poetry add mcp"
            )
        
        self.config = config
        self.info = MCPServerInfo(config=config)
        self._session: Optional[ClientSession] = None
        self._read = None
        self._write = None
        self._process: Optional[subprocess.Popen] = None
        self._connection_lock = asyncio.Lock()
        self._stopping = False
        self._connection_ready = asyncio.Event()

    async def connect(self) -> bool:
        self.info.status = MCPServerStatus.CONNECTING
        self.info.error_message = None
        self._stopping = False
        self._connection_ready.clear()
        
        try:
            if self.config.transport == TransportType.STDIO:
                return await self._connect_stdio()
            elif self.config.transport == TransportType.SSE:
                return await self._connect_sse()
            else:
                raise MCPClientError(f"不支持的传输类型: {self.config.transport}")
        except Exception as e:
            self.info.status = MCPServerStatus.ERROR
            self.info.error_message = str(e)
            return False

    async def _connect_stdio(self) -> bool:
        if not self.config.command:
            raise MCPClientError("stdio 模式需要指定 command")
        
        env = os.environ.copy()
        env.update(self.config.env)
        
        if hasattr(self.config, "http_proxy") and self.config.http_proxy:
            env["HTTP_PROXY"] = self.config.http_proxy
            logger.info(f"设置 HTTP_PROXY: {self.config.http_proxy}")
        if hasattr(self.config, "https_proxy") and self.config.https_proxy:
            env["HTTPS_PROXY"] = self.config.https_proxy
            logger.info(f"设置 HTTPS_PROXY: {self.config.https_proxy}")
        
        logger.info(
            f"启动 stdio MCP 服务器: command={self.config.command}, args={self.config.args}"
        )
        logger.info(f"环境变量配置: {[k for k in self.config.env.keys()]}")
        
        server_params = StdioServerParameters(
            command=self.config.command, args=self.config.args, env=env
        )
        
        try:
            async with self._connection_lock:
                async def maintain_connection():
                    try:
                        logger.info("正在建立 stdio 连接...")
                        async with stdio_client(server_params) as (read, write):
                            self._read = read
                            self._write = write
                            
                            async with ClientSession(read, write) as session:
                                self._session = session
                                
                                logger.info("正在初始化 MCP 会话...")
                                await session.initialize()
                                
                                logger.info("正在加载工具和资源...")
                                await self._load_capabilities()
                                
                                self.connection_ready()
                                logger.info(f"MCP 服务器 {self.config.name} 连接成功，保持运行...")
                                
                                while not self._stopping:
                                    await asyncio.sleep(1)
                    except Exception as e:
                        logger.error(f"连接维持异常: {e}", exc_info=True)
                        self._connection_ready.clear()
                
                task = asyncio.create_task(maintain_connection())
                
                try:
                    await asyncio.wait_for(self._connection_ready.wait(), timeout=180)
                    if self._stopping:
                        raise MCPClientError("连接被中断")
                    return True
                except asyncio.TimeoutError:
                    logger.error("连接超时")
                    self._stopping = True
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=5)
                    except:
                        pass
                    raise MCPClientError("连接超时")
                    
        except Exception as e:
            logger.error(f"MCP 服务器 {self.config.name} 连接失败: {e}", exc_info=True)
            raise MCPClientError(f"连接失败: {e}")

    def connection_ready(self):
        if not self._stopping and self.info.status != MCPServerStatus.CONNECTED:
            self.info.status = MCPServerStatus.CONNECTED
            self._connection_ready.set()

    async def _connect_sse(self) -> bool:
        if not self.config.url:
            raise MCPClientError("SSE 模式需要指定 url")
        
        try:
            async with self._connection_lock:
                async def maintain_sse():
                    try:
                        logger.info("正在建立 SSE 连接...")
                        async with sse_client(self.config.url) as (read, write):
                            self._read = read
                            self._write = write
                            
                            async with ClientSession(read, write) as session:
                                self._session = session
                                await session.initialize()
                                await self._load_capabilities()
                                
                                self.connection_ready()
                                
                                while not self._stopping:
                                    await asyncio.sleep(1)
                    except Exception as e:
                        logger.error(f"SSE 连接异常: {e}", exc_info=True)
                        self._connection_ready.clear()
                
                task = asyncio.create_task(maintain_sse())
                
                try:
                    await asyncio.wait_for(self._connection_ready.wait(), timeout=60)
                    if self._stopping:
                        raise MCPClientError("SSE 连接被中断")
                    return True
                except asyncio.TimeoutError:
                    self._stopping = True
                    task.cancel()
                    raise MCPClientError("SSE 连接超时")
                    
        except Exception as e:
            logger.error(f"SSE 连接失败: {e}", exc_info=True)
            raise MCPClientError(f"SSE 连接失败: {e}")

    async def _load_capabilities(self):
        if not self._session:
            return
        
        try:
            tools_result = await self._session.list_tools()
            self.info.tools = [
                MCPTool(
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.inputSchema,
                    server_name=self.config.name
                )
                for tool in tools_result.tools
            ]
        except Exception:
            self.info.tools = []
        
        try:
            resources_result = await self._session.list_resources()
            self.info.resources = [
                MCPResource(
                    uri=resource.uri,
                    name=resource.name,
                    description=resource.description,
                    mime_type=resource.mimeType,
                    server_name=self.config.name
                )
                for resource in resources_result.resources
            ]
        except Exception:
            self.info.resources = []
    
    async def disconnect(self):
        self._stopping = True
        self._connection_ready.clear()
        
        self._session = None
        self._read = None
        self._write = None
        
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
            self._process = None
        
        self.info.status = MCPServerStatus.DISCONNECTED
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        if not self._session:
            raise MCPClientError("未连接到 MCP 服务器")
        
        if self.info.status != MCPServerStatus.CONNECTED:
            raise MCPClientError(f"服务器状态异常: {self.info.status}")
        
        try:
            result = await self._session.call_tool(tool_name, arguments)
            
            if result.isError:
                error_msg = result.content[0].text if result.content else "未知错误"
                raise MCPClientError(f"工具调用失败: {error_msg}")
            
            if result.content:
                return result.content[0].text
            
            return None
        except Exception as e:
            raise MCPClientError(f"工具调用异常: {e}")
    
    async def read_resource(self, uri: str) -> Any:
        if not self._session:
            raise MCPClientError("未连接到 MCP 服务器")
        
        try:
            result = await self._session.read_resource(uri)
            return result
        except Exception as e:
            raise MCPClientError(f"资源读取失败: {e}")
    
    def get_tools(self) -> List[MCPTool]:
        return self.info.tools
    
    def get_resources(self) -> List[MCPResource]:
        return self.info.resources
    
    def is_connected(self) -> bool:
        return self.info.status == MCPServerStatus.CONNECTED
