"""Test context management: types, compressor, cache, and manager.

Updated to match post-refactor API (2026-05): transcript_dir removed from
ContextCompressor/ContextManager; ContextCache uses Storage not db_path string;
CompressionResult no longer has full_transcript_path.
"""

import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from llm_chat.context import (
    CompressionLevel,
    ContextMessage,
    ContextCompressor,
    ContextCache,
    ContextManager,
)
from llm_chat.context.types import CompressionResult


class TestContextTypes:
    """Test context data types."""

    def test_context_message_conversion(self):
        """ContextMessage to_dict / from_dict round-trip."""
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
        """CompressionLevel enum values."""
        assert CompressionLevel.NONE.value == 0
        assert CompressionLevel.MICRO.value == 1
        assert CompressionLevel.AUTO.value == 2
        assert CompressionLevel.MANUAL.value == 3


class TestCompressionResult:
    """Test CompressionResult dataclass."""

    def test_create(self):
        result = CompressionResult(
            level=CompressionLevel.NONE,
            messages=[],
            original_token_count=100,
            compressed_token_count=100,
            compression_ratio=1.0,
            saved_tokens=0,
        )
        assert result.level == CompressionLevel.NONE
        assert result.saved_tokens == 0
        assert result.compression_ratio == 1.0

    def test_attributes(self):
        result = CompressionResult(
            level=CompressionLevel.MICRO,
            messages=[],
            original_token_count=200,
            compressed_token_count=150,
            compression_ratio=0.75,
            saved_tokens=50,
        )
        assert result.saved_tokens == 50
        assert result.compressed_token_count == 150


class TestContextCompressor:
    """Test context compressor (current API: no transcript_dir)."""

    def setup_method(self):
        self.compressor = ContextCompressor(
            keep_recent_tool_results=2,
        )
        self.test_messages = [
            ContextMessage(role="user", content="你好，我想咨询Python问题。", timestamp=time.time()),
            ContextMessage(role="assistant", content="你好！有什么需要帮助？", timestamp=time.time()),
            ContextMessage(role="user", content="如何实现上下文管理系统？", timestamp=time.time()),
            ContextMessage(role="assistant", content="需要考虑多级压缩策略、缓存机制。", timestamp=time.time()),
            ContextMessage(role="user", content="具体每个级别怎么做？", timestamp=time.time()),
            ContextMessage(
                role="assistant",
                content="微压缩替换旧工具结果为占位符；自动压缩生成摘要；手动压缩全量压缩。",
                timestamp=time.time(),
            ),
        ]
        # Messages with tool results
        self.test_messages_with_tools = self.test_messages.copy()
        for i in range(3):
            self.test_messages_with_tools.append(
                ContextMessage(
                    role="tool",
                    content=f"工具{i + 1}返回结果: {'x' * 500}",
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
                    content=f"工具{i + 1}结果已收到。",
                    timestamp=time.time(),
                )
            )

    # --- compress() dispatch ---

    def test_none_compression(self):
        """compress() with NONE level returns unchanged messages."""
        result = self.compressor.compress(self.test_messages, CompressionLevel.NONE)
        assert result.level == CompressionLevel.NONE
        assert len(result.messages) == len(self.test_messages)
        assert result.compression_ratio == 1.0
        assert result.saved_tokens == 0

    def test_compress_micro(self):
        """compress() with MICRO level delegates to micro_compact."""
        result = self.compressor.compress(self.test_messages, CompressionLevel.MICRO)
        assert result.level == CompressionLevel.MICRO

    def test_compress_auto_needs_max_tokens(self):
        """compress() with AUTO level without max_tokens falls back to MICRO."""
        result = self.compressor.compress(self.test_messages, CompressionLevel.AUTO)
        # No max_tokens → warns and falls back to MICRO
        assert result.level == CompressionLevel.MICRO

    # --- micro_compact ---

    def test_micro_compact_replace_old_tool_results(self):
        """micro_compact replaces old tool results with placeholders."""
        result = self.compressor.micro_compact(self.test_messages_with_tools)
        assert result.level == CompressionLevel.MICRO

        tool_results = [
            msg for msg in result.messages
            if msg.metadata and msg.metadata.get("is_tool_result")
        ]
        assert len(tool_results) == 3

        # First tool result should be truncated (keep_recent_tool_results=2)
        truncated = [msg for msg in tool_results if msg.metadata.get("truncated")]
        assert len(truncated) == 1
        assert "content truncated" in truncated[0].content.lower()

        full = [msg for msg in tool_results if not msg.metadata.get("truncated")]
        assert len(full) == 2
        assert result.saved_tokens > 0

    # --- manual_compact ---

    def test_manual_compact_generates_summary(self):
        """manual_compact generates summary and keeps recent rounds."""
        result = self.compressor.manual_compact(self.test_messages_with_tools)
        assert result.level == CompressionLevel.MANUAL
        # Should contain a summary system message
        summaries = [m for m in result.messages if m.role == "system"]
        assert len(summaries) >= 1
        assert "摘要" in summaries[0].content
        assert result.saved_tokens > 0

    def test_manual_compact_preserves_recent(self):
        """manual_compact keeps recent 1 round of dialog."""
        many = self.test_messages * 10
        result = self.compressor.manual_compact(many)
        # Compressed message count should be <= original
        assert len(result.messages) < len(many)

    # --- edge cases ---

    def test_micro_compact_no_tools(self):
        """micro_compact on messages without tool results returns unchanged."""
        result = self.compressor.micro_compact(self.test_messages)
        assert result.level == CompressionLevel.MICRO
        assert result.saved_tokens == 0

    def test_micro_compact_single_tool(self):
        """micro_compact with single tool result keeps it (within keep_recent limit)."""
        msgs = self.test_messages.copy()
        msgs.append(
            ContextMessage(
                role="tool",
                content="single tool result",
                metadata={"is_tool_result": True, "tool_result_id": "t1", "tool_name": "test"},
                timestamp=time.time(),
            )
        )
        result = self.compressor.micro_compact(msgs)
        tool_results = [m for m in result.messages if m.metadata and m.metadata.get("is_tool_result")]
        # Single tool within keep_recent_tool_results=2 → not truncated
        assert all(not m.metadata.get("truncated") for m in tool_results)


class TestContextCache:
    """Test context cache (current API: uses Storage, not db_path string)."""

    def setup_method(self):
        import tempfile
        from llm_chat.storage import Storage
        self.temp_dir = tempfile.mkdtemp()
        db_path = str(Path(self.temp_dir) / "test_cache.db")
        self.storage = Storage(db_path)
        self.cache = ContextCache(storage=self.storage)
        self.test_messages = [
            ContextMessage(role="user", content="测试消息1", timestamp=time.time()),
            ContextMessage(role="assistant", content="测试回复1", timestamp=time.time()),
        ]

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cache_put_and_get(self):
        """Cache put and get round-trip."""
        cache_key = self.cache.put(
            conversation_id="conv_test",
            compression_level=CompressionLevel.MICRO,
            messages=self.test_messages,
            token_count=100,
        )

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

    def test_cache_invalidate(self):
        """Invalidate by cache_key or conversation_id."""
        cache_key = self.cache.put(
            conversation_id="conv_test",
            compression_level=CompressionLevel.MICRO,
            messages=self.test_messages,
            token_count=100,
        )

        # Invalidate by key
        self.cache.invalidate(cache_key=cache_key)
        entry = self.cache.get(
            conversation_id="conv_test",
            compression_level=CompressionLevel.MICRO,
            messages=self.test_messages,
        )
        assert entry is None

        # Invalidate by conversation_id
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
        """Prune by max_entries."""
        for i in range(10):
            self.cache.put(
                conversation_id=f"conv_{i}",
                compression_level=CompressionLevel.NONE,
                messages=[
                    ContextMessage(role="user", content=f"msg{i}", timestamp=time.time())
                ],
                token_count=10,
            )

        deleted = self.cache.prune(max_entries=5)
        assert deleted >= 5

        stats = self.cache.get_stats()
        assert stats["total_entries"] == 5

    def test_cache_stats(self):
        """get_stats returns correct totals."""
        self.cache.put(
            conversation_id="conv_test",
            compression_level=CompressionLevel.MICRO,
            messages=self.test_messages,
            token_count=100,
        )

        stats = self.cache.get_stats()
        assert stats["total_entries"] == 1
        assert stats["total_cached_tokens"] == 100

    def test_cache_clear_all(self):
        """clear_all removes everything."""
        self.cache.put(
            conversation_id="conv_test",
            compression_level=CompressionLevel.NONE,
            messages=self.test_messages,
            token_count=50,
        )
        self.cache.clear_all()
        stats = self.cache.get_stats()
        assert stats["total_entries"] == 0


class TestContextManager:
    """Test ContextManager (current API: no transcript_dir param)."""

    def setup_method(self):
        self.manager = ContextManager(
            max_model_tokens=4096,
            reserve_tokens=1024,
            enable_cache=False,
        )
        self.test_messages = [
            ContextMessage(role="user", content="你好，Python问题。", timestamp=time.time()),
            ContextMessage(role="assistant", content="你好！请说。", timestamp=time.time()),
            ContextMessage(role="user", content="如何实现上下文管理？", timestamp=time.time()),
            ContextMessage(role="assistant", content="多级压缩、缓存、上下文传递。", timestamp=time.time()),
        ]

    def test_process_context_auto_level(self):
        """process_context auto-selects compression level."""
        result = self.manager.process_context(
            conversation_id="conv_test", messages=self.test_messages
        )
        assert result.level in (CompressionLevel.NONE, CompressionLevel.MICRO)
        assert result.compressed_token_count > 0

    def test_process_context_target_level(self):
        """process_context with explicit target level."""
        result = self.manager.process_context(
            conversation_id="conv_test",
            messages=self.test_messages,
            target_level=CompressionLevel.MICRO,
        )
        assert result.level == CompressionLevel.MICRO

    def test_process_context_manual_level(self):
        """process_context with MANUAL target level."""
        many = self.test_messages * 10
        result = self.manager.process_context(
            conversation_id="conv_test",
            messages=many,
            target_level=CompressionLevel.MANUAL,
            force_recompress=True,
        )
        assert result.level == CompressionLevel.MANUAL

    def test_process_context_empty(self):
        """process_context with empty messages returns NONE."""
        result = self.manager.process_context(
            conversation_id="conv_test", messages=[]
        )
        assert result.level == CompressionLevel.NONE
        assert result.original_token_count == 0
