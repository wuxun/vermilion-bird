from unittest.mock import Mock, patch
from llm_chat.client import LLMClient
from llm_chat.config import Config


def test_chat():
    """测试聊天功能"""
    # 创建配置
    config = Config()
    config.llm.base_url = "https://api.example.com/v1"
    config.llm.model = "gpt-3.5-turbo"
    config.llm.api_key = "test-api-key"
    
    # 创建客户端
    client = LLMClient(config)
    
    # 模拟响应
    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "Hello! How can I help you today?"
                }
            }
        ]
    }
    
    # 模拟 session.post
    with patch.object(client.session, 'post', return_value=mock_response) as mock_post:
        # 测试聊天
        response = client.chat("Hello, how are you?")
        assert response == "Hello! How can I help you today?"
        
        # 验证请求
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://api.example.com/v1/chat/completions"
        assert call_args[1]["json"]["model"] == "gpt-3.5-turbo"
        assert call_args[1]["json"]["messages"] == [{"role": "user", "content": "Hello, how are you?"}]
        assert call_args[1]["headers"]["Authorization"] == "Bearer test-api-key"


def test_chat_with_history():
    """测试带历史记录的聊天功能"""
    # 创建配置
    config = Config()
    config.llm.base_url = "https://api.example.com/v1"
    config.llm.model = "gpt-3.5-turbo"
    
    # 创建客户端
    client = LLMClient(config)
    
    # 模拟响应
    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "I'm doing well, thank you!"
                }
            }
        ]
    }
    
    # 模拟 session.post
    with patch.object(client.session, 'post', return_value=mock_response) as mock_post:
        # 测试带历史记录的聊天
        history = [
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there! How can I help you?"}
        ]
        response = client.chat("How are you?", history=history)
        assert response == "I'm doing well, thank you!"
        
        # 验证请求
        call_args = mock_post.call_args
        assert call_args[1]["json"]["messages"] == [
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there! How can I help you?"},
            {"role": "user", "content": "How are you?"}
        ]


def test_generate():
    """测试文本生成功能"""
    # 创建配置
    config = Config()
    config.llm.base_url = "https://api.example.com/v1"
    config.llm.model = "gpt-3.5-turbo"
    
    # 创建客户端
    client = LLMClient(config)
    
    # 模拟响应
    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "choices": [
            {
                "text": "This is a generated text."
            }
        ]
    }
    
    # 模拟 session.post
    with patch.object(client.session, 'post', return_value=mock_response) as mock_post:
        # 测试生成
        response = client.generate("Write a short sentence.")
        assert response == "This is a generated text."
        
        # 验证请求
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://api.example.com/v1/completions"
        assert call_args[1]["json"]["prompt"] == "Write a short sentence."
