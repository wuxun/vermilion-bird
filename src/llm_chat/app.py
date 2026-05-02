import logging
from typing import Optional, Dict, Any, List, TYPE_CHECKING

logger = logging.getLogger(__name__)

from llm_chat.client import LLMClient
from llm_chat.config import Config
from llm_chat.conversation import Conversation, ConversationManager
from llm_chat.chat_core import ChatCore
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
from llm_chat.health import get_checker, create_database_checker, create_service_manager_checker
from llm_chat.services import ConversationService

if TYPE_CHECKING:
    from llm_chat.scheduler.scheduler import SchedulerService


class App:
    """应用协调器

    职责：
    - 创建并装配所有组件 (client, storage, ChatCore, MCP, scheduler, health)
    - 管理 MCP 工具连接
    - 管理前端生命周期 (set_frontend / run / stop)
    - 会话 CRUD 回调

    NOT 负责：
    - 对话处理管道 → 委托给 ChatCore
    - 前端渲染 → 各前端自行处理
    """

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

        # 核心对话引擎 — 所有前端通过它处理 LLM 对话
        self.chat_core = ChatCore(
            client=self.client,
            conversation_manager=self.conversation_manager,
            config=self.config,
        )
        logger.info("ChatCore initialized")

        self._conv_service = ConversationService(
            self.conversation_manager,
            self.storage,
        )
        self.current_frontend: Optional[BaseFrontend] = None
        self._mcp_manager: Optional[MCPManager] = None
        self._tools_enabled = False
        self._current_conversation_id: str = "default"

        # 初始化服务管理器
        self.service_manager = ServiceManager()

        # 初始化健康检查
        self._health_checker = get_checker()
        self._health_checker.register_checker(
            "database", create_database_checker(self.storage)
        )
        self._health_checker.register_checker(
            "services", create_service_manager_checker(self.service_manager)
        )
        logger.info("HealthChecker initialized with database + services checks")

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
            "extraction_interval": self.config.memory.extraction_interval,
            "extraction_time_interval": self.config.memory.extraction_time_interval,
            "short_term_max_entries": self.config.memory.short_term_max_entries,
            "max_memory_tokens": self.config.memory.max_memory_tokens,
        }

    def get_skill_manager(self) -> SkillManager:
        return self.client.get_skill_manager()

    def reload_skills_from_config(self):
        """Reload config from file and re-initialize all skills.

        Called after the skills dialog saves config.yaml changes.
        Unloads all skills, re-reads config, and loads skills per new config.
        """
        new_config = Config.from_yaml()
        self.config = new_config
        self.client.config = new_config
        self.client._setup_skills()
        logger.info("Skills reloaded from config.yaml")

    def get_scheduler(self) -> Optional["SchedulerService"]:
        return self.scheduler

    def get_health(self) -> Dict[str, Any]:
        """获取系统健康状态"""
        return self._health_checker.get_summary()

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

    # ------------------------------------------------------------------
    # ChatCore 便捷访问 (供前端直接使用)
    # ------------------------------------------------------------------

    def get_chat_core(self) -> ChatCore:
        """获取核心对话引擎。GUI/飞书等前端通过它进行 LLM 对话处理。"""
        return self.chat_core

    # ------------------------------------------------------------------
    # MCP 工具管理 (App 负责 MCP 连接; ChatCore 共享同一个 client)
    # ------------------------------------------------------------------

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

        # 设置 MCP 工具执行器到 client（ChatCore 共享同一个 client 实例）
        self.client.set_tool_executor(self._execute_tool)
        self.chat_core.set_tool_executor(self._execute_tool)
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
        self.chat_core.set_tool_executor(None)
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

        # 注入依赖到前端
        if hasattr(frontend, "set_storage"):
            frontend.set_storage(self.storage)
        if hasattr(frontend, "set_config"):
            frontend.set_config(self.config)
        if hasattr(frontend, "set_app"):
            frontend.set_app(self)
        if hasattr(frontend, "set_chat_core"):
            frontend.set_chat_core(self.chat_core)

        frontend.set_conversation_callbacks(
            on_new=self._on_new_conversation,
            on_delete=self._on_delete_conversation,
            on_rename=self._on_rename_conversation,
            on_switch=self._on_switch_conversation,
            on_list=self._on_list_conversations,
        )

        # 统一的消息处理回调 — 委托给 ChatCore（CLI/简单前端使用此路径）
        def handle_message(message: Message, ctx: ConversationContext):
            try:
                response = self.chat_core.send_message(
                    conversation_id=ctx.conversation_id,
                    message=message.content,
                )
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
        # 如果当前有未保存内容的对话，不创建新对话
        if self.current_frontend.is_current_conversation_empty():
            convs = self.conversation_manager.list_conversations()
            if convs:
                # 已有对话且当前为空，不需要新建
                return

        result = self._conv_service.create()
        self._current_conversation_id = result["id"]
        self.current_frontend.set_current_conversation(result["id"], [])
        self.current_frontend.request_conversation_list_refresh()

    def _on_delete_conversation(self, conversation_id: str):
        if conversation_id == self._conv_service.current_conversation_id:
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

        self._conv_service.delete(conversation_id)
        self.current_frontend.request_conversation_list_refresh()

    def _on_rename_conversation(self, conversation_id: str):
        conv = self.storage.get_conversation(conversation_id)
        current_title = conv.get("title", "") if conv else ""

        new_title = self.current_frontend.request_rename_input(
            conversation_id, current_title
        )

        if new_title:
            self._conv_service.rename(conversation_id, new_title)
            self.current_frontend.request_conversation_list_refresh()

    def _on_switch_conversation(self, conversation_id: str):
        messages = self._conv_service.switch(conversation_id)
        self._current_conversation_id = conversation_id
        self.current_frontend.set_current_conversation(conversation_id, messages)

    def _on_list_conversations(self):
        conversations = self._conv_service.list()
        self.current_frontend.update_conversation_list(conversations)

    def run(self, frontend: BaseFrontend):
        self.set_frontend(frontend)

        self.storage.migrate_from_json()

        conversations = self.conversation_manager.list_conversations()
        if conversations:
            self._current_conversation_id = conversations[0].get("id")
            messages = self.storage.get_messages(self._current_conversation_id)
            frontend.set_current_conversation(self._current_conversation_id, messages)
        else:
            # 无对话时创建默认对话
            self._on_new_conversation()

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
