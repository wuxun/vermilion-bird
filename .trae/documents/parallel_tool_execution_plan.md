# 工具调用并行执行与重试机制优化计划

## 问题分析

### 当前实现的问题

**1. 顺序执行工具调用**

当前代码在 `chat_stream_with_tools` 方法中，工具调用是顺序执行的：

```python
for tool_call in tool_calls:
    tool_name = tool_call["function"]["name"]
    tool_args = tool_call["function"]["arguments"]
    # 顺序执行每个工具
    tool_result = self.execute_builtin_tool(tool_name, args)
```

**2. 无重试机制**

工具执行失败时直接返回错误，没有重试机会：

```python
except Exception as e:
    tool_result = f"Error: {str(e)}"
    # 没有重试逻辑
```

**3. 性能问题**

- 多个独立的工具调用串行执行，浪费时间
- 网络请求（如搜索、网页抓取）可能超时，没有重试

---

## 解决方案

### 方案1：并行执行工具调用

使用 `concurrent.futures.ThreadPoolExecutor` 并行执行无依赖的工具调用：

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def execute_tools_parallel(tool_calls):
    results = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {}
        for tool_call in tool_calls:
            future = executor.submit(
                execute_single_tool,
                tool_call,
                max_retries=3
            )
            futures[future] = tool_call
        
        for future in as_completed(futures):
            tool_call = futures[future]
            try:
                result = future.result()
                results[tool_call["id"]] = result
            except Exception as e:
                results[tool_call["id"]] = f"Error: {str(e)}"
    
    return results
```

### 方案2：添加重试机制

为工具执行添加重试逻辑：

```python
def execute_tool_with_retry(tool_name, args, max_retries=3, retry_delay=1):
    last_error = None
    for attempt in range(max_retries):
        try:
            result = execute_builtin_tool(tool_name, args)
            return result
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                logger.warning(f"工具 {tool_name} 执行失败，{retry_delay}秒后重试 ({attempt+1}/{max_retries}): {e}")
                time.sleep(retry_delay)
    
    raise last_error
```

---

## 实施计划

### 阶段1：添加重试机制（基础优化）

1. **创建工具执行器类**
   - 文件：`src/llm_chat/tools/executor.py`
   - 功能：封装工具执行逻辑，支持重试

2. **更新 client.py**
   - 使用新的工具执行器
   - 添加重试配置参数

### 阶段2：并行执行（核心优化）

1. **实现并行执行器**
   - 使用 `ThreadPoolExecutor`
   - 支持配置最大并行数

2. **更新流式聊天方法**
   - 并行执行多个工具调用
   - 保持结果顺序

### 阶段3：配置支持

1. **添加配置项**
   ```yaml
   tools:
     max_workers: 5        # 最大并行数
     max_retries: 3        # 最大重试次数
     retry_delay: 1        # 重试间隔（秒）
     timeout: 30           # 单个工具超时（秒）
   ```

---

## 详细实施步骤

### 步骤1：创建工具执行器

新建文件 `src/llm_chat/tools/executor.py`:

```python
import time
import logging
from typing import Dict, Any, List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class ToolExecutor:
    def __init__(
        self,
        tool_registry,
        tool_executor: Optional[Callable] = None,
        max_workers: int = 5,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        timeout: int = 30
    ):
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
    
    def execute_single_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call_id: str
    ) -> Dict[str, Any]:
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                if self.tool_registry.has_tool(tool_name):
                    result = self.tool_registry.execute_tool(tool_name, **tool_args)
                elif self.tool_executor:
                    result = self.tool_executor(tool_name, tool_args)
                else:
                    return {
                        "tool_call_id": tool_call_id,
                        "content": f"Error: No tool executor for {tool_name}",
                        "is_error": True
                    }
                
                logger.info(f"工具 {tool_name} 执行成功, 结果长度: {len(result)}")
                return {
                    "tool_call_id": tool_call_id,
                    "content": result,
                    "is_error": False
                }
                
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    logger.warning(
                        f"工具 {tool_name} 执行失败，{self.retry_delay}秒后重试 "
                        f"({attempt+1}/{self.max_retries}): {e}"
                    )
                    time.sleep(self.retry_delay)
        
        logger.error(f"工具 {tool_name} 执行失败，重试耗尽: {last_error}")
        return {
            "tool_call_id": tool_call_id,
            "content": f"Error: {str(last_error)}",
            "is_error": True
        }
    
    def execute_tools_parallel(
        self,
        tool_calls: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if not tool_calls:
            return []
        
        if len(tool_calls) == 1:
            tool_call = tool_calls[0]
            tool_name = tool_call["function"]["name"]
            tool_args = json.loads(tool_call["function"]["arguments"])
            return [self.execute_single_tool(tool_name, tool_args, tool_call["id"])]
        
        results = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            
            for tool_call in tool_calls:
                tool_name = tool_call["function"]["name"]
                tool_args = json.loads(tool_call["function"]["arguments"])
                tool_call_id = tool_call["id"]
                
                future = executor.submit(
                    self.execute_single_tool,
                    tool_name,
                    tool_args,
                    tool_call_id
                )
                futures[future] = tool_call
            
            for future in as_completed(futures):
                tool_call = futures[future]
                try:
                    result = future.result(timeout=self.timeout)
                    results.append(result)
                except Exception as e:
                    logger.error(f"工具调用超时或失败: {e}")
                    results.append({
                        "tool_call_id": tool_call["id"],
                        "content": f"Error: {str(e)}",
                        "is_error": True
                    })
        
        return results
```

### 步骤2：更新配置

修改 `src/llm_chat/config.py`:

```python
class ToolsConfig(BaseSettings):
    max_workers: int = Field(default=5, description="工具并行执行的最大工作线程数")
    max_retries: int = Field(default=3, description="工具执行失败时的最大重试次数")
    retry_delay: float = Field(default=1.0, description="重试间隔时间（秒）")
    timeout: int = Field(default=30, description="单个工具执行超时时间（秒）")

class Config(BaseSettings):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)  # 新增
    enable_tools: bool = Field(default=True)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    external_skill_dirs: List[str] = Field(default_factory=list)
```

### 步骤3：更新 client.py

修改 `chat_stream_with_tools` 方法使用并行执行器：

```python
from llm_chat.tools.executor import ToolExecutor

class LLMClient:
    def __init__(self, config: Config):
        # ... 现有代码 ...
        
        self._tool_executor_instance = ToolExecutor(
            tool_registry=self._tool_registry,
            tool_executor=self._tool_executor,
            max_workers=config.tools.max_workers,
            max_retries=config.tools.max_retries,
            retry_delay=config.tools.retry_delay,
            timeout=config.tools.timeout
        )
    
    def chat_stream_with_tools(self, ...):
        # ... 现有代码 ...
        
        # 替换顺序执行为并行执行
        tool_results = self._tool_executor_instance.execute_tools_parallel(tool_calls)
        
        for result in tool_results:
            tool_message = {
                "role": "tool",
                "tool_call_id": result["tool_call_id"],
                "content": result["content"]
            }
            current_messages.append(tool_message)
```

---

## 预期效果

### 优化前

```
用户：搜索 Python 和 Java 的最新版本
AI：[调用 web_search("Python 最新版本")]  ← 等待 2 秒
AI：[调用 web_search("Java 最新版本")]    ← 等待 2 秒
总耗时：4 秒
```

### 优化后

```
用户：搜索 Python 和 Java 的最新版本
AI：[并行调用 web_search("Python 最新版本"), web_search("Java 最新版本")]
总耗时：2 秒（并行执行）
```

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 线程安全问题 | 中 | 确保 ToolRegistry 的线程安全 |
| 资源消耗 | 低 | 限制最大并行数（默认 5） |
| 结果顺序 | 低 | 使用 tool_call_id 关联结果 |
| 超时处理 | 中 | 添加单个工具超时机制 |

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/llm_chat/tools/executor.py` | 新建 | 工具执行器，支持并行和重试 |
| `src/llm_chat/tools/__init__.py` | 修改 | 导出 ToolExecutor |
| `src/llm_chat/config.py` | 修改 | 添加 ToolsConfig |
| `src/llm_chat/client.py` | 修改 | 使用新的工具执行器 |

---

## 测试计划

1. **单元测试**
   - 测试单个工具执行
   - 测试重试机制
   - 测试并行执行

2. **集成测试**
   - 测试多个搜索并行执行
   - 测试超时处理
   - 测试错误恢复

3. **性能测试**
   - 对比顺序执行和并行执行的时间
