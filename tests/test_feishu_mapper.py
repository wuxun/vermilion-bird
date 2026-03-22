"""单元测试 - SessionMapper 会话ID映射。"""

import pytest

from src.llm_chat.frontends.feishu.mapper import SessionMapper


class TestToConversationId:
    def test_to_conversation_id_p2p_chat(self):
        """测试 P2P 聊天类型映射。"""
        result = SessionMapper.to_conversation_id("p2p", "user_open_id_123")

        assert result == "feishu_p2p_user_open_id_123"

    def test_to_conversation_id_group_chat(self):
        """测试群聊类型映射。"""
        result = SessionMapper.to_conversation_id("group", "oc_group_chat_456")

        assert result == "feishu_group_oc_group_chat_456"

    def test_to_conversation_id_sanitizes_id(self):
        """测试 ID 清理和特殊字符替换。"""
        result = SessionMapper.to_conversation_id("group", "chat-id@with-special")

        # 特殊字符应该被替换为下划线
        assert result == "feishu_group_chat_id_with_special"

    def test_to_conversation_id_with_chat_id(self):
        """测试直接提供 chat_id。"""
        result = SessionMapper.to_conversation_id("group", "chat_123")

        assert result == "feishu_group_chat_123"


class TestFromConversationId:
    def test_from_conversation_id_p2p_chat(self):
        """测试解析 P2P 聊天会话ID。"""
        result = SessionMapper.from_conversation_id("feishu_p2p_user_123")

        assert result == ("p2p", "user_open_id_123")

    def test_from_conversation_id_group_chat(self):
        """测试解析群聊会话ID。"""
        result = SessionMapper.from_conversation_id("feishu_group_oc_group_chat_456")

        assert result == ("group", "oc_group_chat_456")

    def test_from_conversation_id_invalid_format(self):
        """测试无效格式的会话ID。"""
        # 测试缺少前缀的情况
        with pytest.raises(ValueError, match="Invalid conversation ID format"):
            SessionMapper.from_conversation_id("invalid_id")

        # 测试缺少下划线的情况
        with pytest.raises(ValueError, match="Invalid conversation ID format"):
            SessionMapper.from_conversation_id("feishu_invalid")


class TestSessionMapperEdgeCases:
    def test_empty_chat_type_defaults_to_p2p(self):
        """测试空 chat_type 默认为 p2p。"""
        result = SessionMapper.to_conversation_id("", "test_id")

        assert result == "feishu_p2p_test_id"

    def test_long_ids_are_truncated(self):
        """测试长 ID 被截断。"""
        long_id = "a" * 200  # 200 个字符

        # 应该被截断
        result = SessionMapper.to_conversation_id("p2p", long_id)

        assert len(result) <= 100  # 假设最大长度为 100
        assert "..." in result  # 截断标记
