import logging
from pathlib import Path
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
        self.current_frontend: Optional[BaseFrontend] = None
        self._mcp_manager: Optional[MCPManager] = None
        self._tools_enabled = False
        self._current_conversation_id: str = "default"
        self.scheduler: Optional["SchedulerService"] = None

        # 组件分层初始化（保持依赖顺序）
        self.tool_registry = self._init_tool_registry()
        self.storage = self._init_storage()
        self.client = self._init_client()
        self.conversation_manager = self._init_conversation_manager()
        self.chat_core = self._init_chat_core()
        self._init_prompt_skills()
        self.service_manager = self._init_service_manager()
        self._health_checker = self._init_health_checker()
        self._init_scheduler()

        logger.info("App initialization complete")

    # ------------------------------------------------------------------
    # Factory methods (按依赖顺序)
    # ------------------------------------------------------------------

    def _init_tool_registry(self):
        from llm_chat.tools.registry import ToolRegistry
        tr = ToolRegistry()
        ToolRegistry.set_instance(tr)
        return tr

    def _init_storage(self):
        s = Storage()
        Storage.set_instance(s)
        return s

    def _init_client(self):
        return LLMClient(self.config, tool_registry=self.tool_registry)

    def _init_conversation_manager(self):
        memory_config = self._build_memory_config()
        default_model_params = self.config.llm.get_model_params()
        memory_manager = self._init_memory_manager()
        return ConversationManager(
            self.client,
            self.storage,
            memory_config=memory_config,
            default_model_params=default_model_params,
            memory_manager=memory_manager,
        )

    def _init_memory_manager(self):
        """创建共享 MemoryManager (可选，取决于 config.memory.enabled)。"""
        memory_config = self._build_memory_config()
        if not memory_config.get("enabled"):
            return None
        try:
            from llm_chat.memory import MemoryManager, MemoryStorage
            from llm_chat.memory.summarizer import LLMSummarizer
            memory_storage = MemoryStorage(
                memory_config.get("storage_dir", "~/.vermilion-bird/memory")
            )
            summarizer = LLMSummarizer(self.client)
            return MemoryManager(
                storage=memory_storage,
                db_storage=self.storage,
                llm_client=self.client,
                summarizer=summarizer,
                config=memory_config,
            )
        except Exception as e:
            logger.warning(f"共享记忆系统初始化失败: {e}")
            return None

    def _init_chat_core(self):
        chat_core = ChatCore(
            client=self.client,
            conversation_manager=self.conversation_manager,
            config=self.config,
        )
        logger.info("ChatCore initialized")
        return chat_core

    def _init_service_manager(self):
        return ServiceManager()

    def _init_health_checker(self):
        hc = get_checker()
        hc.register_checker("database", create_database_checker(self.storage))
        hc.register_checker("services", create_service_manager_checker(self.service_manager))
        logger.info("HealthChecker initialized with database + services checks")
        return hc

    def _init_scheduler(self):
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

    def _init_prompt_skills(self):
        """发现并初始化 Prompt Skills (Agent Skills 标准)。

        搜索目录:
        1. ~/.vermilion-bird/skills/
        2. .agents/skills/ (当前目录)
        3. config.yaml 中 prompt_skill_dirs 配置
        """
        from llm_chat.skills.prompt_skill import PromptSkill

        skill_manager = self.get_skill_manager()

        # 默认目录
        home = Path.home()
        default_dirs = [
            str(home / ".vermilion-bird" / "skills"),
            str(Path.cwd() / ".agents" / "skills"),
        ]

        # 配置文件额外目录
        extra = self.config.prompt_skill_dirs if hasattr(self.config, 'prompt_skill_dirs') else []

        for d in default_dirs + extra:
            skill_manager.add_prompt_skill_dir(d)

        discovered = skill_manager.discover_prompt_skills()
        if discovered:
            context = skill_manager.get_prompt_skills_for_context()
            self.chat_core.set_prompt_skills_context(context)
            logger.info(
                f"Prompt skills loaded: {len(discovered)} found, "
                f"context={len(context)} chars"
            )
        else:
            logger.debug("No prompt skills found")

    def get_skill_manager(self) -> SkillManager:
        return self.client.get_skill_manager()

    def reload_skills_from_config(self):
        """Reload config from file and re-initialize all skills.

        Called after the skills dialog saves config.yaml changes.
        Unloads all skills, re-reads config, and loads skills per new config.
        Preserves MCP tools by re-enabling tools after skill reload.
        """
        new_config = Config.from_yaml()
        self.config = new_config
        self.client.config = new_config
        self.client._setup_skills()
        # Re-enable MCP tools (wiped by _setup_skills → tool_registry.clear())
        if self._tools_enabled:
            self._tools_enabled = False
            self.enable_tools()
        # Re-discover prompt skills (may have changed in config)
        self._init_prompt_skills()
        logger.info("Skills reloaded from config.yaml")

    def get_scheduler(self) -> Optional["SchedulerService"]:
        return self.scheduler

    def get_health(self) -> Dict[str, Any]:
        """获取系统健康状态"""
        return self._health_checker.get_summary()

    def _get_mcp_manager(self) -> MCPManager:
        if self._mcp_manager is None:
            self._mcp_manager = MCPManager()
            MCPManager.set_instance(self._mcp_manager)
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
                # 注册 MCP 工具到 ToolRegistry → 子 agent 自动可见
                from llm_chat.mcp.manager import MCPToolAdapter
                for mcp_tool in manager.get_all_tools():
                    adapter = MCPToolAdapter(
                        tool_name=mcp_tool.name,
                        description=mcp_tool.description or "",
                        input_schema=mcp_tool.input_schema or {},
                        executor=lambda name, args, mgr=manager: mgr.call_tool(name, args),
                    )
                    self.tool_registry.register(adapter)
                logger.info(
                    f"MCP 工具已注册到 ToolRegistry: "
                    f"{[t.name for t in manager.get_all_tools()]}"
                )

        except Exception as e:
            logger.error(f"MCP 连接失败: {e}", exc_info=True)

        self._tools_enabled = True

    def disable_tools(self):
        if not self._tools_enabled:
            return

        # 先从 ToolRegistry 移除 MCP 工具
        if self._mcp_manager:
            for mcp_tool in self._mcp_manager.get_all_tools():
                self.tool_registry.unregister(mcp_tool.name)

            future = self._mcp_manager.disconnect_all()
            try:
                future.result(timeout=10)
                logger.info("工具已禁用，MCP 连接已断开")
            except Exception as e:
                logger.warning(f"断开 MCP 连接时出错: {e}")

        self._tools_enabled = False

    def get_available_tools(self) -> List[Dict[str, Any]]:
        tools = []

        builtin_tools = self.client.get_builtin_tools()
        # MCP 工具已通过 MCPToolAdapter 注册到 ToolRegistry,
        # get_builtin_tools() 已包含 MCP 工具，无需重复添加
        tools.extend(builtin_tools)

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
        if self.current_frontend.is_current_conversation_empty():
            convs = self.conversation_manager.list_conversations()
            if convs:
                return

        conv = self.conversation_manager.create_conversation()
        self._current_conversation_id = conv.conversation_id
        self.current_frontend.set_current_conversation(conv.conversation_id, [])
        self.current_frontend.request_conversation_list_refresh()

    def _on_delete_conversation(self, conversation_id: str):
        if conversation_id == self._current_conversation_id:
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
        # 关闭 MCP 事件循环
        if self._mcp_manager:
            self._mcp_manager.shutdown()
        if self.current_frontend:
            self.current_frontend.stop()
