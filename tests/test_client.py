from unittest.mock import Mock, patch
from llm_chat.client import LLMClient
from llm_chat.config import Config


def test_chat():
    """测试聊天功能"""
    config = Config()
    config.llm.base_url = "https://api.example.com/v1"
    config.llm.model = "gpt-3.5-turbo"
    config.llm.api_key = "test-api-key"
    config.llm.protocol = "openai"
    
    client = LLMClient(config)
    
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
    
    with patch.object(client.session, 'post', return_value=mock_response) as mock_post:
        response = client.chat("Hello, how are you?")
        assert response == "Hello! How can I help you today?"
        
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://api.example.com/v1/chat/completions"
        assert call_args[1]["json"]["model"] == "gpt-3.5-turbo"
        assert call_args[1]["json"]["messages"] == [{"role": "user", "content": "Hello, how are you?"}]
        assert call_args[1]["headers"]["Authorization"] == "Bearer test-api-key"


def test_chat_with_history():
    """测试带历史记录的聊天功能"""
    config = Config()
    config.llm.base_url = "https://api.example.com/v1"
    config.llm.model = "gpt-3.5-turbo"
    config.llm.protocol = "openai"
    
    client = LLMClient(config)
    
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
    
    with patch.object(client.session, 'post', return_value=mock_response) as mock_post:
        history = [
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there! How can I help you?"}
        ]
        response = client.chat("How are you?", history=history)
        assert response == "I'm doing well, thank you!"
        
        call_args = mock_post.call_args
        assert call_args[1]["json"]["messages"] == [
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there! How can I help you?"},
            {"role": "user", "content": "How are you?"}
        ]


def test_generate():
    """测试文本生成功能"""
    config = Config()
    config.llm.base_url = "https://api.example.com/v1"
    config.llm.model = "gpt-3.5-turbo"
    config.llm.protocol = "openai"
    
    client = LLMClient(config)
    
    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "choices": [
            {
                "text": "This is a generated text."
            }
        ]
    }
    
    with patch.object(client.session, 'post', return_value=mock_response) as mock_post:
        response = client.generate("Write a short sentence.")
        assert response == "This is a generated text."
        
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://api.example.com/v1/completions"
        assert call_args[1]["json"]["prompt"] == "Write a short sentence."


def test_anthropic_protocol():
    """测试 Anthropic 协议"""
    config = Config()
    config.llm.base_url = "https://api.anthropic.com/v1"
    config.llm.model = "claude-3-opus-20240229"
    config.llm.api_key = "test-anthropic-key"
    config.llm.protocol = "anthropic"
    
    client = LLMClient(config)
    
    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "content": [
            {"type": "text", "text": "Hello from Claude!"}
        ]
    }
    
    with patch.object(client.session, 'post', return_value=mock_response) as mock_post:
        response = client.chat("Hello")
        assert response == "Hello from Claude!"
        
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://api.anthropic.com/v1/messages"
        assert call_args[1]["headers"]["x-api-key"] == "test-anthropic-key"


def test_gemini_protocol():
    """测试 Gemini 协议"""
    config = Config()
    config.llm.base_url = "https://generativelanguage.googleapis.com/v1beta"
    config.llm.model = "gemini-pro"
    config.llm.api_key = "test-gemini-key"
    config.llm.protocol = "gemini"
    
    client = LLMClient(config)
    
    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Hello from Gemini!"}
                    ]
                }
            }
        ]
    }
    
    with patch.object(client.session, 'post', return_value=mock_response) as mock_post:
        response = client.chat("Hello")
        assert response == "Hello from Gemini!"
        
        call_args = mock_post.call_args
        assert "gemini-pro:generateContent" in call_args[0][0]
        assert "test-gemini-key" in call_args[0][0]
