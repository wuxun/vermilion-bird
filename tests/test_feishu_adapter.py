"""单元测试 - FeishuAdapter 核心功能。"""

import time
from unittest.mock import MagicMock, patch

import pytest

from src.llm_chat.app import App
from src.llm_chat.config import Config
from src.llm_chat.frontends.base import Message, MessageType
from src.llm_chat.frontends.feishu import (
    FeishuAdapter,
    FeishuAdapterError,
    AccessDeniedError,
    DuplicateEventError,
)
from src.llm_chat.frontends.feishu.models import (
    FeishuChat,
    FeishuEvent,
    FeishuMessage,
    FeishuUser,
)
from src.llm_chat.frontends.feishu.security import AccessController, MessageDeduplicator


class TestFeishuAdapterInit:
    def test_init_basic(self):
        """测试基本初始化。"""
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")
        assert adapter.app is app
        assert adapter.app_id == "test_app_id"
        assert adapter.app_secret == "test_secret"
        adapter.close()

    def test_init_with_security_components(self):
        """测试带安全组件的初始化。"""
        config = Config()
        app = App(config)
        deduplicator = MessageDeduplicator()
        access_controller = AccessController("open")
        adapter = FeishuAdapter(
            app,
            "test_app_id",
            "test_secret",
            deduplicator=deduplicator,
            access_controller=access_controller,
        )
        assert adapter.deduplicator is deduplicator
        assert adapter.access_controller is access_controller
        adapter.close()


class TestConvertToInternalMessage:
    def test_convert_basic_text_message(self):
        """测试基本文本消息转换。"""
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        feishu_user = FeishuUser(user_id="user123", name="Test User")
        feishu_chat = FeishuChat(chat_id="chat456", type="p2p")
        feishu_msg = FeishuMessage(
            message_id="msg789",
            chat=feishu_chat,
            sender=feishu_user,
            text="Hello from Feishu",
        )
        event = FeishuEvent(
            event_id="event001",
            event_type="im.message.receive",
            message=feishu_msg,
        )

        internal_msg = adapter._convert_to_internal_message(event)

        assert internal_msg.content == "Hello from Feishu"
        assert internal_msg.role == "user"
        assert internal_msg.msg_type == MessageType.TEXT
        assert internal_msg.metadata["event_id"] == "event001"
        assert internal_msg.metadata["sender_id"] == "user123"
        assert internal_msg.metadata["chat_id"] == "chat456"
        assert internal_msg.metadata["chat_type"] == "p2p"
        adapter.close()

    def test_convert_message_with_rich_text(self):
        """测试富文本消息转换。"""
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        feishu_msg = FeishuMessage(
            message_id="msg001",
            content={
                "post": {
                    "zh_cn": {
                        "title": "Title",
                        "content": [
                            [{"tag": "text", "text": "Paragraph 1"}],
                            [{"tag": "text", "text": "Paragraph 2"}],
                        ],
                    }
                }
            },
        )
        event = FeishuEvent(event_id="event001", message=feishu_msg)

        internal_msg = adapter._convert_to_internal_message(event)

        assert "Paragraph 1" in internal_msg.content
        assert "Paragraph 2" in internal_msg.content
        adapter.close()

    def test_convert_event_without_message_raises_error(self):
        """测试无消息事件应该返回 None。"""
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        event = FeishuEvent(event_id="event001")

        result = adapter.handle_event(event)

        assert result is None
        adapter.close()


class TestConvertToFeishuMessage:
    def test_convert_response_to_feishu_message(self):
        """测试将 LLM 响应转换为 Feishu 消息。"""
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        original_chat = FeishuChat(chat_id="chat123", type="group")
        original_msg = FeishuMessage(chat=original_chat)

        response = adapter._convert_to_feishu_message("LLM response", original_msg)

        assert response.text == "LLM response"
        assert response.chat is original_chat
        adapter.close()


class TestExtractTextFromContent:
    def test_extract_simple_text(self):
        """测试提取简单文本。"""
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        content = {"text": "Simple text message"}
        result = adapter._extract_text_from_content(content)

        assert result == "Simple text message"
        adapter.close()

    def test_extract_rich_text_post(self):
        """测试提取富文本内容。"""
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        content = {
            "post": {
                "zh_cn": {
                    "title": "Title",
                    "content": [
                        [{"tag": "text", "text": "First paragraph."}],
                        [{"tag": "text", "text": "Second paragraph."}],
                    ],
                }
            }
        }
        result = adapter._extract_text_from_content(content)

        assert "First paragraph." in result
        assert "Second paragraph." in result
        adapter.close()

    def test_extract_empty_content(self):
        """测试空内容返回空字符串。"""
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        result = adapter._extract_text_from_content({})

        assert result == ""
        adapter.close()


class TestGetChatType:
    def test_get_p2p_chat_type(self):
        """测试 P2P 聊天类型识别。"""
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        msg = FeishuMessage(chat=FeishuChat(type="p2p"))
        result = adapter._get_chat_type(msg)

        assert result == "p2p"
        adapter.close()

    def test_get_group_chat_type(self):
        """测试群聊类型识别。"""
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        msg = FeishuMessage(chat=FeishuChat(type="group"))
        result = adapter._get_chat_type(msg)

        assert result == "group"
        adapter.close()

    def test_get_unknown_chat_type_defaults_to_p2p(self):
        """测试未知类型默认为 P2P。"""
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        msg = FeishuMessage()
        result = adapter._get_chat_type(msg)

        assert result == "p2p"
        adapter.close()


class TestHandleEvent:
    def test_handle_event_without_message(self):
        """测试处理无消息事件。"""
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        event = FeishuEvent(event_id="event001")

        result = adapter.handle_event(event)

        assert result is None
        adapter.close()

    def test_handle_event_with_duplicate_detection(self):
        """测试重复事件检测。"""
        config = Config()
        app = App(config)
        deduplicator = MessageDeduplicator()
        adapter = FeishuAdapter(
            app,
            "test_app_id",
            "test_secret",
            deduplicator=deduplicator,
        )

        feishu_msg = FeishuMessage(
            message_id="msg001",
            chat=FeishuChat(chat_id="chat123"),
            text="Hello",
        )
        event = FeishuEvent(event_id="event001", message=feishu_msg)

        with patch.object(app, "get_conversation") as mock_get_conv:
            mock_conv = MagicMock()
            mock_conv.send_message.return_value = "Response"
            mock_get_conv.return_value = mock_conv

            result1 = adapter.handle_event(event)
            assert result1 is not None

            # 第二次处理应该失败
            with pytest.raises(DuplicateEventError):
                adapter.handle_event(event)

        adapter.close()

    def test_handle_event_with_access_control_denied(self):
        """测试访问控制拒绝。"""
        config = Config()
        app = App(config)
        access_controller = AccessController("whitelist", whitelist={"allowed_user"})
        adapter = FeishuAdapter(
            app,
            "test_app_id",
            "test_secret",
            access_controller=access_controller,
        )

        feishu_user = FeishuUser(user_id="blocked_user", name="Blocked User")
        feishu_msg = FeishuMessage(
            message_id="msg001",
            chat=FeishuChat(chat_id="chat123"),
            sender=feishu_user,
            text="Hello",
        )
        event = FeishuEvent(event_id="event001", message=feishu_msg)

        with patch.object(app, "get_conversation") as mock_get_conv:
            mock_get_conv.return_value = MagicMock()

            with pytest.raises(AccessDeniedError):
                adapter.handle_event(event)

        adapter.close()


class TestProcessWithLlm:
    def test_process_with_llm_sync(self):
        """测试同步 LLM 处理。"""
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        internal_msg = Message(content="Hello", role="user", msg_type=MessageType.TEXT)

        # 通过 ChatCore 统一处理（新架构），mock ChatCore.send_message
        with patch.object(app.chat_core, "send_message", return_value="LLM response") as mock_send:
            result = adapter._process_with_llm(internal_msg, "test_conv_id")

            assert result == "LLM response"
            mock_send.assert_called_once_with(
                conversation_id="test_conv_id",
                message="Hello",
            )
        adapter.close()
