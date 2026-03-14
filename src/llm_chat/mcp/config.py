from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from .types import MCPServerConfig, MCPServerInfo, MCPServerStatus


class MCPConfig(BaseModel):
    servers: List[MCPServerConfig] = Field(default_factory=list, description="MCP 服务器配置列表")
    
    def get_server(self, name: str) -> Optional[MCPServerConfig]:
        for server in self.servers:
            if server.name == name:
                return server
        return None
    
    def add_server(self, server: MCPServerConfig) -> None:
        existing = self.get_server(server.name)
        if existing:
            self.servers.remove(existing)
        self.servers.append(server)
    
    def remove_server(self, name: str) -> bool:
        server = self.get_server(name)
        if server:
            self.servers.remove(server)
            return True
        return False
    
    def get_enabled_servers(self) -> List[MCPServerConfig]:
        return [s for s in self.servers if s.enabled]
    
    @classmethod
    def from_dict(cls, data: Dict) -> "MCPConfig":
        servers = []
        for server_data in data.get("servers", []):
            servers.append(MCPServerConfig(**server_data))
        return cls(servers=servers)
    
    def to_dict(self) -> Dict:
        return {
            "servers": [s.model_dump() for s in self.servers]
        }
