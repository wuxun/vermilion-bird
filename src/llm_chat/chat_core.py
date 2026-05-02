"""
ChatCore - 核心对话引擎

封装完整的 LLM 对话处理管道：
  记忆注入 → 上下文压缩 → LLM 调用 → 工具调用循环 → 响应持久化 → 记忆提取

所有前端（CLI / GUI / 飞书）统一通过此类进行对话处理，
不再各自重复实现 LLM 调用逻辑。
"""

import logging
from typing import List, Dict, Any, Optional, Callable, Generator

from llm_chat.config import Config
from llm_chat.client import LLMClient
from llm_chat.conversation import ConversationManager
from llm_chat.utils.token_counter import count_tokens
from llm_chat.utils.observability import observe

logger = logging.getLogger(__name__)

# 流式回调类型
StreamCallback = Callable[[str], None]  # 收到文本 chunk
ToolCallStartCallback = Callable[[str, str], None]  # 工具调用开始 (name, args_json)
ToolCallEndCallback = Callable[[str, str, str], None]  # 工具调用结束 (name, args, result_preview)


class ChatCore:
    """核心对话引擎

    职责边界：
    - 管理完整的对话处理管道
    - 协调记忆、上下文、LLM 调用、工具执行
    - 提供统一的同步 & 流式接口

    NOT 负责：
    - 前端渲染（由 GUI/CLI/飞书各自处理）
    - 会话列表管理（由 ConversationManager 处理）
    - MCP 连接管理（由 App 处理，通过 client.set_tool_executor 注入）
    """

    def __init__(
        self,
        client: LLMClient,
        conversation_manager: ConversationManager,
        config: Config,
    ):
        self.client = client
        self.conversation_manager = conversation_manager
        self.config = config

        # 从 App 注入（见 app.py）
        self._tool_executor_override: Optional[Callable[[str, Dict[str, Any]], str]] = (
            None
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @observe("chat_core.send_message")
    def send_message(
        self,
        conversation_id: str,
        message: str,
        **model_params,
    ) -> str:
        """同步发送消息，返回完整回复文本。

        适用场景：CLI 非流式模式、飞书消息回复、定时任务等。

        Args:
            conversation_id: 会话 ID
            message: 用户消息
            **model_params: 覆盖默认模型参数 (temperature, max_tokens 等)

        Returns:
            AI 回复的完整文本
        """
        conv = self.conversation_manager.get_conversation(conversation_id)

        # 1. 持久化用户消息
        conv.add_user_message(message)

        # 2. 构建系统上下文（记忆注入）
        system_context = self._build_system_context(conv)

        # 3. 获取对话历史（不含刚添加的用户消息）
        history = conv.get_history()
        history = history[:-1] if history else []

        # 4. 上下文压缩（如果有 ContextManager）
        processed_history, processed_message = self._compress_context(
            conv, history, message, system_context
        )

        # 5. 合并模型参数
        params = {**conv.get_model_params(), **model_params}

        # 6. 调用 LLM（带工具或无工具）
        response = self._call_llm(
            processed_message, processed_history, system_context, params
        )

        # 7. 持久化助手回复
        conv.add_assistant_message(response)

        # 8. 异步记忆提取
        self._extract_memory_async(conv, message, response)

        # 9. 记录 token 消耗
        self._record_tokens(
            message=processed_message,
            history=processed_history,
            system_context=system_context,
            response=response,
        )

        return response

    @observe("chat_core.send_message_stream")
    def send_message_stream(
        self,
        conversation_id: str,
        message: str,
        on_chunk: Optional[StreamCallback] = None,
        on_tool_start: Optional[ToolCallStartCallback] = None,
        on_tool_end: Optional[ToolCallEndCallback] = None,
        on_context_update: Optional[Callable[[int, int], None]] = None,
        **model_params,
    ) -> str:
        """流式发送消息，通过回调逐步返回内容。

        适用场景：GUI 实时显示、CLI 流式输出。

        Args:
            conversation_id: 会话 ID
            message: 用户消息
            on_chunk: 收到文本 chunk 时的回调
            on_tool_start: 工具调用开始回调 (tool_name, args_json)
            on_tool_end: 工具调用结束回调 (tool_name, args_json, result_preview)
            on_context_update: 上下文更新回调 (used_tokens, limit)
            **model_params: 覆盖默认模型参数

        Returns:
            AI 回复的完整文本（在所有 chunk 发送完毕后）
        """
        conv = self.conversation_manager.get_conversation(conversation_id)

        # 1. 持久化用户消息
        conv.add_user_message(message)

        # 2. 构建系统上下文（记忆注入）
        system_context = self._build_system_context(conv)

        # 3. 获取对话历史
        history = conv.get_history()
        history = history[:-1] if history else []

        # 4. 上下文压缩
        processed_history, processed_message = self._compress_context(
            conv, history, message, system_context
        )

        # 5. 合并模型参数
        params = {**conv.get_model_params(), **model_params}

        # 6. 检查是否需要工具调用
        has_tools = self.client.has_builtin_tools() or self._tool_executor_override is not None

        full_text = ""

        if has_tools and self.config.enable_tools:
            # 获取可用工具
            tools = self.client.get_builtin_tools()
            if not tools:
                tools = []

            # 确保 tool_executor 已设置
            if self._tool_executor_override:
                self.client.set_tool_executor(self._tool_executor_override)

            logger.info(f"[ChatCore] 流式工具调用: tools={[t.get('function', {}).get('name', '?') for t in tools]}")

            for chunk in self.client.chat_stream_with_tools(
                processed_message,
                tools,
                history=processed_history,
                system_context=system_context,
                **params,
            ):
                if isinstance(chunk, tuple):
                    kind = chunk[0]
                    if kind == "tool_call_start" and on_tool_start:
                        on_tool_start(chunk[1], chunk[2])
                    elif kind == "tool_call_end" and on_tool_end:
                        on_tool_end(chunk[1], chunk[2], chunk[3])
                    elif kind == "context_update" and on_context_update:
                        on_context_update(chunk[1], chunk[2])
                elif isinstance(chunk, str):
                    full_text += chunk
                    if on_chunk:
                        on_chunk(chunk)
        else:
            # 无工具流式聊天
            logger.info("[ChatCore] 流式聊天 (无工具)")
            for chunk in self.client.chat_stream(
                processed_message,
                history=processed_history,
                system_context=system_context,
                **params,
            ):
                full_text += chunk
                if on_chunk:
                    on_chunk(chunk)

        # 7. 持久化助手回复
        conv.add_assistant_message(full_text)

        # 8. 异步记忆提取
        self._extract_memory_async(conv, message, full_text)

        # 9. 记录 token 消耗
        self._record_tokens(
            message=processed_message,
            history=processed_history,
            system_context=system_context,
            response=full_text,
        )

        return full_text

    # ------------------------------------------------------------------
    # 上下文 & 工具
    # ------------------------------------------------------------------

    def get_system_context(self, conversation_id: str) -> Optional[str]:
        """获取指定会话的系统上下文（记忆注入），供外部预览使用。"""
        conv = self.conversation_manager.get_conversation(conversation_id)
        return self._build_system_context(conv)

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """获取所有可用工具（内置 + MCP），供 GUI/CLI 展示。"""
        return self.client.get_builtin_tools()

    def has_tools_available(self) -> bool:
        """是否有可用的工具。"""
        return self.client.has_builtin_tools() or self._tool_executor_override is not None

    # ------------------------------------------------------------------
    # Tool executor override (由 App 注入 MCP)
    # ------------------------------------------------------------------

    def set_tool_executor(self, executor: Optional[Callable[[str, Dict[str, Any]], str]]):
        """设置外部工具执行器（用于 MCP 工具）。"""
        self._tool_executor_override = executor
        self.client.set_tool_executor(executor)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _build_system_context(self, conv) -> Optional[str]:
        """从 Conversation 的记忆管理器构建系统上下文。"""
        memory_manager = getattr(conv, "_memory_manager", None)
        if memory_manager is None:
            return None
        try:
            return memory_manager.build_system_prompt()
        except Exception as e:
            logger.warning(f"构建系统上下文失败: {e}")
            return None

    def _compress_context(
        self,
        conv,
        history: List[Dict[str, Any]],
        message: str,
        system_context: Optional[str],
    ) -> tuple:
        """使用 ContextManager 压缩上下文。

        Returns:
            (processed_history, processed_message) - history 不含当前消息
        """
        context_manager = getattr(conv, "_context_manager", None)
        if context_manager is None:
            return history, message

        try:
            from llm_chat.context import ContextMessage

            context_messages = []
            if system_context:
                context_messages.append(ContextMessage(role="system", content=system_context))

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

            result = context_manager.process_context(
                conversation_id=conv.conversation_id, messages=context_messages
            )

            total_sent_tokens = sum(count_tokens(m.content) for m in result.messages)
            logger.info(
                f"[ChatCore] 上下文压缩完成: token={total_sent_tokens}, "
                f"级别={result.level.name}, 节省={result.saved_tokens}"
            )

            # 分离系统提示和对话历史
            system_prompt = None
            processed_history = []
            for msg in result.messages:
                if msg.role == "system" and system_prompt is None:
                    system_prompt = msg.content
                else:
                    processed_history.append({"role": msg.role, "content": msg.content})

            # 最后一个 user 消息是当前消息
            if processed_history and processed_history[-1]["role"] == "user":
                processed_message = processed_history[-1]["content"]
                processed_history = processed_history[:-1]
            else:
                processed_message = message

            return processed_history, processed_message

        except Exception as e:
            logger.warning(f"上下文压缩失败，使用原始历史: {e}")
            return history, message

    def _call_llm(
        self,
        message: str,
        history: List[Dict[str, Any]],
        system_context: Optional[str],
        params: Dict[str, Any],
    ) -> str:
        """同步调用 LLM，自动选择工具调用或普通聊天路径。"""
        has_tools = self.client.has_builtin_tools() or self._tool_executor_override is not None

        if has_tools and self.config.enable_tools:
            tools = self.client.get_builtin_tools()
            if tools:
                if self._tool_executor_override:
                    self.client.set_tool_executor(self._tool_executor_override)
                logger.info(
                    f"[ChatCore] 同步工具调用: tools={[t.get('function', {}).get('name', '?') for t in tools]}"
                )
                return self.client.chat_with_tools(
                    message, tools, history=history, system_context=system_context, **params
                )

        logger.info("[ChatCore] 同步聊天 (无工具)")
        return self.client.chat(
            message, history=history, system_context=system_context, **params
        )

    def _extract_memory_async(self, conv, user_message: str, assistant_response: str):
        """异步提取记忆到记忆系统。"""
        memory_manager = getattr(conv, "_memory_manager", None)
        if memory_manager is None:
            return
        try:
            messages = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_response},
            ]
            memory_manager.schedule_extraction(messages)
            memory_manager.process_pending_extractions()
        except Exception as e:
            logger.warning(f"记忆提取失败: {e}")

    def _record_tokens(
        self,
        message: str,
        history: List[Dict[str, Any]],
        system_context: Optional[str],
        response: str,
    ):
        """记录本轮对话的 token 消耗 (prompt + completion)，供仪表盘使用。"""
        from llm_chat.utils.observability import get_observability
        from llm_chat.utils.token_counter import count_tokens

        obs = get_observability()

        # 估算 prompt tokens
        prompt_text = ""
        if system_context:
            prompt_text += system_context + "\n"
        for h in history:
            prompt_text += h.get("content", "") + "\n"
        prompt_text += message
        prompt_tokens = count_tokens(prompt_text)

        # 估算 completion tokens
        completion_tokens = count_tokens(response)

        model = self.config.llm.model if hasattr(self.config, 'llm') else "unknown"

        obs.increment("tokens.prompt", prompt_tokens)
        obs.increment("tokens.completion", completion_tokens)
        obs.increment(f"tokens.total", prompt_tokens + completion_tokens)
        obs.increment(f"tokens.{model}", prompt_tokens + completion_tokens)

        logger.debug(
            "Token recorded: prompt=%d, completion=%d, model=%s",
            prompt_tokens, completion_tokens, model,
        )
