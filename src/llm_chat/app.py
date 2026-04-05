import logging
from typing import Optional, Dict, Any, List, TYPE_CHECKING

logger = logging.getLogger(__name__)

from llm_chat.client import LLMClient
from llm_chat.config import Config
from llm_chat.conversation import Conversation, ConversationManager
from llm_chat.frontends.base import (
    BaseFrontend,
    Message,
    ConversationContext,
    MessageType,
)
from llm_chat.mcp import MCPManager, MCPServerStatus
from llm_chat.storage import Storage
from llm_chat.skills import SkillManager
from llm_chat.service_manager import ServiceManager

if TYPE_CHECKING:
    from llm_chat.scheduler.scheduler import SchedulerService


class App:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.client = LLMClient(self.config)
        self.storage = Storage()

        memory_config = self._build_memory_config()
        default_model_params = self.config.llm.get_model_params()

        self.conversation_manager = ConversationManager(
            self.client,
            self.storage,
            memory_config=memory_config,
            default_model_params=default_model_params,
        )
        self.current_frontend: Optional[BaseFrontend] = None
        self._mcp_manager: Optional[MCPManager] = None
        self._tools_enabled = False
        self._current_conversation_id: str = "default"

        # 初始化服务管理器
        self.service_manager = ServiceManager()
        self.scheduler: Optional["SchedulerService"] = None

        logger.info(f"Scheduler enabled config: {self.config.scheduler.enabled}")
        if self.config.scheduler.enabled:
            logger.info("Initializing SchedulerService...")
            from llm_chat.scheduler import SchedulerService

            try:
                self.scheduler = SchedulerService(
                    self.config.scheduler, self.storage, self
                )
                logger.info(f"SchedulerService created: {self.scheduler}")

                # 注册到服务管理器
                self.service_manager.register_service(self.scheduler)
                logger.info(f"SchedulerService registered with ServiceManager")

                skill_manager = self.get_skill_manager()
                skill_manager.reload_skill("scheduler", {"scheduler": self.scheduler})
                logger.info("Scheduler skill reloaded with scheduler instance")
            except Exception as e:
                logger.error(f"Failed to initialize scheduler: {e}")
                import traceback

                traceback.print_exc()
        else:
            logger.warning("Scheduler is disabled in config")

    def _build_memory_config(self) -> Dict[str, Any]:
        if not self.config.memory.enabled:
            return {"enabled": False}

        return {
            "enabled": True,
            "storage_dir": self.config.memory.storage_dir,
            "short_term": {"max_items": self.config.memory.short_term.max_items},
            "mid_term": {
                "max_days": self.config.memory.mid_term.max_days,
                "compress_after_days": self.config.memory.mid_term.compress_after_days,
            },
            "long_term": {
                "auto_evolve": self.config.memory.long_term.auto_evolve,
                "evolve_interval_days": self.config.memory.long_term.evolve_interval_days,
            },
            "exclude_patterns": self.config.memory.exclude_patterns,
        }

    def get_skill_manager(self) -> SkillManager:
        return self.client.get_skill_manager()

    def get_scheduler(self) -> Optional["SchedulerService"]:
        return self.scheduler

    def _get_mcp_manager(self) -> MCPManager:
        if self._mcp_manager is None:
            self._mcp_manager = MCPManager()
            new_servers = []
            for server in self.config.mcp.servers:
                server_dict = server.model_dump()
                if server_dict.get("http_proxy") is None:
                    server_dict["http_proxy"] = self.config.llm.http_proxy
                if server_dict.get("https_proxy") is None:
                    server_dict["https_proxy"] = self.config.llm.https_proxy
                new_server = type(server)(**server_dict)
                new_servers.append(new_server)

            self.config.mcp.servers = new_servers
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

        enabled_servers = self.config.mcp.get_enabled_servers()
        logger.info(
            f"准备连接 {len(enabled_servers)} 个 MCP 服务器: {[s.name for s in enabled_servers]}"
        )

        try:
            future = manager.connect_all()
            results = future.result(timeout=180)
            logger.info(f"MCP 连接结果: {results}")

            connected_tools = manager.get_tools_for_openai()
            logger.info(f"MCP 工具加载完成，共 {len(connected_tools)} 个工具")
            if connected_tools:
                logger.info(
                    f"MCP 工具列表: {[t['function']['name'] for t in connected_tools]}"
                )
        except Exception as e:
            logger.error(f"MCP 连接失败: {e}", exc_info=True)

        self.client.set_tool_executor(self._execute_tool)
        self._tools_enabled = True

    def disable_tools(self):
        if not self._tools_enabled:
            return

        if self._mcp_manager:
            future = self._mcp_manager.disconnect_all()
            try:
                future.result(timeout=10)
                logger.info("工具已禁用，MCP 连接已断开")
            except Exception as e:
                logger.warning(f"断开 MCP 连接时出错: {e}")

        self.client.set_tool_executor(None)
        self._tools_enabled = False

    def get_available_tools(self) -> List[Dict[str, Any]]:
        tools = []

        builtin_tools = self.client.get_builtin_tools()
        tools.extend(builtin_tools)

        if self._tools_enabled:
            manager = self._get_mcp_manager()
            mcp_tools = manager.get_tools_for_openai()
            tools.extend(mcp_tools)

        return tools

    def has_tools_available(self) -> bool:
        return self.client.has_builtin_tools() or self._tools_enabled

    def get_conversation(self, conversation_id: str) -> Conversation:
        return self.conversation_manager.get_conversation(conversation_id)

    def set_frontend(self, frontend: BaseFrontend):
        self.current_frontend = frontend

        # Set storage for frontends that support it (e.g., GUIFrontend)
        if hasattr(frontend, "set_storage"):
            frontend.set_storage(self.storage)

        # Set config for frontends that support it
        if hasattr(frontend, "set_config"):
            frontend.set_config(self.config)

        # Set app instance for frontends that support it (e.g., GUIFrontend for scheduler dialog)
        if hasattr(frontend, "set_app"):
            frontend.set_app(self)

        frontend.set_conversation_callbacks(
            on_new=self._on_new_conversation,
            on_delete=self._on_delete_conversation,
            on_rename=self._on_rename_conversation,
            on_switch=self._on_switch_conversation,
            on_list=self._on_list_conversations,
        )

        def handle_message(message: Message, ctx: ConversationContext):
            conversation = self.get_conversation(ctx.conversation_id)
            try:
                if self.config.enable_tools and self.has_tools_available():
                    tools = self.get_available_tools()
                    if tools:
                        response = self.client.chat_with_tools(
                            message.content, tools, history=conversation.get_history()
                        )
                    else:
                        response = conversation.send_message(message.content)
                else:
                    response = conversation.send_message(message.content)

                response_msg = Message(
                    content=response, role="assistant", msg_type=MessageType.TEXT
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

    def _on_new_conversation(self):
        if self.current_frontend.is_current_conversation_empty():
            return

        conv = self.conversation_manager.create_conversation()
        self._current_conversation_id = conv.conversation_id

        self.current_frontend.set_current_conversation(conv.conversation_id, [])
        self.current_frontend.request_conversation_list_refresh()

    def _on_delete_conversation(self, conversation_id: str):
        if conversation_id == self.current_frontend.conversation_id:
            conversations = self.conversation_manager.list_conversations()
            if conversations:
                next_conv = conversations[0]
                self._current_conversation_id = next_conv.get("id")
                messages = self.storage.get_messages(self._current_conversation_id)
                self.current_frontend.set_current_conversation(
                    self._current_conversation_id, messages
                )
            else:
                self._on_new_conversation()
                return

        self.conversation_manager.delete_conversation(conversation_id)
        self.current_frontend.request_conversation_list_refresh()

    def _on_rename_conversation(self, conversation_id: str):
        conv = self.storage.get_conversation(conversation_id)
        current_title = conv.get("title", "") if conv else ""

        new_title = self.current_frontend.request_rename_input(
            conversation_id, current_title
        )

        if new_title:
            self.storage.update_conversation(conversation_id, title=new_title)
            self.current_frontend.request_conversation_list_refresh()

    def _on_switch_conversation(self, conversation_id: str):
        self._current_conversation_id = conversation_id
        messages = self.storage.get_messages(conversation_id)
        self.current_frontend.set_current_conversation(conversation_id, messages)

    def _on_list_conversations(self):
        conversations = self.conversation_manager.list_conversations()
        self.current_frontend.update_conversation_list(conversations)

    def run(self, frontend: BaseFrontend):
        self.set_frontend(frontend)

        self.storage.migrate_from_json()

        conversations = self.conversation_manager.list_conversations()
        if conversations:
            self._current_conversation_id = conversations[0].get("id")
            messages = self.storage.get_messages(self._current_conversation_id)
            frontend.set_current_conversation(self._current_conversation_id, messages)

        if self.config.enable_tools:
            if self.config.mcp.servers:
                self.enable_tools()

        # 使用服务管理器启动所有服务
        self.service_manager.start_all()

        try:
            frontend.start()
        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            if self.current_frontend:
                self.current_frontend.display_error(str(e))
            raise

    def stop(self):
        # 使用服务管理器停止所有服务
        self.service_manager.stop_all()
        self.disable_tools()
        if self.current_frontend:
            self.current_frontend.stop()
