import os
import shutil
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.llm_chat.app import App
from src.llm_chat.config import Config
from src.llm_chat.frontends.base import Message, MessageType
from src.llm_chat.frontends.feishu import (
    FeishuAdapter,
    FeishuAdapterError,
    AccessDeniedError,
    DuplicateEventError,
    SessionMapper,
)
from src.llm_chat.frontends.feishu.models import (
    FeishuChat,
    FeishuEvent,
    FeishuMessage,
    FeishuUser,
)
from src.llm_chat.frontends.feishu.security import AccessController, MessageDeduplicator


def setup_module():
    if os.path.exists(".vb/history"):
        shutil.rmtree(".vb/history")


def teardown_module():
    if os.path.exists(".vb/history"):
        shutil.rmtree(".vb/history")


class TestFeishuAdapterInit:
    def test_init_basic(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")
        assert adapter.app is app
        assert adapter.app_id == "test_app_id"
        assert adapter.app_secret == "test_secret"
        adapter.close()

    def test_init_with_security_components(self):
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

    def test_http_client_lazy_init(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")
        assert adapter._http_client is None
        client = adapter.http_client
        assert isinstance(client, httpx.Client)
        adapter.close()


class TestConvertToInternalMessage:
    def test_convert_basic_text_message(self):
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
        feishu_event = FeishuEvent(
            event_id="event001",
            event_type="im.message.receive",
            message=feishu_msg,
        )

        internal_msg = adapter._convert_to_internal_message(feishu_event)

        assert internal_msg.content == "Hello from Feishu"
        assert internal_msg.role == "user"
        assert internal_msg.msg_type == MessageType.TEXT
        assert internal_msg.metadata["event_id"] == "event001"
        assert internal_msg.metadata["sender_id"] == "user123"
        assert internal_msg.metadata["chat_id"] == "chat456"
        adapter.close()

    def test_convert_message_with_content_dict(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        feishu_msg = FeishuMessage(
            message_id="msg001",
            content={"text": "Content from dict"},
        )
        feishu_event = FeishuEvent(event_id="event001", message=feishu_msg)

        internal_msg = adapter._convert_to_internal_message(feishu_event)
        assert internal_msg.content == "Content from dict"
        adapter.close()

    def test_convert_event_without_message_raises_error(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        feishu_event = FeishuEvent(event_id="event001")

        with pytest.raises(FeishuAdapterError, match="Event has no message"):
            adapter._convert_to_internal_message(feishu_event)
        adapter.close()


class TestExtractTextFromContent:
    def test_extract_simple_text(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        content = {"text": "Simple text message"}
        result = adapter._extract_text_from_content(content)
        assert result == "Simple text message"
        adapter.close()

    def test_extract_rich_text_post(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        content = {
            "post": {
                "zh_cn": {
                    "title": "Title",
                    "content": [
                        [{"tag": "text", "text": "First paragraph. "}],
                        [{"tag": "text", "text": "Second paragraph."}],
                    ],
                }
            }
        }
        result = adapter._extract_text_from_content(content)
        assert "First paragraph" in result
        assert "Second paragraph" in result
        adapter.close()

    def test_extract_empty_content(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        result = adapter._extract_text_from_content({})
        assert result == ""
        adapter.close()


class TestConvertToFeishuMessage:
    def test_convert_response(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        original_chat = FeishuChat(chat_id="chat123", type="group")
        original_msg = FeishuMessage(
            message_id="msg001",
            chat=original_chat,
        )

        response_msg = adapter._convert_to_feishu_message(
            "LLM response text", original_msg
        )

        assert response_msg.text == "LLM response text"
        assert response_msg.content == {"text": "LLM response text"}
        assert response_msg.chat is original_chat
        adapter.close()


class TestGetChatType:
    def test_p2p_chat_type(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        msg = FeishuMessage(
            message_id="msg001",
            chat=FeishuChat(chat_id="chat123", type="p2p"),
        )
        assert adapter._get_chat_type(msg) == "p2p"
        adapter.close()

    def test_group_chat_type(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        msg = FeishuMessage(
            message_id="msg001",
            chat=FeishuChat(chat_id="chat123", type="group"),
        )
        assert adapter._get_chat_type(msg) == "group"
        adapter.close()

    def test_unknown_chat_type_defaults_to_p2p(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        msg = FeishuMessage(message_id="msg001")
        assert adapter._get_chat_type(msg) == "p2p"
        adapter.close()


class TestHandleEvent:
    def test_handle_event_without_message_returns_none(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        event = FeishuEvent(event_id="event001")
        result = adapter.handle_event(event)
        assert result is None
        adapter.close()

    def test_handle_event_with_duplicate_detection(self):
        config = Config()
        app = App(config)
        deduplicator = MessageDeduplicator()
        adapter = FeishuAdapter(
            app, "test_app_id", "test_secret", deduplicator=deduplicator
        )

        feishu_msg = FeishuMessage(
            message_id="msg001",
            chat=FeishuChat(chat_id="chat123", type="p2p"),
            text="Hello",
        )
        event = FeishuEvent(event_id="event001", message=feishu_msg)

        with patch.object(app, "get_conversation") as mock_get_conv:
            mock_conv = MagicMock()
            mock_conv.get_history.return_value = []
            mock_conv.send_message.return_value = "Response"
            mock_get_conv.return_value = mock_conv

            result1 = adapter.handle_event(event)
            assert result1 is not None

            with pytest.raises(DuplicateEventError):
                adapter.handle_event(event)
        adapter.close()

    def test_handle_event_with_access_control_denied(self):
        config = Config()
        app = App(config)
        access_controller = AccessController("whitelist", whitelist={"allowed_user"})
        adapter = FeishuAdapter(
            app, "test_app_id", "test_secret", access_controller=access_controller
        )

        feishu_user = FeishuUser(user_id="blocked_user")
        feishu_msg = FeishuMessage(
            message_id="msg001",
            chat=FeishuChat(chat_id="chat123", type="p2p"),
            sender=feishu_user,
            text="Hello",
        )
        event = FeishuEvent(event_id="event001", message=feishu_msg)

        with pytest.raises(AccessDeniedError):
            adapter.handle_event(event)
        adapter.close()

    def test_handle_event_creates_correct_conversation_id(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")

        feishu_msg = FeishuMessage(
            message_id="msg001",
            chat=FeishuChat(chat_id="chat_abc_123", type="group"),
            text="Hello",
        )
        event = FeishuEvent(event_id="event001", message=feishu_msg)

        with patch.object(app, "get_conversation") as mock_get_conv:
            mock_conv = MagicMock()
            mock_conv.get_history.return_value = []
            mock_conv.send_message.return_value = "Response"
            mock_get_conv.return_value = mock_conv

            adapter.handle_event(event)

            expected_conv_id = SessionMapper.to_conversation_id("group", "chat_abc_123")
            mock_get_conv.assert_called_once_with(expected_conv_id)
        adapter.close()


class TestSendMessage:
    def test_send_message_success(self):
        config = Config()
        app = App(config)
        mock_http_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 0, "data": {"message_id": "new_msg"}}
        mock_http_client.post.return_value = mock_response

        adapter = FeishuAdapter(
            app, "test_app_id", "test_secret", http_client=mock_http_client
        )

        with patch.object(
            adapter, "_get_tenant_access_token", return_value="test_token"
        ):
            result = adapter.send_message(
                receive_id="chat123",
                msg_type="text",
                content={"text": "Hello"},
            )

        assert result["code"] == 0
        adapter.close()

    def test_send_message_api_error(self):
        config = Config()
        app = App(config)
        mock_http_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 1001, "msg": "Invalid token"}
        mock_http_client.post.return_value = mock_response

        adapter = FeishuAdapter(
            app, "test_app_id", "test_secret", http_client=mock_http_client
        )

        with patch.object(
            adapter, "_get_tenant_access_token", return_value="test_token"
        ):
            with pytest.raises(FeishuAdapterError, match="Feishu API error"):
                adapter.send_message(
                    receive_id="chat123",
                    msg_type="text",
                    content={"text": "Hello"},
                )
        adapter.close()


class TestReplyToMessage:
    def test_reply_to_message_success(self):
        config = Config()
        app = App(config)
        mock_http_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 0, "data": {}}
        mock_http_client.post.return_value = mock_response

        adapter = FeishuAdapter(
            app, "test_app_id", "test_secret", http_client=mock_http_client
        )

        with patch.object(
            adapter, "_get_tenant_access_token", return_value="test_token"
        ):
            result = adapter.reply_to_message("msg001", "Reply text")

        assert result["code"] == 0
        adapter.close()


class TestGetTenantAccessToken:
    def test_get_token_caching(self):
        config = Config()
        app = App(config)
        mock_http_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0,
            "tenant_access_token": "cached_token",
            "expire": 7200,
        }
        mock_http_client.post.return_value = mock_response

        adapter = FeishuAdapter(
            app, "test_app_id", "test_secret", http_client=mock_http_client
        )

        token1 = adapter._get_tenant_access_token()
        token2 = adapter._get_tenant_access_token()

        assert token1 == "cached_token"
        assert token2 == "cached_token"
        mock_http_client.post.assert_called_once()
        adapter.close()

    def test_get_token_auth_failure(self):
        config = Config()
        app = App(config)
        mock_http_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 1001, "msg": "Invalid credentials"}
        mock_http_client.post.return_value = mock_response

        adapter = FeishuAdapter(
            app, "test_app_id", "test_secret", http_client=mock_http_client
        )

        with pytest.raises(FeishuAdapterError, match="Auth failed"):
            adapter._get_tenant_access_token()
        adapter.close()


class TestContextManager:
    def test_context_manager_closes_client(self):
        config = Config()
        app = App(config)

        with FeishuAdapter(app, "test_app_id", "test_secret") as adapter:
            assert adapter._http_client is None or adapter._http_client is not None

        assert adapter._http_client is None
