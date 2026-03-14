import os
import shutil
from unittest.mock import Mock, patch
from llm_chat.conversation import Conversation
from llm_chat.client import LLMClient
from llm_chat.config import Config


# 测试前清理历史记录目录
def setup_module():
    if os.path.exists(".vb/history"):
        shutil.rmtree(".vb/history")


def teardown_module():
    if os.path.exists(".vb/history"):
        shutil.rmtree(".vb/history")


def test_send_message():
    """测试发送消息功能"""
    # 创建配置和客户端
    config = Config()
    client = LLMClient(config)
    
    # 模拟客户端的 chat 方法
    with patch.object(client, 'chat', return_value="Hello! How can I help you today?") as mock_chat:
        # 创建对话
        conversation = Conversation(client, "test_conv")
        
        # 发送消息
        response = conversation.send_message("Hello, how are you?")
        assert response == "Hello! How can I help you today?"
        
        # 验证客户端的 chat 方法被调用
        mock_chat.assert_called_once()
        
        # 验证对话历史
        history = conversation.get_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello, how are you?"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "Hello! How can I help you today?"


def test_persistence():
    """测试对话历史持久化"""
    # 创建配置和客户端
    config = Config()
    client = LLMClient(config)
    
    # 模拟客户端的 chat 方法
    with patch.object(client, 'chat', return_value="Hello! How can I help you today?"):
        # 创建对话并发送消息
        conversation1 = Conversation(client, "persist_conv")
        conversation1.send_message("Hello, how are you?")
        
        # 创建新的对话实例，应该加载历史
        conversation2 = Conversation(client, "persist_conv")
        history = conversation2.get_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello, how are you?"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "Hello! How can I help you today?"


def test_clear_history():
    """测试清空对话历史"""
    # 创建配置和客户端
    config = Config()
    client = LLMClient(config)
    
    # 模拟客户端的 chat 方法
    with patch.object(client, 'chat', return_value="Hello! How can I help you today?"):
        # 创建对话并发送消息
        conversation = Conversation(client, "clear_conv")
        conversation.send_message("Hello, how are you?")
        assert len(conversation.get_history()) == 2
        
        # 清空历史
        conversation.clear_history()
        assert len(conversation.get_history()) == 0
        
        # 验证持久化
        conversation2 = Conversation(client, "clear_conv")
        assert len(conversation2.get_history()) == 0
