# 协议适配器

## 概述

LLM 协议抽象层，支持 OpenAI/Anthropic/Gemini 三种协议，统一工具调用接口。

## 结构

```
protocols/
├── __init__.py      # PROTOCOL_MAP 注册表
├── base.py          # BaseProtocol 基类
├── openai.py        # OpenAI 协议（含 Ollama/vLLM 等）
├── anthropic.py     # Claude 协议
└── gemini.py        # Google Gemini 协议
```

## 快速定位

| 任务 | 文件 | 说明 |
|------|------|------|
| 添加新协议 | `__init__.py` | 注册到 PROTOCOL_MAP |
| 修改工具调用逻辑 | `base.py` | parse_tool_calls() |
| 修改请求格式 | `{protocol}.py` | build_chat_request() |
| 修改流式解析 | `{protocol}.py` | parse_stream_chunk() |

## 核心接口

### BaseProtocol 抽象方法

```python
class BaseProtocol:
    def build_chat_request(self, messages, **kwargs) -> dict
    def parse_chat_response(self, response) -> str
    def supports_tools(self) -> bool  # 默认 False
    def build_chat_request_with_tools(self, messages, tools, **kwargs) -> dict
    def parse_tool_calls(self, response) -> list[ToolCall]
    def has_tool_calls(self, response) -> bool
    def parse_stream_chunk(self, chunk) -> Optional[str]
```

### ToolCall 数据结构

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    status: ToolCallStatus
    result: Optional[str]
    error: Optional[str]
```

## 扩展新协议

1. 在 `protocols/` 下创建 `{protocol}.py`
2. 继承 `BaseProtocol` 并实现所有抽象方法
3. 如支持工具调用，实现 `supports_tools()` 返回 `True`
4. 在 `__init__.py` 的 `PROTOCOL_MAP` 中注册：

```python
PROTOCOL_MAP = {
    "openai": OpenAIProtocol,
    "anthropic": AnthropicProtocol,
    "gemini": GeminiProtocol,
    "your_protocol": YourProtocol,  # 添加
}
```

## 约定

- 所有协议使用 Bearer token 认证（`get_headers()`）
- 请求超时/重试由 `LLMConfig` 统一管理
- 流式响应通过 `parse_stream_chunk()` 返回增量文本

## 工具调用流程

1. `build_chat_request_with_tools()` 构建带工具的请求
2. 模型返回 `tool_calls` 时，`parse_tool_calls()` 解析
3. 执行工具后，`build_tool_result_message()` 构建工具结果消息
4. 将工具结果追加到消息历史，继续对话

## 注意事项

- OpenAI 协议兼容 Ollama/vLLM/智谱 GLM/通义千问等
- Anthropic 协议使用 `tool_use` 而非 `function_call`
- Gemini 协议使用 `functionDeclarations`
