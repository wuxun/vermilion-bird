import os
import re
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path

from llm_chat.utils.token_counter import count_tokens
from .types import CompressionLevel, ContextMessage, CompressionResult

logger = logging.getLogger(__name__)


class ContextCompressor:
    """三级上下文压缩器
    Layer 1: micro_compact - 每次LLM调用前替换旧工具结果为占位符
    Layer 2: auto_compact - Token超阈值时保存完整转录本到磁盘，LLM生成摘要
    Layer 3: manual_compact - 手动触发的摘要压缩
    """

    def __init__(
        self,
        llm_client=None,
        transcript_dir: str = "~/.vermilion-bird/transcripts",
        keep_recent_tool_results: int = 2,
        keep_recent_dialog_rounds: int = 3,
        auto_compact_threshold: float = 0.8,
    ):
        self.llm_client = llm_client
        self.transcript_dir = Path(transcript_dir).expanduser()
        self.keep_recent_tool_results = keep_recent_tool_results
        self.keep_recent_dialog_rounds = keep_recent_dialog_rounds
        self.auto_compact_threshold = auto_compact_threshold
        self.transcript_dir.mkdir(parents=True, exist_ok=True)

    def compress(
        self,
        messages: List[ContextMessage],
        level: CompressionLevel,
        max_tokens: Optional[int] = None,
        conversation_id: Optional[str] = None,
    ) -> CompressionResult:
        """
        压缩上下文到指定级别
        :param messages: 原始上下文消息列表
        :param level: 压缩级别
        :param max_tokens: 最大token限制
        :param conversation_id: 会话ID，用于保存转录本
        :return: 压缩结果
        """
        original_tokens = sum(count_tokens(msg.content) for msg in messages)

        if level == CompressionLevel.NONE:
            return self._compress_none(messages, original_tokens)
        elif level == CompressionLevel.MICRO:
            return self.micro_compact(messages, original_tokens)
        elif level == CompressionLevel.AUTO:
            if not max_tokens:
                logger.warning("AUTO压缩级别需要max_tokens参数，回退到MICRO级别")
                return self.micro_compact(messages, original_tokens)
            return self.auto_compact(
                messages, max_tokens, original_tokens, conversation_id
            )
        elif level == CompressionLevel.MANUAL:
            return self.manual_compact(messages, original_tokens, conversation_id)
        else:
            return self._compress_none(messages, original_tokens)

    def _compress_none(
        self, messages: List[ContextMessage], original_tokens: int
    ) -> CompressionResult:
        """无压缩"""
        return CompressionResult(
            level=CompressionLevel.NONE,
            messages=messages.copy(),
            original_token_count=original_tokens,
            compressed_token_count=original_tokens,
            compression_ratio=1.0,
            saved_tokens=0,
        )

    def micro_compact(
        self,
        messages: List[ContextMessage],
        original_tokens: Optional[int] = None,
    ) -> CompressionResult:
        """
        Layer 1: 微压缩
        替换旧的工具结果为占位符，保留最近N个工具结果不变
        无精度损失，工具结果完整存储可回溯
        """
        if original_tokens is None:
            original_tokens = sum(count_tokens(msg.content) for msg in messages)

        logger.info(
            f"[MICRO_COMPACT] 开始微压缩: 原始消息数={len(messages)}, 原始token={original_tokens}"
        )

        compressed = []
        tool_results = []

        # 先收集所有工具结果
        for msg in messages:
            if msg.metadata and msg.metadata.get("is_tool_result"):
                tool_results.append(msg)

        # 需要保留的最近工具结果ID集合
        keep_tool_ids = set()
        if len(tool_results) > self.keep_recent_tool_results:
            keep_tool_results = tool_results[-self.keep_recent_tool_results :]
            keep_tool_ids = {
                msg.metadata.get("tool_result_id")
                for msg in keep_tool_results
                if msg.metadata.get("tool_result_id")
            }

        # 替换旧工具结果为占位符
        for msg in messages:
            if msg.metadata and msg.metadata.get("is_tool_result"):
                tool_id = msg.metadata.get("tool_result_id")
                tool_name = msg.metadata.get("tool_name", "unknown")
                if tool_id not in keep_tool_ids:
                    # 替换为占位符
                    placeholder = f"[Tool Result: {tool_name} (ID: {tool_id}), content truncated to save context]"
                    compressed_msg = ContextMessage(
                        role=msg.role,
                        content=placeholder,
                        metadata={
                            **msg.metadata,
                            "truncated": True,
                            "original_length": len(msg.content),
                        },
                        timestamp=msg.timestamp,
                    )
                    compressed.append(compressed_msg)
                    continue

            # 非工具结果或者需要保留的工具结果直接保留
            compressed.append(msg)

        compressed_tokens = sum(count_tokens(msg.content) for msg in compressed)
        saved_tokens = original_tokens - compressed_tokens
        ratio = compressed_tokens / original_tokens if original_tokens > 0 else 0

        logger.info(
            f"[MICRO_COMPACT] 微压缩完成: 压缩后token={compressed_tokens}, 节省={saved_tokens}({int((1 - ratio) * 100)}%), 替换工具结果={len([m for m in compressed if m.metadata and m.metadata.get('truncated')])}个"
        )

        return CompressionResult(
            level=CompressionLevel.MICRO,
            messages=compressed,
            original_token_count=original_tokens,
            compressed_token_count=compressed_tokens,
            compression_ratio=ratio,
            saved_tokens=saved_tokens,
        )

    def auto_compact(
        self,
        messages: List[ContextMessage],
        max_tokens: int,
        original_tokens: Optional[int] = None,
        conversation_id: Optional[str] = None,
    ) -> CompressionResult:
        """
        Layer 2: 自动压缩
        当token超过max_tokens*threshold时，保存完整转录本到磁盘，然后生成摘要
        保留最近K轮对话不变，更早的内容替换为摘要
        """
        if original_tokens is None:
            original_tokens = sum(count_tokens(msg.content) for msg in messages)

        threshold = max_tokens * self.auto_compact_threshold
        logger.info(
            f"[AUTO_COMPACT] 检查自动压缩触发条件: 原始token={original_tokens}, 阈值={int(threshold)}, max_tokens={max_tokens}"
        )

        # 先做微压缩
        micro_result = self.micro_compact(messages, original_tokens)
        if micro_result.compressed_token_count <= threshold:
            # 微压缩后已经满足要求，不需要进一步压缩
            logger.info(f"[AUTO_COMPACT] 微压缩后已满足阈值要求，无需自动压缩")
            return micro_result

        logger.info(
            f"[AUTO_COMPACT] 触发自动压缩: 微压缩后token={micro_result.compressed_token_count} > 阈值={int(threshold)}"
        )

        # 保存完整转录本到磁盘
        transcript_path = self._save_full_transcript(messages, conversation_id)

        # 保留最近K轮对话
        recent_messages = self._get_recent_dialog_rounds(
            micro_result.messages, self.keep_recent_dialog_rounds
        )
        older_messages = [
            msg for msg in micro_result.messages if msg not in recent_messages
        ]

        if not older_messages:
            return micro_result

        # 生成历史摘要
        summary = self._generate_dialog_summary(older_messages)

        # 构建压缩后的消息列表
        compressed = [
            ContextMessage(
                role="system",
                content=f"## 历史对话摘要\n{summary}\n\n完整对话记录已保存至: {transcript_path}",
                metadata={
                    "summary": True,
                    "original_messages": len(older_messages),
                    "transcript_path": str(transcript_path),
                },
                timestamp=datetime.now().timestamp(),
            )
        ]
        compressed.extend(recent_messages)

        compressed_tokens = sum(count_tokens(msg.content) for msg in compressed)
        saved_tokens = original_tokens - compressed_tokens
        ratio = compressed_tokens / original_tokens if original_tokens > 0 else 0

        logger.info(
            f"[AUTO_COMPACT] 自动压缩完成: 压缩后token={compressed_tokens}, 节省={saved_tokens}({int((1 - ratio) * 100)}%), 完整转录本已保存到={str(transcript_path)}"
        )

        return CompressionResult(
            level=CompressionLevel.AUTO,
            messages=compressed,
            original_token_count=original_tokens,
            compressed_token_count=compressed_tokens,
            compression_ratio=ratio,
            saved_tokens=saved_tokens,
            full_transcript_path=str(transcript_path),
        )

    def manual_compact(
        self,
        messages: List[ContextMessage],
        original_tokens: Optional[int] = None,
        conversation_id: Optional[str] = None,
    ) -> CompressionResult:
        """
        Layer 3: 手动压缩
        主动触发的全量压缩，保存完整转录本，生成全局摘要
        仅保留最近1轮对话
        """
        if original_tokens is None:
            original_tokens = sum(count_tokens(msg.content) for msg in messages)

        logger.info(
            f"[MANUAL_COMPACT] 手动压缩触发: 会话ID={conversation_id}, 原始消息数={len(messages)}, 原始token={original_tokens}"
        )

        # 保存完整转录本
        transcript_path = self._save_full_transcript(messages, conversation_id)

        # 保留最近1轮对话
        recent_messages = self._get_recent_dialog_rounds(messages, 1)
        all_older_messages = [msg for msg in messages if msg not in recent_messages]

        if not all_older_messages:
            return self._compress_none(messages, original_tokens)

        # 生成全局摘要
        global_summary = self._generate_dialog_summary(
            all_older_messages, is_global=True
        )

        compressed = [
            ContextMessage(
                role="system",
                content=f"## 全局对话摘要\n{global_summary}\n\n完整对话记录已保存至: {transcript_path}",
                metadata={
                    "global_summary": True,
                    "original_messages": len(all_older_messages),
                    "transcript_path": str(transcript_path),
                },
                timestamp=datetime.now().timestamp(),
            )
        ]
        compressed.extend(recent_messages)

        compressed_tokens = sum(count_tokens(msg.content) for msg in compressed)
        saved_tokens = original_tokens - compressed_tokens
        ratio = compressed_tokens / original_tokens if original_tokens > 0 else 0

        logger.info(
            f"[MANUAL_COMPACT] 手动压缩完成: 压缩后token={compressed_tokens}, 节省={saved_tokens}({int((1 - ratio) * 100)}%), 完整转录本已保存到={str(transcript_path)}"
        )

        return CompressionResult(
            level=CompressionLevel.MANUAL,
            messages=compressed,
            original_token_count=original_tokens,
            compressed_token_count=compressed_tokens,
            compression_ratio=ratio,
            saved_tokens=saved_tokens,
            full_transcript_path=str(transcript_path),
        )

    def _save_full_transcript(
        self, messages: List[ContextMessage], conversation_id: Optional[str] = None
    ) -> Path:
        """保存完整转录本到磁盘"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if conversation_id:
            filename = f"transcript_{conversation_id}_{timestamp}.json"
        else:
            filename = f"transcript_unknown_{timestamp}.json"

        file_path = self.transcript_dir / filename

        transcript_data = {
            "conversation_id": conversation_id,
            "timestamp": timestamp,
            "message_count": len(messages),
            "messages": [msg.to_dict() for msg in messages],
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(transcript_data, f, ensure_ascii=False, indent=2)

        logger.info(f"完整转录本已保存到: {file_path}")
        return file_path

    def _get_recent_dialog_rounds(
        self, messages: List[ContextMessage], round_count: int
    ) -> List[ContextMessage]:
        """获取最近N轮对话"""
        dialog_rounds = []
        current_round = []

        for msg in messages:
            current_round.append(msg)
            if msg.role == "assistant":
                dialog_rounds.append(current_round)
                current_round = []

        if current_round:
            dialog_rounds.append(current_round)

        # 取最近N轮
        recent_rounds = dialog_rounds[-round_count:] if round_count > 0 else []

        # 展开为消息列表
        recent_messages = []
        for r in recent_rounds:
            recent_messages.extend(r)

        return recent_messages

    def _generate_dialog_summary(
        self, messages: List[ContextMessage], is_global: bool = False
    ) -> str:
        """生成对话摘要，优先使用LLM，降级到规则摘要。"""
        if not messages:
            return "无历史对话"

        # 如果有LLM客户端，使用LLM生成高质量摘要
        if self.llm_client:
            try:
                # 准备摘要系统提示
                system_prompt = (
                    "你是一个精准的对话摘要助手。"
                    "提取对话中的关键信息：主题、决策、待办事项和重要上下文。"
                    "用简洁的中文输出，不要添加对话中没有的信息。"
                )

                # 准备摘要提示
                prompt = "请生成以下对话的简洁摘要：\n\n"
                for msg in messages:
                    prompt += f"{msg.role}: {msg.content}\n\n"

                if is_global:
                    prompt += "\n生成全局摘要，包含对话主题、关键结论和待办事项。"
                else:
                    prompt += "\n生成简短摘要，不要超过500字。"

                # 使用 chat() 传入 system_context 以获得更好的摘要质量
                summary = self.llm_client.chat(
                    message=prompt,
                    system_context=system_prompt,
                    history=[],
                    max_tokens=512,
                    temperature=0.3,
                )
                return summary.strip()
            except Exception as e:
                logger.warning(f"LLM生成摘要失败，回退到规则摘要: {str(e)}")

        # 规则降级实现
        user_queries = []
        key_points = []

        for msg in messages:
            if msg.role == "user":
                user_queries.append(self._truncate_text(msg.content, 80))
            elif msg.role == "assistant":
                key_points.append(self._truncate_text(msg.content, 100))

        summary_parts = []
        if user_queries:
            summary_parts.append(
                f"用户问题({len(user_queries)}个):\n"
                + "\n".join([f"- {q}" for q in user_queries[:3]])
            )
            if len(user_queries) > 3:
                summary_parts.append(f"... 还有{len(user_queries) - 3}个问题")

        if key_points:
            summary_parts.append(
                f"\n关键回复:\n" + "\n".join([f"- {p}" for p in key_points[:3]])
            )
            if len(key_points) > 3:
                summary_parts.append(f"... 还有{len(key_points) - 3}条回复")

        return "\n".join(summary_parts)

    def _truncate_text(self, text: str, max_length: int) -> str:
        """截断文本到指定长度"""
        if len(text) <= max_length:
            return text
        return text[:max_length] + "..."

    def auto_select_level(
        self, messages: List[ContextMessage], max_tokens: int
    ) -> CompressionLevel:
        """根据token数量自动选择合适的压缩级别"""
        total_tokens = sum(count_tokens(msg.content) for msg in messages)

        if total_tokens <= max_tokens * 0.6:
            return CompressionLevel.NONE
        elif total_tokens <= max_tokens * 0.8:
            return CompressionLevel.MICRO
        else:
            return CompressionLevel.AUTO
