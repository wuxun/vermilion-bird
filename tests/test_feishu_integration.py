"""集成测试 - 完整的 Feishu 消息流转。"""

import time
from unittest.mock import MagicMock, patch

import pytest

from src.llm_chat.app import App
from src.llm_chat.config import Config
from src.llm_chat.frontends.base import Message, MessageType
from src.llm_chat.frontends.feishu import FeishuAdapter
from src.llm_chat.frontends.feishu.models import (
    FeishuChat,
    FeishuEvent,
    FeishuMessage,
    FeishuUser,
)
from src.llm_chat.frontends.feishu.security import AccessController, MessageDeduplicator
from src.llm_chat.frontends.feishu.push import PushService


class TestCompleteMessageFlow:
    def test_message_flow_end_to_end(self):
        """测试完整的消息流转：飞书 → Adapter → App → LLM → 响应 → 飞书。"""
        config = Config()
        app = App(config)

        # Mock LLM 客户端
        mock_llm_client = MagicMock()
        app.client = mock_llm_client
        mock_llm_client.chat.return_value = "LLM response here"

        # Mock Storage
        mock_storage = MagicMock()
        app.storage = mock_storage

        # Mock Feishu API
        mock_http_client = MagicMock()
        mock_feishu_adapter = FeishuAdapter(
            app,
            "test_app_id",
            "test_secret",
            http_client=mock_http_client,
        )

        # 模拟飞书事件
        feishu_user = FeishuUser(user_id="user_123", name="Test User")
        feishu_chat = FeishuChat(chat_id="chat_456", type="p2p", name="Test Chat")
        feishu_msg = FeishuMessage(
            message_id="msg_001",
            chat=feishu_chat,
            sender=feishu_user,
            text="Hello, LLM!",
        )
        feishu_event = FeishuEvent(
            event_id="event_001",
            event_type="im.message.receive",
            message=feishu_msg,
            user=feishu_user,
            timestamp=time.time(),
        )

        # Mock Feishu API 响应
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0,
            "data": {"message_id": "reply_001"},
        }

        def mock_send_post(url, headers, json):
            """Mock HTTP POST to Feishu API."""
            if "messages" in url:
                return mock_response
            raise Exception("API not found")

        mock_http_client.post = mock_send_post

        with patch.object(
            mock_feishu_adapter, "_get_tenant_access_token", return_value="test_token"
        ):
            with patch.object(
                mock_http_client, "post", return_value=mock_response
            ) as mock_post:
                result = mock_feishu_adapter.handle_event(feishu_event)

        assert result is not None
        assert mock_llm_client.chat.called
        assert mock_feishu_adapter.send_message.called

        # 验证调用
        mock_llm_client.chat.assert_called_once()
        mock_feishu_adapter.send_message.assert_called_once()

        # 验证响应内容
        call_kwargs = mock_feishu_adapter.send_message.call_args
        assert call_kwargs[1][0] == "test_token"  # Authorization header
        assert call_kwargs[1][3]["receive_id"] == "chat_456"  # 接收者 ID

        # 验证发送的消息内容
        import json

        sent_content = json.loads(call_kwargs[1][3]["content"])
        assert sent_content["text"] == "LLM response here"

    def test_message_flow_with_access_control(self):
        """测试带访问控制的消息流转。"""
        config = Config()
        app = App(config)

        # Mock LLM 客户端
        mock_llm_client = MagicMock()
        app.client = mock_llm_client
        mock_llm_client.chat.return_value = "LLM response here"

        # Mock Storage
        mock_storage = MagicMock()
        app.storage = mock_storage

        # 创建访问控制器（只允许特定用户）
        access_controller = AccessController("whitelist", whitelist={"user_123"})

        # Mock Feishu API
        mock_http_client = MagicMock()
        mock_feishu_adapter = FeishuAdapter(
            app,
            "test_app_id",
            "test_secret",
            access_controller=access_controller,
            http_client=mock_http_client,
        )

        # 模拟被允许的用户消息
        feishu_user = FeishuUser(user_id="user_123", name="Allowed User")
        feishu_chat = FeishuChat(chat_id="chat_456", type="p2p")
        feishu_msg = FeishuMessage(
            message_id="msg_001",
            chat=feishu_chat,
            sender=feishu_user,
            text="Hello",
        )
        feishu_event = FeishuEvent(
            event_id="event_001",
            message=feishu_msg,
            user=feishu_user,
            timestamp=time.time(),
        )

        # Mock Feishu API 响应
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0,
            "data": {"message_id": "reply_001"},
        }

        def mock_send_post(url, headers, json):
            """Mock HTTP POST to Feishu API."""
            if "messages" in url:
                return mock_response
            raise Exception("API not found")

        mock_http_client.post = mock_send_post

        with patch.object(
            mock_feishu_adapter, "_get_tenant_access_token", return_value="test_token"
        ):
            with patch.object(
                mock_http_client, "post", return_value=mock_response
            ) as mock_post:
                result = mock_feishu_adapter.handle_event(feishu_event)

        assert result is not None

        # 验证 LLM 被调用
        mock_llm_client.chat.assert_called_once()

        # 验证响应被发送
        mock_feishu_adapter.send_message.assert_called_once()

    def test_message_flow_access_denied(self):
        """测试访问被拒绝的情况。"""
        config = Config()
        app = App(config)

        # Mock LLM 客户端
        mock_llm_client = MagicMock()
        app.client = mock_llm_client

        # Mock Storage
        mock_storage = MagicMock()
        app.storage = mock_storage

        # 创建访问控制器（只允许特定用户）
        access_controller = AccessController("whitelist", whitelist={"other_user"})

        # Mock Feishu API
        mock_http_client = MagicMock()
        mock_feishu_adapter = FeishuAdapter(
            app,
            "test_app_id",
            "test_secret",
            access_controller=access_controller,
            http_client=mock_http_client,
        )

        # 模拟被拒绝的用户消息
        feishu_user = FeishuUser(user_id="user_123", name="Blocked User")
        feishu_chat = FeishuChat(chat_id="chat_456", type="p2p")
        feishu_msg = FeishuMessage(
            message_id="msg_001",
            chat=feishu_chat,
            sender=feishu_user,
            text="Hello",
        )
        feishu_event = FeishuEvent(
            event_id="event_001",
            message=feishu_msg,
            user=feishu_user,
            timestamp=time.time(),
        )

        result = mock_feishu_adapter.handle_event(feishu_event)

        assert result is None
        assert not mock_llm_client.chat.called
        assert not mock_feishu_adapter.send_message.called


class TestConversationPersistence:
    def test_conversation_is_persisted(self):
        """测试会话被持久化。"""
        config = Config()
        app = App(config)

        # Mock Storage
        mock_storage = MagicMock()
        app.storage = mock_storage

        # Mock LLM 客户端
        mock_llm_client = MagicMock()
        app.client = mock_llm_client
        mock_llm_client.chat.return_value = "LLM response"

        # Mock Feishu API
        mock_http_client = MagicMock()
        mock_feishu_adapter = FeishuAdapter(
            app,
            "test_app_id",
            "test_secret",
            http_client=mock_http_client,
        )

        # 模拟飞书事件
        feishu_user = FeishuUser(user_id="user_123", name="Test User")
        feishu_chat = FeishuChat(chat_id="chat_456", type="p2p")
        feishu_msg = FeishuMessage(
            message_id="msg_001",
            chat=feishu_chat,
            sender=feishu_user,
            text="Hello",
        )
        feishu_event = FeishuEvent(
            event_id="event_001",
            message=feishu_msg,
            user=feishu_user,
            timestamp=time.time(),
        )

        # Mock Feishu API 响应
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0,
            "data": {"message_id": "reply_001"},
        }

        def mock_send_post(url, headers, json):
            """Mock HTTP POST to Feishu API."""
            if "messages" in url:
                return mock_response
            raise Exception("API not found")

        mock_http_client.post = mock_send_post

        with patch.object(
            mock_feishu_adapter, "_get_tenant_access_token", return_value="test_token"
        ):
            with patch.object(
                mock_http_client, "post", return_value=mock_response
            ) as mock_post:
                result = mock_feishu_adapter.handle_event(feishu_event)

        assert result is not None

        # 验证 Storage 被调用来保存会话
        mock_storage.get_conversation.assert_called_once_with("feishu_p2p_user_123")

        # 验证会话历史被获取
        mock_get_conv = mock_storage.get_conversation.return_value
        mock_get_conv.get_history.assert_called()


class TestProactivePush:
    def test_proactive_push_integration(self):
        """测试主动推送功能集成。"""
        config = Config()
        app = App(config)

        # Mock LLM 客户端
        mock_llm_client = MagicMock()
        app.client = mock_llm_client

        # Mock Storage
        mock_storage = MagicMock()
        app.storage = mock_storage

        # Mock Feishu API
        mock_http_client = MagicMock()
        mock_feishu_adapter = FeishuAdapter(
            app,
            "test_app_id",
            "test_secret",
            http_client=mock_http_client,
        )

        # 创建 PushService
        push_service = PushService(mock_feishu_adapter)

        # 注册会话
        push_service.register_session("feishu_p2p_user_123")

        # 发送主动推送
        push_result = push_service.push_to_user("user_123", "Proactive notification")

        # 验证推送被发送
        assert mock_feishu_adapter.send_message.called
        call_args = mock_feishu_adapter.send_message.call_args
        assert call_args[1][0] == "user_123"


class TestErrorHandling:
    def test_llm_error_is_handled(self):
        """测试 LLM 错误被正确处理。"""
        config = Config()
        app = App(config)

        # Mock LLM 客户端返回错误
        mock_llm_client = MagicMock()
        app.client = mock_llm_client
        mock_llm_client.chat.side_effect = Exception("LLM API error")

        # Mock Storage
        mock_storage = MagicMock()
        app.storage = mock_storage

        # Mock Feishu API
        mock_http_client = MagicMock()
        mock_feishu_adapter = FeishuAdapter(
            app,
            "test_app_id",
            "test_secret",
            http_client=mock_http_client,
        )

        # 模拟飞书事件
        feishu_user = FeishuUser(user_id="user_123", name="Test User")
        feishu_chat = FeishuChat(chat_id="chat_456", type="p2p")
        feishu_msg = FeishuMessage(
            message_id="msg_001",
            chat=feishu_chat,
            sender=feishu_user,
            text="Hello",
        )
        feishu_event = FeishuEvent(
            event_id="event_001",
            message=feishu_msg,
            user=feishu_user,
            timestamp=time.time(),
        )

        # Mock Feishu API 响应
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0,
            "data": {"message_id": "reply_001"},
        }

        def mock_send_post(url, headers, json):
            """Mock HTTP POST to Feishu API."""
            if "messages" in url:
                return mock_response
            raise Exception("API not found")

        mock_http_client.post = mock_send_post

        with patch.object(
            mock_feishu_adapter, "_get_tenant_access_token", return_value="test_token"
        ):
            with patch.object(
                mock_http_client, "post", return_value=mock_response
            ) as mock_post:
                result = mock_feishu_adapter.handle_event(feishu_event)

        # LLM 应该被调用但不应该成功
        mock_llm_client.chat.assert_called_once()

        # 响应不应该被发送（因为 LLM 失败）
        mock_feishu_adapter.send_message.assert_not_called()
