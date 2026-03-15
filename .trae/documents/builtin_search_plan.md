# 内置网络搜索能力实现方案

## 需求分析

用户希望内置网络搜索能力，让LLM能够实时搜索互联网获取信息。

## 方案对比

### 方案一：MCP 服务器（推荐）

**实现方式**：配置内置的 MCP 搜索服务器

**优点**：

* 已有完整的 MCP 框架，无需额外开发

* 支持多种搜索服务（Brave Search、DuckDuckGo 等）

* 用户可自行配置其他搜索服务

**缺点**：

* 需要外部依赖（npx）

* 部分服务需要 API Key

**实现步骤**：

1. 在配置中添加默认搜索服务器配置
2. 启动时自动连接搜索服务
3. GUI 中添加搜索开关

### 方案二：内置工具系统

**实现方式**：创建内置工具模块，直接调用搜索 API

**优点**：

* 无需外部依赖

* 开箱即用

**缺点**：

* 需要自己实现工具调用逻辑

* 需要维护搜索 API 密钥

* 扩展性较差

### 方案三：混合方案（最佳）

**实现方式**：内置工具 + MCP 扩展

**优点**：

* 内置常用工具（搜索、计算器等），开箱即用

* 支持通过 MCP 扩展更多工具

* 灵活性最高

**缺点**：

* 实现复杂度较高

## 推荐方案：混合方案

### 架构设计

```
src/llm_chat/
├── tools/                    # 新增：内置工具模块
│   ├── __init__.py
│   ├── base.py              # 工具基类
│   ├── registry.py          # 工具注册表
│   ├── search.py            # 搜索工具
│   └── calculator.py        # 计算器工具（示例）
├── mcp/                      # 现有：MCP 扩展
└── client.py                 # 修改：集成内置工具
```

### 核心组件

#### 1. 工具基类 (tools/base.py)

```python
class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        pass
    
    @abstractmethod
    def get_parameters_schema(self) -> Dict[str, Any]:
        pass
    
    @abstractmethod
    def execute(self, **kwargs) -> str:
        pass
    
    def to_openai_tool(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_parameters_schema()
            }
        }
```

#### 2. 搜索工具 (tools/search.py)

支持多种搜索后端：

* **DuckDuckGo**：免费，无需 API Key（默认）

* **Brave Search**：需要 API Key，质量更好

* **Google Custom Search**：需要 API Key

```python
class WebSearchTool(BaseTool):
    name = "web_search"
    description = "搜索互联网获取信息"
    
    def __init__(self, engine: str = "duckduckgo", api_key: str = None):
        self.engine = engine
        self.api_key = api_key
    
    def execute(self, query: str, num_results: int = 5) -> str:
        if self.engine == "duckduckgo":
            return self._search_duckduckgo(query, num_results)
        elif self.engine == "brave":
            return self._search_brave(query, num_results)
        # ...
```

#### 3. 工具注册表 (tools/registry.py)

```python
class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
    
    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool
    
    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)
    
    def get_all_tools(self) -> List[BaseTool]:
        return list(self._tools.values())
    
    def get_tools_for_openai(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._tools.values()]
```

### 配置扩展

```yaml
# config.yaml
llm:
  # ...

tools:
  enabled: true
  builtin:
    web_search:
      enabled: true
      engine: "duckduckgo"  # duckduckgo, brave, google
      api_key: null         # 可选
    calculator:
      enabled: true

mcp:
  servers:
    # 用户自定义的 MCP 服务器
```

### 实现步骤

#### 第一阶段：内置工具框架

1. 创建 `tools/` 模块

   * `base.py` - 工具基类

   * `registry.py` - 工具注册表

   * `__init__.py` - 模块导出

2. 修改 `config.py`

   * 添加内置工具配置

3. 修改 `client.py`

   * 集成工具注册表

   * 合并内置工具和 MCP 工具

#### 第二阶段：搜索工具实现

1. 创建 `tools/search.py`

   * DuckDuckGo 搜索（免费）

   * Brave Search（可选，需 API Key）

2. 添加搜索依赖

   * `duckduckgo-search` Python 包

#### 第三阶段：GUI 集成

1. 修改 `gui.py`

   * 添加工具状态显示

   * 搜索结果展示优化

### 依赖

```toml
[tool.poetry.dependencies]
# 现有依赖...
duckduckgo-search = "^4.0"  # 免费搜索
```

### 文件变更清单

| 文件                               | 操作 | 说明      |
| -------------------------------- | -- | ------- |
| `src/llm_chat/tools/__init__.py` | 新建 | 工具模块    |
| `src/llm_chat/tools/base.py`     | 新建 | 工具基类    |
| `src/llm_chat/tools/registry.py` | 新建 | 工具注册表   |
| `src/llm_chat/tools/search.py`   | 新建 | 搜索工具    |
| `src/llm_chat/config.py`         | 修改 | 添加工具配置  |
| `src/llm_chat/client.py`         | 修改 | 集成工具调用  |
| `src/llm_chat/app.py`            | 修改 | 初始化内置工具 |
| `pyproject.toml`                 | 修改 | 添加依赖    |

### 使用示例

```python
# 用户发送消息
"帮我搜索一下今天的新闻"

# LLM 决定调用工具
{
    "tool_calls": [{
        "name": "web_search",
        "arguments": {"query": "今日新闻"}
    }]
}

# 工具执行并返回结果
# 系统将结果返回给 LLM
# LLM 生成最终回复
```

### 优势

1. **开箱即用**：内置搜索工具，无需配置即可使用
2. **可扩展**：支持通过 MCP 添加更多工具
3. **灵活配置**：用户可选择不同的搜索引擎
4. **统一接口**：内置工具和 MCP 工具使用相同的调用机制

