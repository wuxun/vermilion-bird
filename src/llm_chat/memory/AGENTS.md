# 记忆系统

## 概述

多层记忆系统，支持短期/中期/长期记忆和人格设定，让 AI 更懂用户。

## 结构

```
memory/
├── __init__.py       # 公共导出
├── storage.py        # MemoryStorage 持久化
├── manager.py        # 记忆管理器
├── extractor.py      # 记忆提取器
└── templates.py      # 记忆模板
```

## 快速定位

| 任务 | 文件 | 说明 |
|------|------|------|
| 读取/写入记忆 | `storage.py` | MemoryStorage |
| 记忆提取逻辑 | `extractor.py` | 从对话提取记忆 |
| 记忆模板 | `templates.py` | 默认人格/格式 |

## 记忆层次

| 层次 | 文件 | 内容 | 用途 |
|------|------|------|------|
| 短期 | `short_term.md` | 当前任务/待办 | 临时上下文 |
| 中期 | `mid_term.md` | 近期摘要/时间线 | 周期总结 |
| 长期 | `long_term.md` | 用户画像/重要事实 | 持久知识 |
| 人格 | `soul.md` | AI 性格/行为准则 | 角色设定 |

## MemoryStorage API

```python
class MemoryStorage:
    def __init__(self, memory_dir: str = "~/.vermilion-bird/memory")
    
    # 短期记忆
    def load_short_term(self) -> str
    def save_short_term(self, content: str)
    def clear_short_term(self)
    
    # 中期记忆
    def load_mid_term(self) -> str
    def save_mid_term(self, content: str)
    def append_summary(self, date: str, summary: str)
    def append_timeline_event(self, date: str, event: str)
    
    # 长期记忆
    def load_long_term(self) -> str
    def save_long_term(self, content: str)
    def update_section(self, section: str, content: str)
    def add_user_fact(self, fact: str)
    def add_inferred_fact(self, fact: str)
    def add_evolution_log(self, date: str, log: str)
    
    # 人格设定
    def load_soul(self) -> str
    def save_soul(self, content: str)
    
    # 工具方法
    def backup_memory(self) -> str
    def restore_memory(self, backup_path: str)
    def search_memories(self, query: str) -> Dict[str, List[str]]
    def get_memory_stats(self) -> Dict[str, Any]
```

## CLI 命令

```bash
# 查看记忆状态
vermilion-bird memory status

# 查看人格设定
vermilion-bird memory soul

# 查看各层记忆
vermilion-bird memory short-term
vermilion-bird memory mid-term
vermilion-bird memory long-term

# 备份记忆
vermilion-bird memory backup

# 清空记忆（危险操作）
vermilion-bird memory clear
```

## 配置

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
  exclude_patterns:
    - "密码"
    - "password"
    - "token"
    - "api_key"
  extraction_interval: 10        # 每 N 次对话提取
  extraction_time_interval: 3600 # 或每 N 秒提取
  short_term_max_entries: 50
```

## 记忆文件格式

### short_term.md
```markdown
# 短期记忆

- 当前任务：...
- 待办事项：...
```

### mid_term.md
```markdown
# 中期记忆

## 摘要
- 2024-01-15: ...

## 时间线
- 2024-01-15: 发生了...
```

### long_term.md
```markdown
# 长期记忆

## 用户画像
- ...

## 重要事实
- ...

## 推断信息
- ...

## 进化日志
- 2024-01-15: ...
```

### soul.md
```markdown
# 人格设定

## 核心特质
...

## 行为准则
...

## 沟通风格
...

## 专业能力
...
```

## 约定

- 记忆文件使用 Markdown 格式
- 敏感信息通过 `exclude_patterns` 过滤
- 长期记忆支持自动进化（合并/压缩）

## 注意事项

- 记忆文件可直接编辑
- 清空操作不可恢复（建议先备份）
- 存储目录可通过配置修改
