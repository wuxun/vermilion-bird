# 记忆系统 (Memory System)

> 最后更新: 2026-05-02 (P0/P1 修复后)

## 概述

多层记忆系统，支持短期/中期/长期记忆和人格设定 (soul)，通过 LLM 从对话中自动提取和进化记忆，使 AI 更懂用户。

**核心层次**: soul (人格) → long_term (持久知识) → mid_term (周期总结) → short_term (当前上下文)

## 结构

```
memory/
├── __init__.py       # 公共导出
├── storage.py        # MemoryStorage — Markdown 文件 I/O
├── manager.py        # MemoryManager — 核心编排器 (单例)
├── extractor.py      # MemoryExtractor — LLM/规则提取
└── templates.py      # 记忆文件初始模板
```

## 架构与数据流

```
                     ┌──────────────────────────────┐
                     │      ConversationManager      │
                     │   (创建并持有唯一 MemoryManager) │
                     └──────────────┬───────────────┘
                                    │ 注入到每个 Conversation
         ┌──────────────────────────┼──────────────────────────┐
         ▼                          ▼                          ▼
   Conversation A           Conversation B           Conversation C
         │                          │                          │
         │ send_message()            │                          │
         ├─ schedule_extraction()    │                          │
         ├─ process_pending_extractions()                       │
         │  ├─ _write_short_term_directly()    ← 对话日志写入   │
         │  ├─ _should_extract_mid_term()      ← 按轮次/时间    │
         │  ├─ _maybe_compress_mid_term()      ← 自动去旧       │
         │  └─ _maybe_evolve_understanding()   ← 自动进化       │
         └─ build_system_prompt()              ← token 预算注入  │
```

### 模块职责

| 模块 | 文件 | 行数 | 职责 |
|------|------|------|------|
| **MemoryStorage** | `storage.py` | ~230 | Markdown 文件 CRUD、搜索、备份恢复 |
| **MemoryManager** | `manager.py` | ~430 | 核心编排：调度→写入→提取→压缩→进化→prompt注入 |
| **MemoryExtractor** | `extractor.py` | ~330 | LLM 提示工程、规则提取、敏感信息过滤、JSON 解析 |
| **Templates** | `templates.py` | ~120 | 四层记忆文件的初始模板 |

## 各层记忆详解

### soul.md — 人格设定

- **内容**: 核心特质、行为准则、沟通风格、专业能力、工具使用指南
- **写入**: 初始化模板 + `update_soul()` / `update_soul_section()` 手动更新
- **读取**: `build_system_prompt()` 最高优先级注入，不截断
- **格式**: 3 段提取 (核心特质 / 行为准则 / 沟通风格)

### short_term.md — 短期记忆

- **内容**: 最近对话日志 (带时间戳) + 当前任务 + 待办事项
- **写入**: `_write_short_term_directly()` 每轮对话写入 (截取前 200 字)
- **修剪**: `_trim_short_term_entries()` 保持 `short_term_max_entries` 条上限
- **读取**: `build_system_prompt()` 最低优先级注入 (当前任务段)
- **⚠️ 注意**: 对话日志与 SQLite 冗余，职责偏重日志而非语义摘要

### mid_term.md — 中期记忆

- **内容**: 每日摘要 (按日期)、重要事件时间线、活跃话题
- **写入**: `_extract_to_mid_term()` LLM 生成每日摘要 → `append_summary()`
- **触发**: 每 N 轮对话 或 每 M 秒 (配置 `extraction_interval` / `extraction_time_interval`)
- **压缩**: `compress_mid_term()` 删除 `max_days` 天前的摘要，按 `compress_after_days` 周期自动触发
- **读取**: `build_system_prompt()` 提取最近 3 天摘要

### long_term.md — 长期记忆

- **内容**: 用户画像 (基本信息/沟通偏好/技能偏好)、重要事实 (主动告知/系统推断)、进化日志
- **写入**: 
  - `consolidate_to_long_term()` 用户告知或系统推断的事实
  - `consolidate_mid_to_long_term()` 从中期记忆 LLM 提取 → 手动触发
- **进化**: `evolve_understanding()` 从最近 7 天对话检测偏好，按 `evolve_interval_days` 周期自动触发
- **读取**: `build_system_prompt()` 第二优先级注入 (用户画像 + 重要事实)

## MemoryManager API (完整)

```python
class MemoryManager:
    def __init__(storage, db_storage, llm_client, config)

    # ── 提取与整理 ──────────────────────────
    extract_memories_from_messages(messages) -> Dict
    consolidate_to_short_term(info: Dict)            # LLM 提取 → 短期
    consolidate_to_mid_term(summary, date?)          # 摘要 → 中期
    consolidate_to_long_term(facts, is_user_told?)   # 事实 → 长期
    consolidate_mid_to_long_term()                   # 中期 → 长期

    # ── 调度与处理 ──────────────────────────
    schedule_extraction(messages)                    # 入队
    process_pending_extractions()                    # 出队并处理 (含周期维护)
    archive_session(session_id)                      # 归档到中期

    # ── 记忆生命周期 ────────────────────────
    compress_mid_term(max_days=30)                   # 压缩过期中期记忆
    evolve_understanding()                           # 进化长期理解

    # ── 人格管理 ────────────────────────────
    get_soul() -> str
    update_soul(content)
    update_soul_section(section, content)

    # ── 系统提示生成 ────────────────────────
    build_system_prompt() -> str                     # token 预算控制

    # ── 工具 ────────────────────────────────
    search_memories(query) -> List[Dict]
    get_memory_stats() -> Dict
    clear_all_memories()
    export_memories() -> Dict
    import_memories(data: Dict)
    load_recent_conversations(days=7) -> List[Dict]
```

## MemoryExtractor API

```python
class MemoryExtractor:
    def __init__(llm_client)

    extract(messages) -> Dict          # 提取记忆 (LLM / 规则)
    summarize_day(messages) -> str     # 生成每日摘要
    detect_user_preferences(messages) -> Dict  # 检测偏好
    extract_long_term_facts(mid_term_content) -> List[str]  # 提取长期事实

    calculate_importance(info) -> float    # 0.0~1.0
    should_remember(info, threshold=0.3) -> bool

    # Static
    _parse_llm_json(response) -> Dict  # 容错 JSON 解析 (处理 ```json 包裹)
```

## MemoryStorage API

```python
class MemoryStorage:
    def __init__(memory_dir="~/.vermilion-bird/memory")

    # 短期记忆
    load_short_term() -> str
    save_short_term(content)
    clear_short_term()

    # 中期记忆
    load_mid_term() -> str
    save_mid_term(content)
    append_summary(date, summary)
    append_timeline_event(date, event)

    # 长期记忆
    load_long_term() -> str
    save_long_term(content)
    update_section(section, content) -> bool       # regex 更新 H3 章节
    add_user_fact(fact)
    add_inferred_fact(fact)
    add_evolution_log(date, log)
    update_timestamp(memory_type="all")

    # 人格
    load_soul() -> Optional[str]
    save_soul(content)

    # 工具
    backup_memory(backup_dir?) -> str
    restore_memory(backup_path)
    search_memories(query) -> List[Dict]
    get_memory_stats() -> Dict
```

## 配置体系

### Pydantic 模型 (config.py)

```python
MemoryConfig:
  enabled: bool = True
  storage_dir: str = "~/.vermilion-bird/memory"
  max_memory_tokens: int = 2000               # token 预算上限
  extraction_interval: int = 10               # N 次对话后触发中期提取
  extraction_time_interval: int = 3600        # 或 N 秒后触发
  short_term_max_entries: int = 50            # 短期记忆最大条目
  exclude_patterns: List[str]                 # 敏感词过滤
  short_term: ShortTermMemoryConfig:
    max_items: int = 10
  mid_term: MidTermMemoryConfig:
    max_days: int = 30                        # 保留天数
    compress_after_days: int = 7              # 压缩周期
  long_term: LongTermMemoryConfig:
    auto_evolve: bool = True                  # 自动进化
    evolve_interval_days: int = 7             # 进化周期
```

### config.yaml 示例

```yaml
memory:
  enabled: true
  storage_dir: "~/.vermilion-bird/memory"
  max_memory_tokens: 2000
  extraction_interval: 10
  extraction_time_interval: 3600
  short_term_max_entries: 50
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
```

### 配置传递链

```
config.yaml / env vars
    ↓
MemoryConfig (Pydantic)        ← config.py
    ↓ _parse_memory()
Config.memory                   ← 内置字段全部传递
    ↓ _build_memory_config()
memory_config dict              ← app.py, 传递给 MemoryManager
    ↓ MemoryManager.__init__()
self._extraction_interval etc   ← manager.py, 读取并应用
```

## 已修复问题 (P0 & P1)

| 编号 | 问题 | 修复 |
|------|------|------|
| P0-1 | 配置字段断联 | `_parse_memory()` / `_build_memory_config()` 补传 3 个字段 |
| P0-2 | MemoryManager 多实例竞态 | 提升为 ConversationManager 单例，注入到每个 Conversation |
| P1-1 | 中期/长期自动触发链路断裂 | `process_pending_extractions()` 追加 `_maybe_compress_mid_term()` + `_maybe_evolve_understanding()` |
| P1-2 | build_system_prompt() 无 token 预算 | `_estimate_tokens()` + `_truncate_by_tokens()` + 优先级截断 |
| P1-3 | JSON 解析无容错 | `_parse_llm_json()` 处理 `` ```json ... ``` `` 包裹 |

## 待优化项 (P2-P4)

| 编号 | 优先级 | 问题 | 位置 | 建议 |
|------|--------|------|------|------|
| P2-4 | 中 | 同步调用伪装成异步 | `conversation.py:_extract_memory_async()` | schedule + immediate process 无意义，简化为直接调用 |
| P2-5 | 中 | 短期记忆职责混乱 | `manager.py`, `short_term.md` | 对话日志与语义摘要混存；短期应只保留语义摘要，对话日志仅存 SQLite |
| P2-6 | 中 | 敏感信息过滤过于激进 | `extractor.py:extract()` | 脱敏后继续提取，而非整轮丢弃 |
| P3-7 | 低 | 3 套不一致的 section regex | `storage.py`, `manager.py` (×2) | 抽取公共 `_parse_markdown_sections()` |
| P3-8 | 低 | 无原子写入保护 | `storage.py` | temp file + rename 模式 |
| P4-9 | 低 | 规则提取正则过于简单 | `extractor.py:_extract_with_rules()` | `(正在|开始).{0,20}(任务|项目)` 只匹配 20 字 |
| P4-10 | 低 | 零测试覆盖 | `tests/` | 无 `test_memory*` 文件 |
