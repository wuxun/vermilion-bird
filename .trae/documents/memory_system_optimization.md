# 记忆系统优化计划

## 目标

1. 短期记忆直接写入，不每次调用 LLM 提取
2. 积累一定对话次数或时间间隔后，再从会话历史提取到中期记忆
3. 从中期记忆整理到长期记忆
4. 统一短期记忆在 SQLite 和 Markdown 的存储

## 当前架构分析

### 现有组件

* `MemoryStorage`: Markdown 文件存储（短期/中期/长期/soul）

* `MemoryExtractor`: 使用 LLM 或规则提取记忆

* `MemoryManager`: 核心管理器，协调记忆提取和存储

* `Storage`: SQLite 存储对话历史

### 现有问题

1. 每次对话都调用 `process_pending_extractions` → 调用 LLM 提取，成本高
2. 短期记忆只在 Markdown 中，SQLite 没有对应记录
3. 没有对话计数/时间间隔触发机制

## 实现步骤

### 步骤 1: 修改短期记忆写入逻辑

**文件**: `src/llm_chat/memory/manager.py`

修改 `process_pending_extractions` 方法：

* 短期记忆直接追加到 Markdown，不调用 LLM

* 只记录用户消息和助手响应的摘要

```python
def process_pending_extractions(self):
    """处理待提取的记忆 - 短期记忆直接写入"""
    with self._extraction_lock:
        if not self._pending_extractions:
            return
        
        messages = self._pending_extractions.copy()
        self._pending_extractions.clear()
    
    # 短期记忆直接写入，不调用 LLM
    self._write_short_term_directly(messages)
    
    # 增加对话计数
    self._increment_conversation_count()
    
    # 检查是否需要提取中期记忆
    if self._should_extract_mid_term():
        self._extract_to_mid_term()
```

### 步骤 2: 添加对话计数和时间间隔机制

**文件**: `src/llm_chat/memory/manager.py`

添加新属性和方法：

```python
def __init__(self, ...):
    # 新增属性
    self._conversation_count = 0
    self._last_extraction_time = datetime.now()
    self._extraction_interval = self.config.get("extraction_interval", 10)  # 对话次数
    self._extraction_time_interval = self.config.get("extraction_time_interval", 3600)  # 秒

def _increment_conversation_count(self):
    """增加对话计数"""
    self._conversation_count += 1

def _should_extract_mid_term(self) -> bool:
    """判断是否需要提取中期记忆"""
    # 按对话次数
    if self._conversation_count >= self._extraction_interval:
        return True
    
    # 按时间间隔
    elapsed = (datetime.now() - self._last_extraction_time).total_seconds()
    if elapsed >= self._extraction_time_interval:
        return True
    
    return False

def _extract_to_mid_term(self):
    """从短期记忆提取到中期记忆"""
    # 重置计数器
    self._conversation_count = 0
    self._last_extraction_time = datetime.now()
    
    # 从 SQLite 加载历史对话
    messages = self.load_recent_conversations(days=1)
    
    # 使用 LLM 提取中期记忆
    if messages and self.llm_client:
        summary = self.extractor.summarize_day(messages)
        if summary:
            self.consolidate_to_mid_term(summary)
```

### 步骤 3: 统一 SQLite 和 Markdown 的短期记忆

**文件**: `src/llm_chat/memory/manager.py`

修改短期记忆写入：

```python
def _write_short_term_directly(self, messages: List[Dict]):
    """直接写入短期记忆，不调用 LLM"""
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        
        if role == "user":
            # 记录用户意图
            self._append_short_term_entry("用户", content[:200])
        elif role == "assistant":
            # 记录助手响应摘要
            self._append_short_term_entry("助手", content[:200])

def _append_short_term_entry(self, role: str, content: str):
    """追加短期记忆条目"""
    current = self.storage.load_short_term()
    timestamp = datetime.now().strftime("%H:%M")
    
    entry = f"\n- [{timestamp}] {role}: {content}"
    
    # 更新 Markdown
    updated = self._update_section(current, "## 最近对话", entry)
    self.storage.save_short_term(updated)
```

### 步骤 4: 添加配置项

**文件**: `src/llm_chat/config.py`

在 `MemoryConfig` 中添加：

```python
class MemoryConfig(BaseSettings):
    # 现有配置...
    
    # 新增配置
    extraction_interval: int = Field(default=10, description="多少次对话后提取中期记忆")
    extraction_time_interval: int = Field(default=3600, description="多少秒后提取中期记忆（默认1小时）")
    short_term_max_entries: int = Field(default=50, description="短期记忆最大条目数")
```

### 步骤 5: 修改 GUI 调用

**文件**: `src/llm_chat/frontends/gui.py`

修改 `_extract_memory_async` 方法：

```python
def _extract_memory_async(self, assistant_response: str):
    """异步处理记忆 - 短期记忆直接写入"""
    if len(self._messages) < 2:
        return
    
    user_message = None
    for msg in reversed(self._messages[:-1]):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break
    
    if not user_message:
        return
    
    def process_memory():
        try:
            from llm_chat.config import Config
            from llm_chat.memory import MemoryStorage, MemoryManager
            from llm_chat.client import LLMClient
            
            config = Config.from_yaml()
            if not config.memory.enabled:
                return
            
            memory_storage = MemoryStorage(config.memory.storage_dir)
            client = LLMClient(config)
            
            memory_manager = MemoryManager(
                storage=memory_storage,
                db_storage=None,
                llm_client=client,
                config={
                    "extraction_interval": config.memory.extraction_interval,
                    "extraction_time_interval": config.memory.extraction_time_interval
                }
            )
            
            messages = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_response}
            ]
            
            # 短期记忆直接写入，中期记忆按需提取
            memory_manager.schedule_extraction(messages)
            memory_manager.process_pending_extractions()
            
            logger.info("记忆处理完成")
        except Exception as e:
            logger.warning(f"记忆处理失败: {e}")
    
    import threading
    thread = threading.Thread(target=process_memory, daemon=True)
    thread.start()
```

### 步骤 6: 添加中期到长期的定期整理

**文件**: `src/llm_chat/memory/manager.py`

```python
def consolidate_mid_to_long_term(self):
    """从中期记忆整理到长期记忆"""
    mid_term = self.storage.load_mid_term()
    
    # 提取重要事实和用户偏好
    if self.llm_client:
        facts = self.extractor.extract_long_term_facts(mid_term)
        if facts:
            self.consolidate_to_long_term(facts, is_user_told=False)
    
    logger.info("中期记忆已整理到长期记忆")
```

## 文件修改清单

1. `src/llm_chat/memory/manager.py` - 核心修改

   * 添加对话计数和时间间隔机制

   * 修改 `process_pending_extractions` 短期记忆直接写入

   * 添加 `_should_extract_mid_term` 和 `_extract_to_mid_term` 方法

2. `src/llm_chat/config.py` - 添加配置项

   * `extraction_interval`

   * `extraction_time_interval`

   * `short_term_max_entries`

3. `src/llm_chat/frontends/gui.py` - 修改调用方式

   * 更新 `_extract_memory_async` 方法

4. `src/llm_chat/memory/extractor.py` - 添加新方法

   * `extract_long_term_facts` 方法

## 测试计划

1. 测试短期记忆直接写入
2. 测试对话计数触发中期记忆提取
3. 测试时间间隔触发中期记忆提取
4. 测试中期到长期的整理

