"""Tests for context management types"""

import pytest
from llm_chat.context.types import (
    CompressionLevel,
    ContextMessage,
    CompressionResult,
    ContextCacheEntry,
)


class TestCompressionLevel:
    def test_enum_values(self):
        assert CompressionLevel.NONE.value == 0
        assert CompressionLevel.MICRO.value == 1
        assert CompressionLevel.AUTO.value == 2
        assert CompressionLevel.MANUAL.value == 3


class TestContextMessage:
    def test_create(self):
        msg = ContextMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.metadata is None
        assert msg.timestamp is None

    def test_create_with_metadata(self):
        msg = ContextMessage(
            role="assistant",
            content="hi",
            metadata={"tool_calls": []},
            timestamp=1234567890.0,
        )
        assert msg.metadata == {"tool_calls": []}
        assert msg.timestamp == 1234567890.0

    def test_to_dict(self):
        msg = ContextMessage(role="system", content="prompt", metadata={"key": "val"})
        d = msg.to_dict()
        assert d == {
            "role": "system",
            "content": "prompt",
            "metadata": {"key": "val"},
            "timestamp": None,
        }

    def test_from_dict(self):
        data = {
            "role": "user",
            "content": "test",
            "metadata": {"k": "v"},
            "timestamp": 1000.0,
        }
        msg = ContextMessage.from_dict(data)
        assert msg.role == "user"
        assert msg.content == "test"
        assert msg.metadata == {"k": "v"}
        assert msg.timestamp == 1000.0

    def test_from_dict_missing_optional(self):
        msg = ContextMessage.from_dict({"role": "user", "content": "test"})
        assert msg.metadata is None
        assert msg.timestamp is None


class TestCompressionResult:
    def test_create(self):
        msgs = [ContextMessage(role="user", content="hi")]
        result = CompressionResult(
            level=CompressionLevel.MICRO,
            messages=msgs,
            original_token_count=1000,
            compressed_token_count=700,
            compression_ratio=0.7,
            saved_tokens=300,
            full_transcript_path="/tmp/transcript.json",
        )
        assert result.level == CompressionLevel.MICRO
        assert len(result.messages) == 1
        assert result.original_token_count == 1000
        assert result.compressed_token_count == 700
        assert result.compression_ratio == 0.7
        assert result.saved_tokens == 300
        assert result.full_transcript_path == "/tmp/transcript.json"

    def test_default_full_transcript_path(self):
        msgs = [ContextMessage(role="user", content="hi")]
        result = CompressionResult(
            level=CompressionLevel.NONE,
            messages=msgs,
            original_token_count=100,
            compressed_token_count=100,
            compression_ratio=1.0,
            saved_tokens=0,
        )
        assert result.full_transcript_path is None


class TestContextCacheEntry:
    def test_create(self):
        msgs = [ContextMessage(role="user", content="cached")]
        entry = ContextCacheEntry(
            cache_key="key_123",
            conversation_id="conv_1",
            compression_level=CompressionLevel.AUTO,
            messages=msgs,
            token_count=50,
            created_at=1000000.0,
            last_accessed=1000100.0,
            access_count=3,
        )
        assert entry.cache_key == "key_123"
        assert entry.conversation_id == "conv_1"
        assert entry.compression_level == CompressionLevel.AUTO
        assert entry.token_count == 50
        assert entry.access_count == 3

    def test_default_access_count(self):
        entry = ContextCacheEntry(
            cache_key="k",
            conversation_id="c",
            compression_level=CompressionLevel.NONE,
            messages=[],
            token_count=0,
            created_at=0.0,
            last_accessed=0.0,
        )
        assert entry.access_count == 0
