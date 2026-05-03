import logging
from typing import List, Dict, Any, Optional
from dataclasses import asdict

from llm_chat.utils.token_counter import count_tokens
from .types import (
    CompressionLevel,
    ContextMessage,
    CompressionResult,
    ContextCacheEntry,
)
from .compressor import ContextCompressor
from .cache import ContextCache

logger = logging.getLogger(__name__)


class ContextManager:
    """上下文管理器核心类"""

    def __init__(
        self,
        llm_client=None,
        max_model_tokens: int = 4096,
        reserve_tokens: int = 1024,  # 为系统提示和回复预留的token
        cache_db_path: Optional[str] = None,
        enable_cache: bool = True,
        auto_prune_cache: bool = True,
        transcript_dir: str = "~/.vermilion-bird/transcripts",
        keep_recent_tool_results: int = 2,
        keep_recent_dialog_rounds: int = 3,
        auto_compact_threshold: float = 0.8,
    ):
        self.llm_client = llm_client
        self.max_model_tokens = max_model_tokens
        self.reserve_tokens = reserve_tokens
        self.enable_cache = enable_cache

        # 计算实际可用的上下文token数量
        self.max_context_tokens = max_model_tokens - reserve_tokens

        self.compressor = ContextCompressor(
            llm_client=llm_client,
            transcript_dir=transcript_dir,
            keep_recent_tool_results=keep_recent_tool_results,
            keep_recent_dialog_rounds=keep_recent_dialog_rounds,
            auto_compact_threshold=auto_compact_threshold,
        )

        if enable_cache:
            if cache_db_path:
                self.cache = ContextCache(cache_db_path)
            else:
                self.cache = ContextCache()

            if auto_prune_cache:
                # 自动清理过期缓存
                self.cache.prune()
        else:
            self.cache = None

    def process_context(
        self,
        conversation_id: str,
        messages: List[ContextMessage],
        target_level: Optional[CompressionLevel] = None,
        force_recompress: bool = False,
    ) -> CompressionResult:
        """
        处理上下文，自动选择压缩级别并应用压缩，支持缓存
        :param conversation_id: 会话ID
        :param messages: 原始消息列表
        :param target_level: 指定压缩级别，不传则自动选择
        :param force_recompress: 强制重新压缩，忽略缓存
        :return: 压缩结果
        """
        if not messages:
            return CompressionResult(
                level=CompressionLevel.NONE,
                messages=[],
                original_token_count=0,
                compressed_token_count=0,
                compression_ratio=1.0,
                saved_tokens=0,
            )

        # 自动选择压缩级别
        if not target_level:
            target_level = self.compressor.auto_select_level(
                messages, self.max_context_tokens
            )

        # 预计算一次原始 token（后续多次使用）
        total_original = sum(count_tokens(m.content) for m in messages)

        # 尝试从缓存获取
        if self.enable_cache and self.cache and not force_recompress:
            cached = self.cache.get(conversation_id, target_level, messages=messages)
            if cached:
                logger.debug(
                    f"命中缓存: 会话{conversation_id}, 级别{target_level.name}, token={cached.token_count}"
                )
                return CompressionResult(
                    level=target_level,
                    messages=cached.messages,
                    original_token_count=total_original,
                    compressed_token_count=cached.token_count,
                    compression_ratio=cached.token_count / total_original
                    if total_original > 0
                    else 0,
                    saved_tokens=total_original - cached.token_count,
                )

        # 执行压缩
        result = self.compressor.compress(
            messages,
            target_level,
            self.max_context_tokens,
            conversation_id=conversation_id,
        )

        # 写入缓存
        if self.enable_cache and self.cache:
            self.cache.put(
                conversation_id=conversation_id,
                compression_level=result.level,
                messages=result.messages,
                token_count=result.compressed_token_count,
                message_hash=self.cache._compute_message_hash(messages),
            )

        logger.info(
            f"[CONTEXT_MANAGER] 上下文处理完成: 原始token={result.original_token_count}, 压缩后={result.compressed_token_count}, "
            f"节省={result.saved_tokens}({int((1 - result.compression_ratio) * 100)}%), 级别={result.level.name}, "
            f"最终可发送给大模型的token长度={result.compressed_token_count}, 预留回复token={self.reserve_tokens}, 模型总上下文窗口={self.max_model_tokens}"
        )

        return result

    def micro_compact(
        self,
        conversation_id: str,
        messages: List[ContextMessage],
    ) -> CompressionResult:
        """
        快捷调用微压缩，每次LLM调用前执行
        :param conversation_id: 会话ID
        :param messages: 上下文消息列表
        :return: 压缩结果
        """
        return self.process_context(
            conversation_id=conversation_id,
            messages=messages,
            target_level=CompressionLevel.MICRO,
        )

    def manual_compact(
        self,
        conversation_id: str,
        messages: List[ContextMessage],
    ) -> CompressionResult:
        """
        手动触发全量压缩，保存完整转录本
        :param conversation_id: 会话ID
        :param messages: 上下文消息列表
        :return: 压缩结果
        """
        result = self.compressor.manual_compact(
            messages=messages,
            conversation_id=conversation_id,
        )
        # 写入缓存
        if self.enable_cache and self.cache:
            self.cache.put(
                conversation_id=conversation_id,
                compression_level=result.level,
                messages=result.messages,
                token_count=result.compressed_token_count,
                message_hash=self.cache._compute_message_hash(messages),
            )
        return result

    def get_context_for_subagent(
        self,
        conversation_id: str,
        task_description: str,
        include_recent_rounds: int = 5,
        include_long_term_memory: bool = True,
        max_tokens: int = 2048,
    ) -> List[ContextMessage]:
        """
        获取子代理需要的上下文（增量传递模式）
        :param conversation_id: 父会话ID
        :param task_description: 子代理任务描述
        :param include_recent_rounds: 包含最近的对话轮次
        :param include_long_term_memory: 是否包含长期记忆
        :param max_tokens: 子代理上下文最大token数
        :return: 子代理上下文消息列表
        """
        from llm_chat.memory import MemoryManager

        context = []

        # 添加任务描述作为系统提示
        system_prompt = f"## 你的任务\n{task_description}\n\n"
        system_prompt += "你是一个专业的子代理，专注于完成分配给你的特定任务。请基于提供的上下文信息完成任务，不要询问额外信息。\n"

        if include_long_term_memory:
            # 尝试获取长期记忆
            try:
                # 这里需要外部传入memory_manager或者通过全局方式获取
                # 暂时简化实现，实际使用时会集成到现有记忆系统
                memory_manager = MemoryManager()
                long_term_context = memory_manager.build_system_prompt()
                if long_term_context:
                    system_prompt += "\n## 用户相关信息\n" + long_term_context
            except Exception as e:
                logger.debug(f"获取长期记忆失败: {e}")

        context.append(
            ContextMessage(
                role="system",
                content=system_prompt,
                metadata={
                    "subagent_context": True,
                    "parent_conversation_id": conversation_id,
                },
            )
        )

        # 添加最近的对话轮次
        # 这里需要从父会话获取历史消息，暂时留待集成时实现
        # 实际实现时会从conversation存储中获取最近N轮对话

        # 压缩上下文到指定token限制
        if len(context) > 1:
            result = self.compressor.compress(
                context, CompressionLevel.MICRO, max_tokens
            )
            return result.messages

        return context

    def invalidate_cache(
        self, conversation_id: Optional[str] = None, cache_key: Optional[str] = None
    ):
        """失效缓存"""
        if self.cache:
            self.cache.invalidate(conversation_id, cache_key)

    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        """获取缓存统计信息"""
        if self.cache:
            return self.cache.get_stats()
        return None

    def prune_cache(self, max_age_days: int = 30, max_entries: int = 1000) -> int:
        """清理缓存"""
        if self.cache:
            return self.cache.prune(max_age_days, max_entries)
        return 0

    def clear_cache(self):
        """清空所有缓存"""
        if self.cache:
            self.cache.clear_all()

    @staticmethod
    def from_config(
        config: Dict[str, Any], llm_client=None, storage=None
    ) -> "ContextManager":
        """从配置创建ContextManager实例"""
        context_config = config.get("context", {})
        llm_config = config.get("llm", {})

        max_tokens = context_config.get(
            "max_model_tokens", llm_config.get("max_context_tokens", 4096)
        )
        reserve_tokens = context_config.get("reserve_tokens", 1024)
        enable_cache = context_config.get("enable_cache", True)
        auto_prune_cache = context_config.get("auto_prune_cache", True)
        transcript_dir = context_config.get(
            "transcript_dir", "~/.vermilion-bird/transcripts"
        )
        keep_recent_tool_results = context_config.get("keep_recent_tool_results", 2)
        keep_recent_dialog_rounds = context_config.get("keep_recent_dialog_rounds", 3)
        auto_compact_threshold = context_config.get("auto_compact_threshold", 0.8)

        manager = ContextManager(
            llm_client=llm_client,
            max_model_tokens=max_tokens,
            reserve_tokens=reserve_tokens,
            enable_cache=enable_cache,
            auto_prune_cache=auto_prune_cache,
            transcript_dir=transcript_dir,
            keep_recent_tool_results=keep_recent_tool_results,
            keep_recent_dialog_rounds=keep_recent_dialog_rounds,
            auto_compact_threshold=auto_compact_threshold,
        )

        # 传入自定义storage实例
        if storage and enable_cache:
            manager.cache = ContextCache(storage)

        return manager
