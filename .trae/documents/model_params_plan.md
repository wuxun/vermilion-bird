# 单对话模型参数配置实现计划

## 一、需求概述

在单个对话中支持配置：
1. **温度 (temperature)** - 控制模型输出的随机性
2. **深入思考 (reasoning)** - 启用模型的深度推理能力（如 DeepSeek R1、OpenAI o1 等）

## 二、当前架构分析

### 2.1 参数传递路径
```
Frontend → Conversation.send_message() → LLMClient.chat(**kwargs) → protocol.build_chat_request(**kwargs)
```

### 2.2 当前问题
1. `Conversation.send_message` 没有传递 `**kwargs`
2. `LLMConfig` 中没有模型参数配置
3. 协议层缺少 `reasoning` 参数支持
4. 前端没有参数配置界面

### 2.3 各协议支持情况

| 参数 | OpenAI | Anthropic | Gemini | DeepSeek |
|------|--------|-----------|--------|----------|
| temperature | ✅ | ❌ | ✅ | ✅ |
| max_tokens | ✅ | ✅ | ✅ | ✅ |
| reasoning | ❌ | ❌ | ❌ | ✅ (reasoning_effort) |

## 三、实现方案

### 3.1 配置扩展

在 `LLMConfig` 中添加模型参数：

```python
class LLMConfig(BaseSettings):
    # 现有配置...
    
    # 模型参数
    temperature: float = Field(default=0.7, description="温度参数 (0-2)")
    max_tokens: Optional[int] = Field(default=None, description="最大输出token数")
    reasoning_effort: Optional[str] = Field(default=None, description="推理深度: low/medium/high")
    top_p: Optional[float] = Field(default=None, description="Top-p 采样")
    
    class Config:
        env_prefix = "LLM_"
```

### 3.2 Conversation 类扩展

添加会话级别的参数配置：

```python
class Conversation:
    def __init__(self, client, conversation_id, storage, memory_config, model_params=None):
        # ...
        self._model_params = model_params or {}
    
    def set_model_param(self, key: str, value: Any):
        """设置单个模型参数"""
        self._model_params[key] = value
    
    def set_model_params(self, params: Dict[str, Any]):
        """批量设置模型参数"""
        self._model_params.update(params)
    
    def get_model_params(self) -> Dict[str, Any]:
        """获取当前模型参数"""
        return self._model_params.copy()
    
    def send_message(self, message: str) -> str:
        # ...
        response = self.client.chat(
            message, 
            self._get_simple_history(),
            system_context=memory_context,
            **self._model_params  # 传递模型参数
        )
```

### 3.3 协议层扩展

#### OpenAI 协议
```python
def build_chat_request(self, messages, **kwargs):
    data = {
        "model": self.model,
        "messages": messages,
    }
    
    if kwargs.get("temperature") is not None:
        data["temperature"] = kwargs["temperature"]
    
    if kwargs.get("max_tokens"):
        data["max_tokens"] = kwargs["max_tokens"]
    
    if kwargs.get("top_p"):
        data["top_p"] = kwargs["top_p"]
    
    # DeepSeek R1 / OpenAI o1 推理模式
    if kwargs.get("reasoning_effort"):
        data["reasoning_effort"] = kwargs["reasoning_effort"]
    
    return data
```

### 3.4 前端扩展

#### CLI 前端
添加交互式命令设置参数：

```
> /set temperature 0.5
温度已设置为: 0.5

> /set reasoning high
推理深度已设置为: high

> /params
当前模型参数:
  temperature: 0.5
  reasoning_effort: high
```

#### GUI 前端
添加参数设置面板：
- 温度滑块 (0-2)
- 推理深度下拉框 (low/medium/high/off)
- 最大token输入框

## 四、文件修改清单

### 4.1 配置层
- `src/llm_chat/config.py` - 添加模型参数配置

### 4.2 核心层
- `src/llm_chat/conversation.py` - 添加参数管理方法
- `src/llm_chat/client.py` - 确保参数正确传递

### 4.3 协议层
- `src/llm_chat/protocols/openai.py` - 添加 reasoning_effort 支持
- `src/llm_chat/protocols/anthropic.py` - 添加 extended_thinking 支持
- `src/llm_chat/protocols/gemini.py` - 添加 thinking_budget 支持

### 4.4 前端层
- `src/llm_chat/frontends/cli.py` - 添加参数设置命令
- `src/llm_chat/frontends/gui.py` - 添加参数设置UI

### 4.5 应用层
- `src/llm_chat/app.py` - 传递默认参数到 Conversation

## 五、实现步骤

### 阶段一：配置和核心层（第1步）
1. 扩展 `LLMConfig` 添加模型参数
2. 修改 `Conversation` 类支持参数管理
3. 确保参数正确传递到协议层

### 阶段二：协议层（第2步）
1. 更新 OpenAI 协议支持 reasoning_effort
2. 更新 Anthropic 协议支持 extended_thinking
3. 更新 Gemini 协议支持 thinking_budget

### 阶段三：CLI前端（第3步）
1. 添加 `/set` 命令设置参数
2. 添加 `/params` 命令查看参数
3. 添加 `/reset` 命令重置参数

### 阶段四：GUI前端（第4步）
1. 添加参数设置面板
2. 添加温度滑块
3. 添加推理深度下拉框

### 阶段五：测试验证（第5步）
1. 单元测试
2. 集成测试
3. 文档更新

## 六、配置文件示例

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4"
  api_key: "your-api-key"
  protocol: "openai"
  
  # 模型参数
  temperature: 0.7
  max_tokens: 4096
  reasoning_effort: medium  # low/medium/high
  top_p: 0.9
```

## 七、CLI 命令设计

```bash
# 设置温度
/set temperature 0.5

# 设置推理深度
/set reasoning high

# 设置最大token
/set max_tokens 8192

# 查看当前参数
/params

# 重置为默认值
/reset params

# 查看帮助
/help
```

## 八、GUI 设计

在输入框上方添加参数设置栏：

```
┌─────────────────────────────────────────────────────────────┐
│ [温度: 0.7 ▬▬▬▬▬○──────] [推理: 中等 ▼] [最大Token: 4096] │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  对话内容区域                                                │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ [输入消息...                                    ] [发送]    │
└─────────────────────────────────────────────────────────────┘
```

## 九、预期效果

1. **默认行为**：使用配置文件中的默认参数
2. **会话级别**：每个会话可以独立设置参数
3. **实时生效**：参数修改后立即生效，无需重启
4. **持久化**：会话参数可以保存到数据库
