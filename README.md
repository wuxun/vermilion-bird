# Vermilion Bird

一个简单的大模型对话客户端，支持多种 API 协议，可配置化设置。

## 功能特性

- 支持多种大模型 API 协议（OpenAI、Anthropic、Gemini）
- 配置化模型设置（base URL、模型名称、协议类型等）
- 支持多种配置方式（YAML 文件、环境变量、命令行参数）
- 命令行交互式聊天界面
- 对话历史管理与持久化
- 多轮对话上下文保持

## 安装

### 使用 Poetry

```bash
poetry install
```

### 使用 pip

```bash
pip install -e .
```

## 支持的协议

| 协议 | 适用平台 | 说明 |
|------|----------|------|
| **openai** | OpenAI、Azure OpenAI、Ollama、vLLM、智谱 GLM、通义千问等 | 最广泛使用的协议，很多平台兼容 |
| **anthropic** | Claude 系列 | Anthropic 官方 API 协议 |
| **gemini** | Google Gemini | Google 的 Gemini API 协议 |

## 配置

### 方式一：YAML 配置文件

创建 `config.yaml` 文件：

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-3.5-turbo"
  api_key: "your-api-key"
  timeout: 30
  max_retries: 3
  protocol: "openai"
```

#### 不同平台配置示例

```yaml
# OpenAI
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4"
  api_key: "sk-xxx"
  protocol: "openai"

# Azure OpenAI
llm:
  base_url: "https://your-resource.openai.azure.com/openai/deployments/your-deployment"
  model: "gpt-4"
  api_key: "your-azure-key"
  protocol: "openai"

# Ollama 本地模型
llm:
  base_url: "http://localhost:11434/v1"
  model: "llama2"
  protocol: "openai"

# Anthropic Claude
llm:
  base_url: "https://api.anthropic.com/v1"
  model: "claude-3-opus-20240229"
  api_key: "sk-ant-xxx"
  protocol: "anthropic"

# Google Gemini
llm:
  base_url: "https://generativelanguage.googleapis.com/v1beta"
  model: "gemini-pro"
  api_key: "your-google-api-key"
  protocol: "gemini"

# 智谱 GLM（兼容 OpenAI 协议）
llm:
  base_url: "https://open.bigmodel.cn/api/paas/v4"
  model: "glm-4"
  api_key: "your-zhipu-api-key"
  protocol: "openai"
```

### 方式二：环境变量

```bash
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL="gpt-3.5-turbo"
export LLM_API_KEY="your-api-key"
export LLM_PROTOCOL="openai"
export LLM_TIMEOUT="30"
export LLM_MAX_RETRIES="3"
```

### 方式三：命令行参数

```bash
vermilion-bird --protocol anthropic --model claude-3-opus-20240229 --api-key your-api-key
```

## 使用方法

### 命令行界面

#### 基本使用

```bash
vermilion-bird
```

#### 使用命令行参数

```bash
# 指定协议和模型
vermilion-bird --protocol anthropic --model claude-3-opus-20240229 --api-key your-api-key

# 使用本地 Ollama 模型
vermilion-bird --base-url http://localhost:11434/v1 --model llama2 --protocol openai

# 指定对话 ID（用于恢复之前的对话）
vermilion-bird --conversation-id conv_1234567890
```

#### 交互命令

- 输入消息后按回车发送
- 输入 `exit` 退出程序
- 输入 `clear` 清空对话历史

### Python API

#### 基本使用

```python
from llm_chat.client import LLMClient
from llm_chat.config import Config

# 加载配置
config = Config()

# 创建客户端
client = LLMClient(config)

# 发送消息
response = client.chat("Hello, how are you?")
print(response)
```

#### 使用不同协议

```python
from llm_chat.client import LLMClient
from llm_chat.config import Config

# 使用 Anthropic Claude
config = Config()
config.llm.base_url = "https://api.anthropic.com/v1"
config.llm.model = "claude-3-opus-20240229"
config.llm.api_key = "your-anthropic-key"
config.llm.protocol = "anthropic"

client = LLMClient(config)
response = client.chat("Hello!")
```

#### 对话管理

```python
from llm_chat.client import LLMClient
from llm_chat.config import Config
from llm_chat.conversation import Conversation

# 加载配置
config = Config()

# 创建客户端
client = LLMClient(config)

# 创建对话
conversation = Conversation(client, "my_conversation")

# 发送消息
response1 = conversation.send_message("Hello, how are you?")
print(response1)

response2 = conversation.send_message("What's the weather like today?")
print(response2)

# 获取对话历史
history = conversation.get_history()
print(history)

# 清空对话历史
conversation.clear_history()
```

## 项目结构

```
src/llm_chat/
├── __init__.py
├── cli.py           # 命令行接口
├── client.py        # 大模型客户端
├── config.py        # 配置管理
├── conversation.py  # 对话管理
└── protocols/       # 协议适配器
    ├── __init__.py
    ├── base.py      # 协议基类
    ├── openai.py    # OpenAI 协议
    ├── anthropic.py # Anthropic 协议
    └── gemini.py    # Gemini 协议
```

## 扩展协议

如需添加新的协议支持：

1. 在 `src/llm_chat/protocols/` 下创建新的协议适配器文件
2. 继承 `BaseProtocol` 类并实现所有抽象方法
3. 在 `protocols/__init__.py` 的 `PROTOCOL_MAP` 中注册

```python
# protocols/custom.py
from .base import BaseProtocol

class CustomProtocol(BaseProtocol):
    def get_headers(self) -> dict:
        # 实现请求头
        pass
    
    def get_chat_url(self) -> str:
        # 实现聊天 URL
        pass
    
    def build_chat_request(self, messages, **kwargs) -> dict:
        # 构建请求体
        pass
    
    def parse_chat_response(self, response) -> str:
        # 解析响应
        pass
    
    # ... 其他方法
```

## 测试

```bash
pytest
```

## 许可证

MIT
