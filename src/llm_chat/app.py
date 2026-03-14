from typing import Optional, Dict, Any, List
from llm_chat.client import LLMClient
from llm_chat.config import Config
from llm_chat.conversation import Conversation
from llm_chat.frontends.base import BaseFrontend, Message, ConversationContext, MessageType
from llm_chat.mcp import MCPManager, MCPServerStatus


class App:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.client = LLMClient(self.config)
        self.conversations: Dict[str, Conversation] = {}
        self.current_frontend: Optional[BaseFrontend] = None
        self._mcp_manager: Optional[MCPManager] = None
        self._tools_enabled = False
    
    def _get_mcp_manager(self) -> MCPManager:
        if self._mcp_manager is None:
            self._mcp_manager = MCPManager()
            self._mcp_manager.load_config(self.config.mcp)
        return self._mcp_manager
    
    def _execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        manager = self._get_mcp_manager()
        try:
            future = manager.call_tool(tool_name, arguments)
            result = future.result(timeout=60)
            return str(result) if result else ""
        except Exception as e:
            return f"Error: {str(e)}"
    
    def enable_tools(self):
        if self._tools_enabled:
            return
        
        manager = self._get_mcp_manager()
        
        future = manager.connect_all()
        try:
            future.result(timeout=30)
        except Exception:
            pass
        
        self.client.set_tool_executor(self._execute_tool)
        self._tools_enabled = True
    
    def disable_tools(self):
        if not self._tools_enabled:
            return
        
        if self._mcp_manager:
            future = self._mcp_manager.disconnect_all()
            try:
                future.result(timeout=10)
            except Exception:
                pass
        
        self.client.set_tool_executor(None)
        self._tools_enabled = False
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
        if not self._tools_enabled:
            return []
        
        manager = self._get_mcp_manager()
        return manager.get_tools_for_openai()
    
    def get_conversation(self, conversation_id: str) -> Conversation:
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = Conversation(self.client, conversation_id)
        return self.conversations[conversation_id]
    
    def set_frontend(self, frontend: BaseFrontend):
        self.current_frontend = frontend
        
        def handle_message(message: Message, ctx: ConversationContext):
            conversation = self.get_conversation(ctx.conversation_id)
            try:
                if self.config.enable_tools and self._tools_enabled:
                    tools = self.get_available_tools()
                    if tools:
                        response = self.client.chat_with_tools(
                            message.content,
                            tools,
                            history=conversation.get_history()
                        )
                    else:
                        response = conversation.send_message(message.content)
                else:
                    response = conversation.send_message(message.content)
                
                response_msg = Message(
                    content=response,
                    role="assistant",
                    msg_type=MessageType.TEXT
                )
                frontend.display_message(response_msg)
            except Exception as e:
                frontend.display_error(str(e))
        
        def handle_clear(ctx: ConversationContext):
            conversation = self.get_conversation(ctx.conversation_id)
            conversation.clear_history()
            frontend.display_info("对话历史已清空")
        
        def handle_exit():
            self.stop()
        
        frontend.set_on_message(handle_message)
        frontend.set_on_clear(handle_clear)
        frontend.set_on_exit(handle_exit)
    
    def run(self, frontend: BaseFrontend):
        self.set_frontend(frontend)
        
        if self.config.enable_tools and self.config.mcp.servers:
            self.enable_tools()
        
        try:
            frontend.start()
        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            if self.current_frontend:
                self.current_frontend.display_error(str(e))
            raise
    
    def stop(self):
        self.disable_tools()
        if self.current_frontend:
            self.current_frontend.stop()
