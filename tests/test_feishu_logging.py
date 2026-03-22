import logging
import time

import pytest

from llm_chat.frontends.feishu.server import FeishuServer
from llm_chat.frontends.feishu.push import PushService
from llm_chat.frontends.feishu.push import PushServiceError


class DummyAdapter:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail

    def send_message(self, receive_id, msg_type, content, receive_id_type):
        if self.should_fail:
            raise FeishuAdapterError("simulated failure")
        return {"ok": True, "receive_id": receive_id}


def test_server_lifecycle_logging(caplog):
    caplog.set_level(logging.INFO)
    server = FeishuServer("id", "secret")
    server.start()
    time.sleep(0.1)
    assert "FeishuServer started in background thread" in caplog.text
    server.stop()
    time.sleep(0.1)
    assert "FeishuServer background thread stopped" in caplog.text
    assert "FeishuServer wiring up (simulated)" in caplog.text


def test_server_process_request_logging(caplog):
    caplog.set_level(logging.INFO)
    server = FeishuServer("id", "secret")
    server.start()
    time.sleep(0.05)
    server.process_request({"action": "ping"}, user_id="usr_123", chat_id="chat_789")
    time.sleep(0.05)
    assert any("Processing Feishu request" in rec.message for rec in caplog.records)
    # Ensure original IDs are not logged in plain form
    assert "usr_123" not in caplog.text
    assert "chat_789" not in caplog.text


def test_push_logging_with_mask_and_preview(caplog):
    caplog.set_level(logging.INFO)
    adapter = DummyAdapter()
    push = PushService(adapter)
    push._adapter = adapter
    # Push to user should log masked id and a 30-char preview
    push.push_to_user("open_456", "This is a sample message to test logging", "text")
    time.sleep(0.05)
    assert any("Pushing to user" in rec.message for rec in caplog.records)
    assert any(
        "preview='This is a sample message to" in rec.message for rec in caplog.records
    )
    assert all("open_456" not in rec.message for rec in caplog.records)


def test_push_logging_error_with_trace(caplog):
    caplog.set_level(logging.ERROR)
    adapter = DummyAdapter(should_fail=True)
    push = PushService(adapter)
    with pytest.raises(PushServiceError):
        push.push_to_user("open_999", "hello", "text")
    time.sleep(0.05)
    # Ensure the error log includes stack trace information
    assert any(
        "Failed to push message to user" in rec.message for rec in caplog.records
    )
    assert any(rec.levelname == "ERROR" for rec in caplog.records)
    assert any(
        "Traceback" in rec.getMessage() or rec.exc_info for rec in caplog.records
    )
