# 大模型调用流程文档

## 概述

本文档详细说明 Vermilion Bird 项目中大模型（LLM）的调用流程，包括普通聊天、流式聊天、带工具的聊天等场景。

---

## 核心组件

### 1. LLMClient（大模型客户端）

位置：`src/llm_chat/client.py`

核心职责：
- 管理与大模型 API 的通信
- 协调工具调用流程
- 管理 Skills 和工具注册

### 2. BaseProtocol（协议基类）

位置：`src/llm_chat/protocols/base.py`

核心职责：
- 定义 API 请求格式
- 解析 API 响应
- 处理工具调用相关逻辑

### 3. ToolRegistry（工具注册表）

位置：`src/llm_chat/tools/registry.py`

核心职责：
- 管理已注册的工具
- 执行工具调用

---

## 调用流程

### 1. 普通聊天流程（非流式）

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户输入消息                                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Frontend._on_send()                                                │
│  - 获取用户输入                                                       │
│  - 添加到消息列表                                                     │
│  - 调用处理函数                                                       │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  App.handle_message()                                               │
│  - 检查是否启用工具                                                   │
│  - 获取可用工具列表                                                   │
│  - 调用 LLMClient.chat_with_tools() 或 chat()                        │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LLMClient.chat(message, history)                                   │
│  - 构建消息列表                                                       │
│  - 调用 _send_chat_request()                                         │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LLMClient._send_chat_request(messages)                             │
│  - 获取 API URL 和 Headers                                           │
│  - 构建请求数据                                                       │
│  - 发送 HTTP POST 请求                                               │
│  - 处理重试逻辑                                                       │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Protocol.build_chat_request(messages)                              │
│  - 构建符合 API 格式的请求体                                          │
│  - 包含 model, messages, temperature 等参数                          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  HTTP POST → {base_url}/chat/completions                            │
│  - 发送请求到大模型 API                                               │
│  - 接收响应                                                          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Protocol.parse_chat_response(response)                             │
│  - 解析 JSON 响应                                                    │
│  - 提取 assistant 消息内容                                           │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Frontend.display_message(response)                                 │
│  - 显示 AI 响应给用户                                                 │
└─────────────────────────────────────────────────────────────────────┘
```

### 2. 流式聊天流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户输入消息                                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LLMClient.chat_stream(message, history)                           │
│  - 构建消息列表                                                       │
│  - 调用 _send_chat_request_stream()                                  │
│  - 返回 Generator                                                    │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LLMClient._send_chat_request_stream(messages)                      │
│  - 构建请求（stream=True）                                           │
│  - 发送 HTTP POST 请求                                               │
│  - 迭代读取响应流                                                     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  HTTP POST → {base_url}/chat/completions (stream=True)              │
│  - 建立 SSE 连接                                                     │
│  - 持续接收数据块                                                     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ (循环)
┌─────────────────────────────────────────────────────────────────────┐
│  解析 SSE 数据块                                                      │
│  - 格式: data: {json}                                                │
│  - 解析 JSON 获取 delta.content                                      │
│  - yield content                                                     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ (data: [DONE])
┌─────────────────────────────────────────────────────────────────────┐
│  流式响应完成                                                         │
│  - 更新 UI 显示最终结果                                               │
└─────────────────────────────────────────────────────────────────────┘
```

### 3. 带工具的聊天流程（核心流程）

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户输入消息                                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LLMClient.chat_stream_with_tools(message, tools, history)          │
│  - 检查协议是否支持工具                                               │
│  - 初始化消息列表                                                     │
│  - 开始迭代循环（max_iterations）                                     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ┌─────────────────── 迭代循环开始 ───────────────────┐              │
│  │                                                     │              │
│  │  Protocol.build_chat_request_with_tools()          │              │
│  │  - 构建请求体，包含 tools 参数                       │              │
│  │  - tool_choice: "auto"                              │              │
│  │                                                     │              │
│  │                    ▼                                │              │
│  │                                                     │              │
│  │  HTTP POST → API (stream=True)                      │              │
│  │  - 发送请求                                          │              │
│  │  - 接收流式响应                                      │              │
│  │                                                     │              │
│  │                    ▼                                │              │
│  │                                                     │              │
│  │  解析响应                                            │              │
│  │  ├─ 有文本内容？ → yield content                    │              │
│  │  └─ 有 tool_calls？ → 收集工具调用数据              │              │
│  │                                                     │              │
│  │                    ▼                                │              │
│  │                                                     │              │
│  │  ┌────────── 有 tool_calls？ ──────────┐            │              │
│  │  │                                      │            │              │
│  │  │  是                                  │  否        │              │
│  │  │   │                                   │            │              │
│  │  │   ▼                                   ▼            │              │
│  │  │                                     返回最终响应   │              │
│  │  │  合并 tool_calls 数据                              │              │
│  │  │   │                                              │              │
│  │  │   ▼                                              │              │
│  │  │                                                  │              │
│  │  │  ┌────────── 遍历每个 tool_call ──────────┐      │              │
│  │  │  │                                        │      │              │
│  │  │  │  yield ("tool_call", name, args)       │      │              │
│  │  │  │                                        │      │              │
│  │  │  │  查找工具执行器                         │      │              │
│  │  │  │  ├─ ToolRegistry.has_tool()?           │      │              │
│  │  │  │  │   └─ execute_builtin_tool()         │      │              │
│  │  │  │  └─ _tool_executor?                    │      │              │
│  │  │  │      └─ 调用 MCP 工具                   │      │              │
│  │  │  │                                        │      │              │
│  │  │  │  构建 tool 消息                         │      │              │
│  │  │  │  - role: "tool"                        │      │              │
│  │  │  │  - tool_call_id: xxx                   │      │              │
│  │  │  │  - content: 工具执行结果                │      │              │
│  │  │  │                                        │      │              │
│  │  │  │  添加到 current_messages               │      │              │
│  │  │  └────────────────────────────────────────┘      │              │
│  │  │                                                  │              │
│  │  │  继续下一次迭代                                   │              │
│  │  │                                                  │              │
│  │  └──────────────────────────────────────────────────┘              │
│  │                                                     │              │
│  └──────────────────── 迭代循环结束 ───────────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 工具调用详细流程

### 1. 工具发现阶段

```
LLMClient.__init__()
    │
    ├─► SkillManager 初始化
    │
    ├─► 注册内置 Skill 类
    │   - WebSearchSkill
    │   - CalculatorSkill
    │
    ├─► 发现外部 Skills（external_skill_dirs）
    │
    ├─► 从配置加载 Skills
    │   │
    │   ▼
    │   Skill.on_load(config)
    │   │
    │   ▼
    │   Skill.get_tools()
    │   │
    │   ▼
    │   ToolRegistry.register(tool)
    │
    └─► 工具可用
```

### 2. 工具执行阶段

```
检测到 tool_calls
    │
    ▼
解析 tool_call
    - id: "call_xxx"
    - function.name: "web_search"
    - function.arguments: '{"query": "..."}'
    │
    ▼
查找工具执行器
    │
    ├─► ToolRegistry.has_tool("web_search")?
    │       │
    │       ▼ 是
    │   ToolRegistry.execute_tool("web_search", {"query": "..."})
    │       │
    │       ▼
    │   WebSearchTool.execute(query="...", num_results=5)
    │       │
    │       ▼
    │   返回搜索结果 JSON
    │
    └─► _tool_executor 存在?
            │
            ▼ 是
        调用 MCP 工具执行器
```

---

## API 请求格式

### OpenAI 协议

**普通聊天请求：**
```json
{
    "model": "gpt-3.5-turbo",
    "messages": [
        {"role": "user", "content": "你好"}
    ],
    "temperature": 0.7
}
```

**带工具的聊天请求：**
```json
{
    "model": "gpt-3.5-turbo",
    "messages": [
        {"role": "user", "content": "搜索今天的天气"}
    ],
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "搜索互联网获取实时信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"}
                    },
                    "required": ["query"]
                }
            }
        }
    ],
    "tool_choice": "auto",
    "temperature": 0.7
}
```

**工具调用响应：**
```json
{
    "choices": [{
        "message": {
            "role": "assistant",
            "content": null,
            "tool_calls": [{
                "id": "call_xxx",
                "type": "function",
                "function": {
                    "name": "web_search",
                    "arguments": "{\"query\": \"今天的天气\"}"
                }
            }]
        }
    }]
}
```

**工具结果消息：**
```json
{
    "role": "tool",
    "tool_call_id": "call_xxx",
    "content": "[{\"title\": \"...\", \"url\": \"...\", \"snippet\": \"...\"}]"
}
```

---

## 关键代码位置

| 功能 | 文件 | 方法 |
|------|------|------|
| 聊天入口 | `client.py` | `LLMClient.chat()` |
| 流式聊天 | `client.py` | `LLMClient.chat_stream()` |
| 带工具聊天 | `client.py` | `LLMClient.chat_stream_with_tools()` |
| 发送请求 | `client.py` | `LLMClient._send_chat_request()` |
| 构建请求 | `protocols/openai.py` | `OpenAIProtocol.build_chat_request()` |
| 解析响应 | `protocols/openai.py` | `OpenAIProtocol.parse_chat_response()` |
| 工具调用检测 | `protocols/openai.py` | `OpenAIProtocol.has_tool_calls()` |
| 工具调用解析 | `protocols/openai.py` | `OpenAIProtocol.parse_tool_calls()` |
| 工具执行 | `tools/registry.py` | `ToolRegistry.execute_tool()` |

---

## 日志追踪

启用日志后，可以追踪完整的调用流程：

```bash
python -m llm_chat.app --log-level DEBUG
```

**日志输出示例：**

```
INFO - 初始化 LLMClient: protocol=openai, model=gpt-3.5-turbo, base_url=https://api.openai.com/v1
INFO - Skills setup complete. Loaded: ['web_search', 'calculator']
INFO - 开始带工具的流式聊天: tools=['web_search', 'calculator'], max_iterations=10
DEBUG - 迭代 1: 发送请求到 https://api.openai.com/v1/chat/completions
DEBUG - 响应状态码: 200
INFO - 检测到 1 个工具调用
INFO - 工具调用: web_search, 参数: {"query": "今天的天气"}...
INFO - 开始 DuckDuckGo 搜索: query=今天的天气, num_results=5, region=cn-zh
INFO - 搜索结果 1: title=..., url=...
INFO - 工具 web_search 执行成功, 结果长度: 512
DEBUG - 迭代 2: 发送请求到 https://api.openai.com/v1/chat/completions
INFO - 流式聊天完成: response_length=256
```

---

## 错误处理

### 重试机制

```python
for i in range(self.config.llm.max_retries):
    try:
        response = self.session.post(url, json=data, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        if i == self.config.llm.max_retries - 1:
            raise
        logger.warning(f"请求失败，{i+1}秒后重试: {e}")
        time.sleep(1)
```

### 工具执行错误

```python
try:
    tool_result = self.execute_builtin_tool(tool_name, args)
except Exception as e:
    tool_result = f"Error: {str(e)}"
    is_error = True
```

---

## 配置说明

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-3.5-turbo"
  api_key: "your-api-key"
  protocol: "openai"
  timeout: 30
  max_retries: 3
  http_proxy: "http://127.0.0.1:7890"
  https_proxy: "http://127.0.0.1:7890"

enable_tools: true

skills:
  web_search:
    enabled: true
  calculator:
    enabled: true
```

---

## 更新历史

| 日期 | 版本 | 更新内容 |
|------|------|---------|
| 2024-01 | 1.0.0 | 初始版本 |
