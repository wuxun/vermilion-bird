# LLM Chat

A simple LLM chat client with configurable settings. This project allows you to interact with various large language models through a unified interface.

## Features

- Configurable model settings (base URL, model name, etc.)
- Support for multiple LLM providers
- Command-line interface for interactive chat
- Conversation history management
- Context preservation for multi-turn conversations

## Installation

### Using Poetry

```bash
poetry install
```

### Using pip

```bash
pip install -e .
```

## Configuration

Create a `config.yaml` file in the project root:

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-3.5-turbo"
  api_key: "your-api-key"
  timeout: 30
  max_retries: 3
```

You can also use environment variables to override configuration values:

```bash
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL="gpt-3.5-turbo"
export LLM_API_KEY="your-api-key"
```

## Usage

### Command-line Interface

#### 基本使用

```bash
llm-chat
```

#### 使用命令行参数

```bash
# 指定模型和 API 密钥
llm-chat --model gpt-4 --api-key your-api-key

# 指定基础 URL（例如使用本地模型）
llm-chat --base-url http://localhost:8080/v1 --model local-model

# 指定对话 ID（用于恢复之前的对话）
llm-chat --conversation-id conv_1234567890
```

#### 命令行交互

- 输入消息后按回车发送
- 输入 `exit` 退出程序
- 输入 `clear` 清空对话历史

### Python API

#### 基本使用

```python
from llm_chat.client import LLMClient
from llm_chat.config import Config

# Load configuration
config = Config()

# Create client
client = LLMClient(config)

# Send message
response = client.chat("Hello, how are you?")
print(response)
```

#### 使用对话管理

```python
from llm_chat.client import LLMClient
from llm_chat.config import Config
from llm_chat.conversation import Conversation

# Load configuration
config = Config()

# Create client
client = LLMClient(config)

# Create conversation
conversation = Conversation(client, "my_conversation")

# Send messages
response1 = conversation.send_message("Hello, how are you?")
print(response1)

response2 = conversation.send_message("What's the weather like today?")
print(response2)

# Get conversation history
history = conversation.get_history()
print(history)

# Clear conversation history
conversation.clear_history()
```

## Supported Models

- OpenAI GPT models
- Anthropic Claude models
- Other models with compatible API

## Testing

```bash
pytest
```

## License

MIT
