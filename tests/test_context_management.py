import pytest
import tempfile
import time
import os
from pathlib import Path

from llm_chat.context import (
    CompressionLevel,
    ContextMessage,
    ContextCompressor,
    ContextCache,
    ContextManager,
)


class TestContextTypes:
    """测试上下文数据类型"""

    def test_context_message_conversion(self):
        """测试ContextMessage和dict的互相转换"""
        msg = ContextMessage(
            role="user",
            content="Hello, world!",
            metadata={"key": "value"},
            timestamp=time.time(),
        )

        msg_dict = msg.to_dict()
        assert msg_dict["role"] == "user"
        assert msg_dict["content"] == "Hello, world!"
        assert msg_dict["metadata"] == {"key": "value"}

        restored = ContextMessage.from_dict(msg_dict)
        assert restored.role == msg.role
        assert restored.content == msg.content
        assert restored.metadata == msg.metadata
        assert restored.timestamp == msg.timestamp

    def test_compression_level_enum(self):
        """测试压缩级别枚举"""
        assert CompressionLevel.NONE.value == 0
        assert CompressionLevel.MICRO.value == 1
        assert CompressionLevel.AUTO.value == 2
        assert CompressionLevel.MANUAL.value == 3


class TestContextCompressor:
    """测试上下文压缩器"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.transcript_dir = Path(self.temp_dir) / "transcripts"
        self.compressor = ContextCompressor(
            transcript_dir=str(self.transcript_dir),
            keep_recent_tool_results=2,
        )
        self.test_messages = [
            ContextMessage(
                role="user",
                content="你好，我想咨询一下Python的问题。",
                timestamp=time.time(),
            ),
            ContextMessage(
                role="assistant",
                content="你好！请问你有什么Python相关的问题需要帮助？",
                timestamp=time.time(),
            ),
            ContextMessage(
                role="user",
                content="我想知道如何实现一个上下文管理系统，需要支持多级压缩。",
                timestamp=time.time(),
            ),
            ContextMessage(
                role="assistant",
                content="要实现上下文管理系统，你需要考虑几个核心部分：首先是多级压缩策略，然后是缓存机制，还有上下文传递逻辑。压缩分为微压缩、自动压缩和手动压缩三个级别。",
                timestamp=time.time(),
            ),
            ContextMessage(
                role="user",
                content="那具体每个级别应该怎么做呢？",
                timestamp=time.time(),
            ),
            ContextMessage(
                role="assistant",
                content="微压缩是每次调用前替换旧工具结果为占位符；自动压缩是token超阈值时保存完整记录到磁盘再生成摘要；手动压缩是主动触发的全量压缩。",
                timestamp=time.time(),
            ),
        ]
        # 带工具结果的测试消息
        self.test_messages_with_tools = self.test_messages.copy()
        # 添加3个工具结果
        for i in range(3):
            self.test_messages_with_tools.append(
                ContextMessage(
                    role="tool",
                    content=f"这是工具{i + 1}的返回结果，包含大量内容：{'x' * 500}",
                    metadata={
                        "is_tool_result": True,
                        "tool_result_id": f"tool_{i + 1}",
                        "tool_name": f"test_tool_{i + 1}",
                    },
                    timestamp=time.time(),
                )
            )
            self.test_messages_with_tools.append(
                ContextMessage(
                    role="assistant",
                    content=f"工具{i + 1}的结果已经收到，我来分析一下。",
                    timestamp=time.time(),
                )
            )

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_none_compression(self):
        """测试NONE无压缩"""
        result = self.compressor.compress(self.test_messages, CompressionLevel.NONE)
        assert result.level == CompressionLevel.NONE
        assert len(result.messages) == len(self.test_messages)
        assert result.compression_ratio == 1.0
        assert result.saved_tokens == 0

    def test_micro_compact_replace_old_tool_results(self):
        """测试微压缩替换旧工具结果"""
        result = self.compressor.micro_compact(self.test_messages_with_tools)
        assert result.level == CompressionLevel.MICRO

        # 统计工具结果数量
        tool_results = [
            msg
            for msg in result.messages
            if msg.metadata and msg.metadata.get("is_tool_result")
        ]
        assert len(tool_results) == 3

        # 前1个工具结果应该被替换为占位符，后2个保留
        truncated_tools = [msg for msg in tool_results if msg.metadata.get("truncated")]
        assert len(truncated_tools) == 1
        assert "content truncated to save context" in truncated_tools[0].content

        # 后2个工具结果应该保留完整内容
        full_tools = [msg for msg in tool_results if not msg.metadata.get("truncated")]
        assert len(full_tools) == 2
        assert "xxxxxxxxxx" in full_tools[0].content
        assert "xxxxxxxxxx" in full_tools[1].content

        assert result.saved_tokens > 0

    def test_auto_compact_trigger_when_over_threshold(self):
        """测试自动压缩在超过阈值时触发"""
        # 创建大量消息，超过阈值
        many_messages = self.test_messages * 20  # 120条消息
        result = self.compressor.auto_compact(many_messages, max_tokens=500)

        assert result.level == CompressionLevel.AUTO
        assert result.full_transcript_path is not None
        # 转录本文件应该存在
        assert os.path.exists(result.full_transcript_path)
        # 压缩后token应该不超过阈值
        assert result.compressed_token_count <= 500 * 0.8
        # 应该包含摘要消息和最近3轮对话
        assert len(result.messages) <= 7  # 1条摘要 + 3轮*2=6条消息

    def test_manual_compact_saves_transcript_and_generates_summary(self):
        """测试手动压缩保存转录本并生成全局摘要"""
        result = self.compressor.manual_compact(
            self.test_messages_with_tools, conversation_id="test_conv"
        )

        assert result.level == CompressionLevel.MANUAL
        assert result.full_transcript_path is not None
        assert "test_conv" in result.full_transcript_path
        assert os.path.exists(result.full_transcript_path)
        # 手动压缩应该只保留最近1轮对话
        assert len(result.messages) <= 3  # 1条摘要 + 1轮*2=2条消息
        # 摘要应该包含对话主题
        assert "对话摘要" in result.messages[0].content

    def test_auto_select_level(self):
        """测试自动选择压缩级别"""
        # 极少量消息应该选NONE
        level = self.compressor.auto_select_level(
            self.test_messages[:2], max_tokens=1000
        )
        assert level == CompressionLevel.NONE

        # 中等数量消息选MICRO
        level = self.compressor.auto_select_level(
            self.test_messages_with_tools, max_tokens=1000
        )
        assert level == CompressionLevel.MICRO

        # 大量消息选AUTO
        level = self.compressor.auto_select_level(
            self.test_messages * 10, max_tokens=1000
        )
        assert level == CompressionLevel.AUTO

    def test_full_transcript_saved_correctly(self):
        """测试完整转录本保存正确"""
        result = self.compressor.manual_compact(
            self.test_messages, conversation_id="test_save"
        )

        # 读取转录本文件
        import json

        with open(result.full_transcript_path, "r", encoding="utf-8") as f:
            transcript = json.load(f)

        assert transcript["conversation_id"] == "test_save"
        assert transcript["message_count"] == len(self.test_messages)
        assert len(transcript["messages"]) == len(self.test_messages)
        assert transcript["messages"][0]["content"] == self.test_messages[0].content


class TestContextCache:
    """测试上下文缓存"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_cache.db"
        self.cache = ContextCache(str(self.db_path))
        self.test_messages = [
            ContextMessage(role="user", content="测试消息1", timestamp=time.time()),
            ContextMessage(
                role="assistant", content="测试回复1", timestamp=time.time()
            ),
        ]

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_cache_put_and_get(self):
        """测试缓存写入和读取"""
        # 写入缓存
        cache_key = self.cache.put(
            conversation_id="conv_test",
            compression_level=CompressionLevel.MICRO,
            messages=self.test_messages,
            token_count=100,
        )

        # 读取缓存
        entry = self.cache.get(
            conversation_id="conv_test",
            compression_level=CompressionLevel.MICRO,
            messages=self.test_messages,
        )

        assert entry is not None
        assert entry.cache_key == cache_key
        assert entry.conversation_id == "conv_test"
        assert entry.compression_level == CompressionLevel.MICRO
        assert len(entry.messages) == 2
        assert entry.token_count == 100
        assert entry.access_count == 1  # 读取后访问次数+1

    def test_cache_invalidate(self):
        """测试缓存失效"""
        cache_key = self.cache.put(
            conversation_id="conv_test",
            compression_level=CompressionLevel.MICRO,
            messages=self.test_messages,
            token_count=100,
        )

        # 失效单个缓存
        self.cache.invalidate(cache_key=cache_key)
        entry = self.cache.get(
            conversation_id="conv_test",
            compression_level=CompressionLevel.MICRO,
            messages=self.test_messages,
        )
        assert entry is None

        # 失效整个会话的缓存
        self.cache.put(
            conversation_id="conv_test",
            compression_level=CompressionLevel.MICRO,
            messages=self.test_messages,
            token_count=100,
        )
        self.cache.invalidate(conversation_id="conv_test")
        entry = self.cache.get(
            conversation_id="conv_test",
            compression_level=CompressionLevel.MICRO,
            messages=self.test_messages,
        )
        assert entry is None

    def test_cache_prune(self):
        """测试缓存清理"""
        # 写入多个缓存条目，模拟不同的访问时间
        for i in range(10):
            messages = [
                ContextMessage(
                    role="user", content=f"测试消息{i}", timestamp=time.time()
                )
            ]
            self.cache.put(
                conversation_id=f"conv_{i}",
                compression_level=CompressionLevel.NONE,
                messages=messages,
                token_count=10,
            )

        # 限制最大条目数为5，应该清理掉5个
        deleted = self.cache.prune(max_entries=5)
        assert deleted == 5

        stats = self.cache.get_stats()
        assert stats["total_entries"] == 5

    def test_cache_stats(self):
        """测试缓存统计"""
        self.cache.put(
            conversation_id="conv_test",
            compression_level=CompressionLevel.MICRO,
            messages=self.test_messages,
            token_count=100,
        )

        stats = self.cache.get_stats()
        assert stats["total_entries"] == 1
        assert stats["total_cached_tokens"] == 100


class TestContextManager:
    """测试上下文管理器"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.manager = ContextManager(
            max_model_tokens=4096,
            reserve_tokens=1024,
            enable_cache=False,  # 测试时禁用缓存简化
            transcript_dir=str(Path(self.temp_dir) / "transcripts"),
        )
        self.test_messages = [
            ContextMessage(
                role="user",
                content="你好，我想咨询一下Python的问题。",
                timestamp=time.time(),
            ),
            ContextMessage(
                role="assistant",
                content="你好！请问你有什么Python相关的问题需要帮助？",
                timestamp=time.time(),
            ),
            ContextMessage(
                role="user",
                content="我想知道如何实现一个上下文管理系统，需要支持多级压缩。",
                timestamp=time.time(),
            ),
            ContextMessage(
                role="assistant",
                content="要实现上下文管理系统，你需要考虑几个核心部分：首先是多级压缩策略，然后是缓存机制，还有上下文传递逻辑。",
                timestamp=time.time(),
            ),
        ]

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_process_context_auto_level(self):
        """测试自动选择级别的上下文处理"""
        result = self.manager.process_context(
            conversation_id="conv_test", messages=self.test_messages
        )

        assert result.level in (CompressionLevel.NONE, CompressionLevel.MICRO)
        assert result.compressed_token_count > 0

    def test_process_context_target_level(self):
        """测试指定级别的上下文处理"""
        result = self.manager.process_context(
            conversation_id="conv_test",
            messages=self.test_messages,
            target_level=CompressionLevel.MICRO,
        )

        assert result.level == CompressionLevel.MICRO

    def test_micro_compact_shortcut(self):
        """测试微压缩快捷方法"""
        # 带工具结果的消息
        messages = self.test_messages.copy()
        messages.append(
            ContextMessage(
                role="tool",
                content="工具结果内容" * 100,
                metadata={
                    "is_tool_result": True,
                    "tool_result_id": "test_1",
                    "tool_name": "test",
                },
            )
        )

        result = self.manager.micro_compact("conv_test", messages)
        assert result.level == CompressionLevel.MICRO

    def test_manual_compact_shortcut(self):
        """测试手动压缩快捷方法"""
        result = self.manager.manual_compact("conv_test", self.test_messages * 5)
        assert result.level == CompressionLevel.MANUAL
        assert result.full_transcript_path is not None

    def test_subagent_context_generation(self):
        """测试子代理上下文生成"""
        context = self.manager.get_context_for_subagent(
            conversation_id="conv_test",
            task_description="实现一个简单的上下文压缩功能",
            max_tokens=1000,
        )

        assert len(context) >= 1
        assert context[0].role == "system"
        assert "实现一个简单的上下文压缩功能" in context[0].content
        assert "子代理" in context[0].content
