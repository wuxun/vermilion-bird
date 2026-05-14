"""Test Conversation: message persistence, history, and clear.

Updated: send_message has been moved to ChatCore; Conversation now uses
add_user_message / add_assistant_message for message management.
"""

import os
import shutil
from unittest.mock import patch
from llm_chat.conversation import Conversation
from llm_chat.client import LLMClient
from llm_chat.config import Config


HISTORY_DIR = os.path.expanduser("~/.vermilion-bird/history")


def setup_module():
    if os.path.exists(HISTORY_DIR):
        shutil.rmtree(HISTORY_DIR)


def teardown_module():
    if os.path.exists(HISTORY_DIR):
        shutil.rmtree(HISTORY_DIR)


def test_add_and_get_history():
    """add_user_message + add_assistant_message → get_history round-trip."""
    config = Config()
    client = LLMClient(config)

    conv = Conversation(client, "test_conv")
    conv.add_user_message("Hello, how are you?")
    conv.add_assistant_message("Hello! How can I help you today?")

    history = conv.get_history()
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Hello, how are you?"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "Hello! How can I help you today?"


def test_persistence():
    """Messages persist across Conversation instances (same conv_id)."""
    config = Config()
    client = LLMClient(config)

    conv1 = Conversation(client, "persist_conv")
    conv1.add_user_message("Hello, how are you?")
    conv1.add_assistant_message("I'm fine, thanks!")

    # New instance with same conversation_id should load history
    conv2 = Conversation(client, "persist_conv")
    history = conv2.get_history()
    assert len(history) >= 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Hello, how are you?"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "I'm fine, thanks!"


def test_clear_history():
    """clear_history removes all messages, persistence reflects it."""
    config = Config()
    client = LLMClient(config)

    conv = Conversation(client, "clear_conv")
    conv.add_user_message("Hello, how are you?")
    conv.add_assistant_message("Hi there!")
    assert len(conv.get_history()) >= 2

    conv.clear_history()
    assert len(conv.get_history()) == 0

    # New instance should also see empty
    conv2 = Conversation(client, "clear_conv")
    assert len(conv2.get_history()) == 0
