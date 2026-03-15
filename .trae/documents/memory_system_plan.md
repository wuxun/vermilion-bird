# 记忆系统实现计划

## 一、需求概述

实现类似OpenClaw的多层记忆系统，让AI助手能够：

* 短期记忆：当前会话上下文和任务状态

* 中期记忆：近期对话摘要和重要事件

* 长期记忆：用户偏好、习惯、重要信息

## 二、系统架构设计

### 2.1 记忆存储结构（Markdown格式）

```
~/.vermilion-bird/memory/
├── short_term.md        # 短期记忆（当前任务状态）
├── mid_term.md          # 中期记忆（近期摘要）
├── long_term.md         # 长期记忆（用户画像）
└── soul.md              # 人格设定（可选）
```

### 2.2 复用现有SQLite存储

会话历史已存储在 `~/.vermilion-bird/conversations.db` 中，无需重复创建。记忆系统将：

* 从SQLite读取历史对话进行分析

* 提取有价值的信息存储到Markdown文件

* 定期从SQLite归档旧会话

### 2.3 记忆文件格式设计

#### short\_term.md（短期记忆）

```markdown
# 短期记忆

## 当前任务
- 正在进行的工作：xxx
- 任务状态：进行中/等待/完成

## 最近上下文
- 关键信息1
- 关键信息2

## 待处理事项
- [ ] 待办1
- [x] 已完成

---
更新时间：2024-03-16 10:30
```

#### mid\_term.md（中期记忆）

```markdown
# 中期记忆

## 近期摘要

### 2024-03-16
- 完成了xxx功能开发
- 讨论了xxx技术方案

### 2024-03-15
- 修复了xxx问题
- 学习了xxx知识

## 重要事件时间线
- 2024-03-16: 项目架构重构
- 2024-03-10: 开始使用Vermilion Bird

## 活跃话题
- Python开发
- AI助手
- GUI界面

---
更新时间：2024-03-16 10:30
```

#### long\_term.md（长期记忆）

```markdown
# 长期记忆

## 用户画像

### 基本信息
- 偏好语言：中文
- 编程语言：Python
- 工作领域：软件开发

### 沟通偏好
- 回复风格：简洁/详细
- 代码风格：高内聚低耦合
- 日志习惯：关键位置打印日志

### 技能偏好
- 常用工具：web_search, calculator
- 常用框架：PyQt6, Pydantic

## 重要事实

### 用户主动告知
- 代码设计要合理，高内聚，低耦合，易扩展
- 代码在关键位置要打印日志

### 系统推断
- 用户偏好中文交互
- 用户是Python开发者

## 进化日志

### 2024-03-16
- 发现用户偏好Markdown格式存储
- 更新了记忆存储策略

---
创建时间：2024-03-10
更新时间：2024-03-16
```

## 三、核心模块设计

### 3.1 目录结构

```
src/llm_chat/memory/
├── __init__.py
├── models.py          # 数据模型
├── storage.py         # Markdown存储管理
├── manager.py         # 记忆管理器
├── extractor.py       # 记忆提取器
└── templates.py       # Markdown模板
```

### 3.2 存储模块 (memory/storage.py)

```python
class MemoryStorage:
    """Markdown格式记忆存储"""
    
    def __init__(self, memory_dir: str = "~/.vermilion-bird/memory"):
        self.memory_dir = Path(memory_dir).expanduser()
        self.memory_dir.mkdir(parents=True, exist_ok=True)
    
    # 短期记忆
    def load_short_term() -> str
    def save_short_term(content: str)
    def clear_short_term()
    
    # 中期记忆
    def load_mid_term() -> str
    def save_mid_term(content: str)
    def append_summary(date: str, summary: str)
    
    # 长期记忆
    def load_long_term() -> str
    def save_long_term(content: str)
    def update_section(section: str, content: str)
    
    # 通用
    def backup_memory()  # 备份记忆文件
    def restore_memory(backup_path: str)
```

### 3.3 记忆管理器 (memory/manager.py)

```python
class MemoryManager:
    """记忆系统核心管理器"""
    
    def __init__(self, storage: MemoryStorage, db_storage: Storage, llm_client: LLMClient)
    
    # 从SQLite读取历史
    def load_recent_conversations(days: int = 7) -> List[Dict]
    
    # 记忆提取（使用LLM）
    def extract_memories_from_messages(messages: List[Dict]) -> Dict
    
    # 记忆整合
    def consolidate_to_short_term(info: Dict)
    def consolidate_to_mid_term(summary: str)
    def consolidate_to_long_term(fact: Dict)
    
    # 记忆检索
    def search_memories(query: str) -> List[str]
    
    # 记忆压缩（定期执行）
    def compress_mid_term()
    
    # 记忆进化
    def evolve_understanding()
    
    # 构建系统提示
    def build_system_prompt() -> str
```

### 3.4 记忆提取器 (memory/extractor.py)

```python
class MemoryExtractor:
    """使用LLM从对话中提取记忆"""
    
    EXTRACTION_PROMPT = """
分析以下对话，提取值得记忆的信息：

对话内容：
{conversation}

请提取：
1. 用户偏好（语言风格、回复格式等）
2. 重要事实（用户主动告知的信息）
3. 当前任务状态
4. 值得记住的事件

以Markdown格式输出，不要包含敏感信息（密码、token等）。
"""

    def extract(messages: List[Dict]) -> Dict
    def summarize_day(messages: List[Dict]) -> str
    def detect_user_preferences(messages: List[Dict]) -> Dict
```

## 四、与现有系统集成

### 4.1 修改 Conversation 类

```python
class Conversation:
    def __init__(self, client, conversation_id, storage):
        # ... 现有代码 ...
        self.memory_manager = MemoryManager(
            storage=MemoryStorage(),
            db_storage=storage,
            llm_client=client
        )
    
    def send_message(self, message: str) -> str:
        # 1. 获取记忆上下文
        memory_context = self.memory_manager.build_system_prompt()
        
        # 2. 发送消息（带记忆上下文）
        response = self.client.chat(
            message, 
            history=self.get_history(),
            system_context=memory_context
        )
        
        # 3. 异步提取记忆（不阻塞响应）
        self._schedule_memory_extraction(message, response)
        
        return response
    
    def end_session(self):
        """会话结束时调用"""
        # 归档短期记忆到中期记忆
        self.memory_manager.archive_session()
```

### 4.2 修改 LLMClient

```python
class LLMClient:
    def chat(self, message: str, history: List, system_context: str = None):
        # 构建系统消息
        system_message = self._build_system_message(system_context)
        # ... 现有逻辑 ...
```

### 4.3 配置扩展

```yaml
memory:
  enabled: true
  storage_dir: "~/.vermilion-bird/memory"
  
  short_term:
    max_items: 10
  
  mid_term:
    max_days: 30
    compress_after_days: 7
  
  long_term:
    auto_evolve: true
    evolve_interval_days: 7
  
  privacy:
    exclude_patterns:
      - "密码"
      - "password"
      - "token"
      - "api_key"
      - "secret"
```

## 五、实现步骤

### 阶段一：基础架构（第1天）

1. 创建 `src/llm_chat/memory/` 模块
2. 实现 Markdown 存储层 `storage.py`
3. 定义数据模型和模板

### 阶段二：核心功能（第2-3天）

1. 实现记忆管理器 `manager.py`
2. 实现记忆提取器 `extractor.py`
3. 集成SQLite读取历史对话

### 阶段三：系统集成（第4天）

1. 修改 `Conversation` 类
2. 修改 `LLMClient` 支持系统上下文
3. 添加配置支持

### 阶段四：进化功能（第5天）

1. 实现记忆进化机制
2. 实现定期压缩
3. 添加记忆可视化（CLI命令）

### 阶段五：测试与优化（第6天）

1. 单元测试
2. 性能优化
3. 文档完善

## 六、关键技术点

### 6.1 Markdown解析与更新

* 使用正则表达式定位章节

* 保留格式的同时更新内容

* 支持增量更新

### 6.2 记忆提取策略

* 使用LLM分析对话内容

* 过滤敏感信息

* 重要性评分

### 6.3 记忆检索

* 简单关键词匹配（初期）

* 可选：后续集成向量检索

### 6.4 隐私保护

* 敏感词正则过滤

* 本地存储

* 用户可编辑Markdown文件

## 七、与OpenClaw对比

| 特性   | OpenClaw | 本方案         |
| ---- | -------- | ----------- |
| 存储格式 | Markdown | Markdown    |
| 会话存储 | 独立目录     | 复用SQLite    |
| 记忆层次 | 短期/长期    | 短期/中期/长期    |
| 进化机制 | 有        | 有           |
| 人格设定 | soul.md  | soul.md（可选） |

## 八、预期效果

1. **即时效果**：AI能记住当前会话的关键信息
2. **短期效果**：AI能回顾近期对话，保持上下文连贯
3. **长期效果**：AI逐渐了解用户偏好，提供个性化服务
4. **进化效果**：AI能主动学习和适应用户习惯

