from unittest.mock import MagicMock, patch

import pytest

from src.llm_chat.app import App
from src.llm_chat.config import Config
from src.llm_chat.frontends.feishu import (
    FeishuAdapter,
    FeishuAdapterError,
    PushService,
    PushServiceError,
)


class TestPushServiceInit:
    def test_init_with_adapter(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")
        push = PushService(adapter)

        assert push._adapter is adapter
        assert push.get_active_sessions() == set()
        adapter.close()

    def test_session_management(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")
        push = PushService(adapter)

        push.register_session("session_1")
        push.register_session("session_2")
        assert push.get_active_sessions() == {"session_1", "session_2"}

        push.unregister_session("session_1")
        assert push.get_active_sessions() == {"session_2"}

        push.unregister_session("non_existent")
        assert push.get_active_sessions() == {"session_2"}
        adapter.close()


class TestPushToUser:
    def test_push_to_user_success(self):
        config = Config()
        app = App(config)
        mock_http_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 0, "data": {"message_id": "msg_001"}}
        mock_http_client.post.return_value = mock_response

        adapter = FeishuAdapter(
            app, "test_app_id", "test_secret", http_client=mock_http_client
        )
        push = PushService(adapter)

        with patch.object(
            adapter, "_get_tenant_access_token", return_value="test_token"
        ):
            result = push.push_to_user("ou_user123", "Hello User!")

        assert result["code"] == 0
        adapter.close()

    def test_push_to_user_with_custom_type(self):
        config = Config()
        app = App(config)
        mock_http_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 0, "data": {}}
        mock_http_client.post.return_value = mock_response

        adapter = FeishuAdapter(
            app, "test_app_id", "test_secret", http_client=mock_http_client
        )
        push = PushService(adapter)

        with patch.object(
            adapter, "_get_tenant_access_token", return_value="test_token"
        ):
            result = push.push_to_user("ou_user123", "Rich message", msg_type="post")

        assert result["code"] == 0
        adapter.close()

    def test_push_to_user_failure(self):
        config = Config()
        app = App(config)
        mock_adapter = MagicMock()
        mock_adapter.send_message.side_effect = FeishuAdapterError("API error")

        push = PushService(mock_adapter)

        with pytest.raises(PushServiceError, match="Failed to push to user"):
            push.push_to_user("ou_user123", "Hello")


class TestPushToGroup:
    def test_push_to_group_success(self):
        config = Config()
        app = App(config)
        mock_http_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 0, "data": {"message_id": "msg_002"}}
        mock_http_client.post.return_value = mock_response

        adapter = FeishuAdapter(
            app, "test_app_id", "test_secret", http_client=mock_http_client
        )
        push = PushService(adapter)

        with patch.object(
            adapter, "_get_tenant_access_token", return_value="test_token"
        ):
            result = push.push_to_group("oc_group456", "Hello Group!")

        assert result["code"] == 0
        adapter.close()

    def test_push_to_group_failure(self):
        config = Config()
        app = App(config)
        mock_adapter = MagicMock()
        mock_adapter.send_message.side_effect = FeishuAdapterError("API error")

        push = PushService(mock_adapter)

        with pytest.raises(PushServiceError, match="Failed to push to group"):
            push.push_to_group("oc_group456", "Hello")


class TestBroadcast:
    def test_broadcast_to_active_sessions(self):
        mock_adapter = MagicMock()
        mock_adapter.send_message.return_value = {"code": 0, "data": {}}

        push = PushService(mock_adapter)
        push.register_session("session_1")
        push.register_session("session_2")

        results = push.broadcast("Broadcast message!")

        assert len(results) == 2
        assert all(r["code"] == 0 for r in results.values())
        assert mock_adapter.send_message.call_count == 2

    def test_broadcast_with_custom_sessions(self):
        mock_adapter = MagicMock()
        mock_adapter.send_message.return_value = {"code": 0, "data": {}}

        push = PushService(mock_adapter)
        push.register_session("session_1")

        results = push.broadcast(
            "Custom broadcast", session_ids=["custom_1", "custom_2"]
        )

        assert len(results) == 2
        assert mock_adapter.send_message.call_count == 2

    def test_broadcast_empty_sessions(self):
        mock_adapter = MagicMock()

        push = PushService(mock_adapter)

        results = push.broadcast("No one to hear")

        assert results == {}
        mock_adapter.send_message.assert_not_called()

    def test_broadcast_with_partial_failure(self):
        mock_adapter = MagicMock()
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"code": 0, "data": {}}
            raise FeishuAdapterError("Failed")

        mock_adapter.send_message.side_effect = side_effect

        push = PushService(mock_adapter)
        push.register_session("session_1")
        push.register_session("session_2")

        results = push.broadcast("Partial failure")

        success_count = sum(1 for r in results.values() if "error" not in r)
        assert success_count == 1
        assert "error" in results["session_2"]

    def test_broadcast_fallback_to_open_id(self):
        mock_adapter = MagicMock()
        call_count = {"session_1": 0, "session_2": 0}

        def side_effect(receive_id, msg_type, content, receive_id_type):
            call_count[receive_id] += 1
            if receive_id_type == "chat_id" and receive_id == "session_1":
                raise FeishuAdapterError("chat_id not found")
            return {"code": 0, "data": {}}

        mock_adapter.send_message.side_effect = side_effect

        push = PushService(mock_adapter)
        push.register_session("session_1")
        push.register_session("session_2")

        results = push.broadcast("Fallback test")

        assert call_count["session_1"] == 2
        assert call_count["session_2"] == 1
        assert all("error" not in r for r in results.values())


class TestBuildContent:
    def test_build_text_content(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")
        push = PushService(adapter)

        content = push._build_content("Hello", "text")
        assert content == {"text": "Hello"}
        adapter.close()

    def test_build_post_content_with_json(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")
        push = PushService(adapter)

        import json

        post_content = {
            "zh_cn": {"title": "Title", "content": [[{"tag": "text", "text": "Body"}]]}
        }
        content = push._build_content(json.dumps(post_content), "post")
        assert content == post_content
        adapter.close()

    def test_build_post_content_with_plain_text(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")
        push = PushService(adapter)

        content = push._build_content("Plain text", "post")
        assert "zh_cn" in content
        assert content["zh_cn"]["content"][0][0]["text"] == "Plain text"
        adapter.close()

    def test_build_other_type_content(self):
        config = Config()
        app = App(config)
        adapter = FeishuAdapter(app, "test_app_id", "test_secret")
        push = PushService(adapter)

        content = push._build_content("Image data", "image")
        assert content == {"text": "Image data"}
        adapter.close()
