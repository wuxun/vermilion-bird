import time
import logging
from typing import List, Dict, Any, Optional
from llm_chat.client import LLMClient
from llm_chat.storage import Storage
from llm_chat.utils.token_counter import count_tokens
from llm_chat.context import ContextManager, ContextMessage
from llm_chat.utils.observability import observe

logger = logging.getLogger(__name__)


class Conversation:
    def __init__(
        self,
        client: LLMClient,
        conversation_id: Optional[str] = None,
        storage: Optional[Storage] = None,
        memory_config: Optional[Dict] = None,
        memory_manager=None,
        model_params: Optional[Dict[str, Any]] = None,
        context_config: Optional[Dict] = None,
    ):
        self.client = client
        self.conversation_id = conversation_id or f"conv_{int(time.time())}"
        self.storage = storage or Storage()
        self.memory_config = memory_config or {}
        self._model_params = model_params or {}
        self.context_config = context_config or {}
        self._ensure_conversation()
        self._memory_manager = memory_manager
        self._context_manager = None
        self._init_memory()
        self._init_context_manager()

    def set_model_param(self, key: str, value: Any):
        """设置单个模型参数"""
        self._model_params[key] = value
        logger.info(f"设置模型参数: {key}={value}")

    def set_model_params(self, params: Dict[str, Any]):
        """批量设置模型参数"""
        self._model_params.update(params)
        logger.info(f"批量设置模型参数: {params}")

    def get_model_params(self) -> Dict[str, Any]:
        """获取当前模型参数"""
        return self._model_params.copy()

    def clear_model_params(self):
        """清空模型参数"""
        self._model_params = {}
        logger.info("已清空模型参数")

    def remove_model_param(self, key: str):
        """移除指定模型参数"""
        if key in self._model_params:
            del self._model_params[key]
            logger.info(f"移除模型参数: {key}")

    def _init_memory(self):
        """初始化记忆管理器（优先使用外部注入的共享实例）"""
        if self._memory_manager is not None:
            # 使用外部注入的共享 MemoryManager，无需创建新实例
            logger.debug("使用共享记忆管理器")
            return

        if self.memory_config.get("enabled", False):
            try:
                from llm_chat.memory import MemoryManager, MemoryStorage
                from llm_chat.memory.summarizer import LLMSummarizer

                memory_storage = MemoryStorage(
                    self.memory_config.get("storage_dir", "~/.vermilion-bird/memory")
                )
                summarizer = LLMSummarizer(self.client)
                self._memory_manager = MemoryManager(
                    storage=memory_storage,
                    db_storage=self.storage,
                    llm_client=self.client,
                    summarizer=summarizer,
                    config=self.memory_config,
                )
                logger.info("记忆系统已初始化（独立实例）")
            except Exception as e:
                logger.warning(f"记忆系统初始化失败: {e}")
                self._memory_manager = None

    def _init_context_manager(self):
        """初始化上下文管理器"""
        try:
            from llm_chat.context import ContextManager

            self._context_manager = ContextManager.from_config(
                config={
                    "context": self.context_config,
                    "llm": self.client.config.llm.model_dump(),
                },
                llm_client=self.client,
                storage=self.storage,
            )
            logger.info("上下文管理系统已初始化")
        except Exception as e:
            logger.warning(f"上下文管理系统初始化失败: {e}")
            self._context_manager = None

    def _ensure_conversation(self):
        existing = self.storage.get_conversation(self.conversation_id)
        if not existing:
            self.storage.create_conversation(self.conversation_id)

    def add_message(self, role: str, content: str, **kwargs):
        metadata = kwargs if kwargs else None
        self.storage.add_message(self.conversation_id, role, content, metadata)

        if role == "user" and not self._get_title():
            title = content[:30]
            if len(content) > 30:
                title += "..."
            self.storage.update_conversation(self.conversation_id, title=title)

    def add_user_message(self, content: str):
        self.add_message("user", content)

    def add_assistant_message(
        self, content: str, tool_calls: Optional[List[Dict]] = None
    ):
        metadata = {"tool_calls": tool_calls} if tool_calls else None
        self.storage.add_message(self.conversation_id, "assistant", content, metadata)

    def add_tool_message(
        self, tool_call_id: str, content: str, tool_name: str = "unknown"
    ):
        metadata = {
            "tool_call_id": tool_call_id,
            "is_tool_result": True,
            "tool_result_id": tool_call_id,
            "tool_name": tool_name,
        }
        self.storage.add_message(self.conversation_id, "tool", content, metadata)

    @observe("conversation.send_message")
    def send_message(self, message: str) -> str:
        """发送消息并获取回复。

        管道: 持久化用户消息 → 构建压缩上下文 → LLM 调用 → 存储回复 → 记忆提取
        """
        # 阶段 1: 持久化用户消息
        self.add_user_message(message)

        # 阶段 2-3: 记忆注入 + 上下文压缩 + LLM 调用
        response = self._call_llm_with_compression(message)

        # 阶段 4: 持久化助手回复
        self.add_assistant_message(response)

        # 阶段 5: 异步记忆提取
        self._extract_memory_async(message, response)

        return response

    # ------------------------------------------------------------------
    # Pipeline 阶段 (可独立测试和替换)
    # ------------------------------------------------------------------

    def _call_llm_with_compression(self, message: str) -> str:
        """阶段 2-3: 记忆注入 → 上下文压缩 → LLM 调用。

        有 ContextManager 时走压缩路径，否则直接调用。
        """
        memory_context = self._get_memory_context()
        all_messages = self.storage.get_messages(self.conversation_id)
        history = all_messages[:-1]  # 排除刚添加的当前用户消息

        if self._context_manager:
            system_prompt, processed_history, processed_message = (
                self._compress_context(memory_context, history, message)
            )
            return self.client.chat(
                processed_message,
                processed_history,
                system_context=system_prompt,
                **self._model_params,
            )

        # 降级：无 ContextManager 时直接调用
        return self.client.chat(
            message, history, system_context=memory_context, **self._model_params
        )

    def _compress_context(
        self,
        memory_context: Optional[str],
        history: List[Dict[str, Any]],
        message: str,
    ):
        """阶段 2b: 将记忆上下文和历史消息送入 ContextManager 压缩。

        Returns:
            (system_prompt, processed_history, processed_message)
        """
        from llm_chat.context import ContextMessage

        context_messages = []
        if memory_context:
            context_messages.append(
                ContextMessage(role="system", content=memory_context)
            )

        for msg in history:
            context_messages.append(
                ContextMessage(
                    role=msg["role"],
                    content=msg["content"],
                    metadata=msg.get("metadata"),
                    timestamp=msg.get("timestamp"),
                )
            )

        context_messages.append(ContextMessage(role="user", content=message))

        result = self._context_manager.process_context(
            conversation_id=self.conversation_id, messages=context_messages
        )

        total_sent_tokens = sum(count_tokens(m.content) for m in result.messages)
        logger.info(
            f"[CONVERSATION] 最终发送token={total_sent_tokens}, "
            f"压缩级别={result.level.name}"
        )

        # 分离系统提示和对话历史
        system_prompt = None
        processed_history = []

        for msg in result.messages:
            if msg.role == "system" and system_prompt is None:
                system_prompt = msg.content
            else:
                processed_history.append({"role": msg.role, "content": msg.content})

        # 提取当前用户消息（最后一条 user 消息）
        if processed_history and processed_history[-1]["role"] == "user":
            processed_message = processed_history[-1]["content"]
            processed_history = processed_history[:-1]
        else:
            processed_message = message

        return system_prompt, processed_history, processed_message

    def _get_memory_context(self) -> Optional[str]:
        """获取记忆上下文"""
        if self._memory_manager:
            return self._memory_manager.build_system_prompt()
        return None

    def _extract_memory_async(self, user_message: str, assistant_response: str):
        """异步提取记忆"""
        if self._memory_manager:
            try:
                messages = [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": assistant_response},
                ]
                self._memory_manager.schedule_extraction(messages)
                self._memory_manager.process_pending_extractions()
            except Exception as e:
                logger.warning(f"记忆提取失败: {e}")

    def end_session(self):
        """结束会话，归档记忆"""
        if self._memory_manager:
            try:
                self._memory_manager.archive_session(self.conversation_id)
                logger.info(f"会话已归档: {self.conversation_id}")
            except Exception as e:
                logger.warning(f"会话归档失败: {e}")

    def _get_simple_history(self) -> List[Dict[str, str]]:
        messages = self.storage.get_messages(self.conversation_id)
        result = []
        for msg in messages[:-1]:
            if msg.get("role") in ("user", "assistant") and msg.get("content"):
                result.append({"role": msg["role"], "content": msg["content"]})
        return result

    def get_history(self) -> List[Dict[str, Any]]:
        return self.storage.get_messages(self.conversation_id)

    def clear_history(self):
        self.storage.clear_messages(self.conversation_id)

    def _get_title(self) -> Optional[str]:
        conv = self.storage.get_conversation(self.conversation_id)
        return conv.get("title") if conv else None

    def set_title(self, title: str):
        self.storage.update_conversation(self.conversation_id, title=title)

    def get_memory_stats(self) -> Optional[Dict]:
        """获取记忆统计信息"""
        if self._memory_manager:
            return self._memory_manager.get_memory_stats()
        return None

    def get_context_stats(self) -> Optional[Dict]:
        """获取上下文管理统计信息"""
        if self._context_manager:
            return {
                "cache_stats": self._context_manager.get_cache_stats(),
                "max_context_tokens": self._context_manager.max_context_tokens,
                "reserve_tokens": self._context_manager.reserve_tokens,
            }
        return None

    def create_subagent_context(
        self, task_description: str, **kwargs
    ) -> List[Dict[str, Any]]:
        """
        创建子代理上下文
        :param task_description: 子代理任务描述
        :param kwargs: 其他参数（include_recent_rounds, max_tokens等）
        :return: 子代理上下文消息列表
        """
        if not self._context_manager:
            # 上下文管理器未初始化时返回基础上下文
            return [
                {"role": "system", "content": f"请完成以下任务：{task_description}"}
            ]

        context_messages = self._context_manager.get_context_for_subagent(
            conversation_id=self.conversation_id,
            task_description=task_description,
            **kwargs,
        )

        return [msg.to_dict() for msg in context_messages]


class ConversationManager:
    def __init__(
        self,
        client: LLMClient,
        storage: Optional[Storage] = None,
        memory_config: Optional[Dict] = None,
        default_model_params: Optional[Dict[str, Any]] = None,
    ):
        self.client = client
        self.storage = storage or Storage()
        self.memory_config = memory_config or {}
        self.default_model_params = default_model_params or {}
        self._conversations: Dict[str, Conversation] = {}
        self._memory_manager = None
        self._init_memory()

    def _init_memory(self):
        """初始化共享记忆管理器（单例）"""
        if self.memory_config.get("enabled", False):
            try:
                from llm_chat.memory import MemoryManager, MemoryStorage
                from llm_chat.memory.summarizer import LLMSummarizer

                memory_storage = MemoryStorage(
                    self.memory_config.get("storage_dir", "~/.vermilion-bird/memory")
                )
                summarizer = LLMSummarizer(self.client)
                self._memory_manager = MemoryManager(
                    storage=memory_storage,
                    db_storage=self.storage,
                    llm_client=self.client,
                    summarizer=summarizer,
                    config=self.memory_config,
                )
                logger.info("共享记忆系统已初始化")
            except Exception as e:
                logger.warning(f"共享记忆系统初始化失败: {e}")
                self._memory_manager = None

    def get_conversation(self, conversation_id: str) -> Conversation:
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = Conversation(
                self.client,
                conversation_id,
                self.storage,
                self.memory_config,
                memory_manager=self._memory_manager,
                model_params=self.default_model_params,
            )
        return self._conversations[conversation_id]

    def create_conversation(self, title: Optional[str] = None) -> Conversation:
        conversation_id = f"conv_{int(time.time())}"
        self.storage.create_conversation(conversation_id, title)
        conv = Conversation(
            self.client,
            conversation_id,
            self.storage,
            self.memory_config,
            memory_manager=self._memory_manager,
            model_params=self.default_model_params,
        )
        self._conversations[conversation_id] = conv
        return conv

    def set_default_model_params(self, params: Dict[str, Any]):
        """设置默认模型参数"""
        self.default_model_params = params

    def get_default_model_params(self) -> Dict[str, Any]:
        """获取默认模型参数"""
        return self.default_model_params.copy()

    def list_conversations(
        self, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        return self.storage.list_conversations(limit, offset)

    def delete_conversation(self, conversation_id: str) -> bool:
        if conversation_id in self._conversations:
            conv = self._conversations[conversation_id]
            conv.end_session()
            del self._conversations[conversation_id]
        return self.storage.delete_conversation(conversation_id)

    def search_messages(
        self, query: str, conversation_id: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        return self.storage.search_messages(query, conversation_id, limit)

    def migrate_from_json(self, json_dir: str = ".vb/history") -> int:
        return self.storage.migrate_from_json(json_dir)

    def evolve_memories(self):
        """进化长期记忆（使用共享 MemoryManager）"""
        if self._memory_manager:
            self._memory_manager.evolve_understanding()
