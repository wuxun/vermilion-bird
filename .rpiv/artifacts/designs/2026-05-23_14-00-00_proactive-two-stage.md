---
date: 2026-05-23T14:00:00+0800
author: wuxun
commit: 2674231
branch: main
repository: vermilion-bird
topic: "ProactiveAgent 两阶段拆分：新闻精选 + 讨论话题"
confidence: high
complexity: medium
status: ready
tags: [design, proactive-agent, rss, feedparser, two-stage]
last_updated: 2026-05-23T14:00:00+0800
last_updated_by: wuxun
---

# Design: ProactiveAgent 两阶段管线

**Date**: 2026-05-23T14:00:00+0800
**Author**: wuxun
**Commit**: 2674231
**Branch**: main
**Repository**: vermilion-bird
**Input**: `thoughts/shared/solutions/2026-05-23_13-48-08_info-aggregation-pipeline.md`

## Architecture Decisions

### AD1: Two cron jobs, one Agent class

ProactiveAgent 保持一个类，但通过 `mode` 参数区分行为。Scheduler 注册两个 cron job：

| Job | Cron | Mode | 输出 |
|-----|------|------|------|
| `proactive-digest` | 8:00 daily | `news_digest` | 纯文本摘要 → 飞书/GUI |
| `proactive-discuss` | 9:00 daily | `discussion` | DecisionCard → 飞书/GUI |

**Rationale**: 两个独立的 cron job 允许未来独立调整频率（比如新闻两小时一次，讨论仍每天一次），但共享同一个 Agent 实例避免代码重复。

### AD2: SQLite `daily_digest` table for cross-stage state

8:00 的新闻精选结果写入 `daily_digest` 表，9:00 的讨论阶段读取。不依赖内存或文件——避免进程重启丢数据。

**Rationale**: 遵循现有 `StorageMixin` 模式。SQLite 已在项目中作为主存储，零新依赖。

### AD3: LLM 驱动的精选（非规则驱动）

新闻精选由 LLM 完成（调用一次 `chat()`），而非规则/关键词过滤。LLM 读数 10 条 RSS 条目 → 输出 5-8 条精选。

**Rationale**: RSS 条目的价值判断需要语义理解。"arXiv 这篇论文跟用户的 Go 项目有关"是 LLM 才能做的。规则无法替代。

### AD4: Discussion 阶段可 fallback 到独立选题

如果 8:00 采集失败（网络问题、API 故障），`daily_digest` 为空。9:00 仍能基于用户记忆生成话题卡片，而不是直接跳过。

**Rationale**: 避免单点故障导致一整天无推送。与当前 fallback 行为一致（无资讯时仅用记忆）。

### AD5: feedparser 作为 P0 信息源，与 DDGS 并行

`_collect_info()` 同时调用 `_fetch_rss()` (feedparser) 和 `_search()` (DDGS)，合并去重后传给 LLM。

**Rationale**: RSS 提供确定性内容（用户订阅的源），DDGS 提供广度（发现新东西）。两者互补。

---

## Slice Breakdown

### Slice 1: feedparser 集成 + RSS 配置
文件: `pyproject.toml`, `scheduler_config.py`, `agent.py` (部分)

- [ ] `poetry add feedparser`
- [ ] `SchedulerConfig` 新增 `proactive_rss_feeds: list[str] = []`
- [ ] `agent.py` 新增 `_fetch_rss()` 方法 (~25 lines)
- [ ] `_build_context()` 中调用 `_fetch_rss()`，结果并入 `web_news`

**验证**: 手动触发 `vermilion-bird schedule proactive`，确认 RSS 内容出现在卡片中

### Slice 2: daily_digest 存储层
文件: `storage/_digest.py` (新), `storage/_core.py`, `storage/__init__.py`

- [ ] 创建 `StorageDigestMixin`，包含 `save_digest()`, `get_today_digest()`
- [ ] `_core.py._init_db()` 注册 `_create_digest_tables_in()`
- [ ] `__init__.py` 增加 mixin 继承

**验证**: 单元测试 CRUD 操作

### Slice 3: ProactiveAgent 重构 — mode 参数
文件: `agent.py` (核心重构), `prompts.py` (新), `scheduler.py`, `app.py`

- [ ] 新增 `proactive/prompts.py` — `NEWS_CURATOR_PROMPT` + 修改后的 `DISCUSSION_PROMPT`
- [ ] `__init__` 接受 `mode` 参数，默认 `"discussion"` 保持向后兼容
- [ ] `generate_and_push()` 根据 `mode` 分发到 `_run_news_digest()` 或 `_run_discussion()`
- [ ] `_run_news_digest()`: 采集 → LLM 精选 → 存 SQLite → 推送文本
- [ ] `_run_discussion()`: 读 digest → (可选) 重采集 → LLM 选题 → 推送卡片
- [ ] `scheduler.py._run_proactive_chat_task()` 接受 mode 参数
- [ ] `app.py._register_proactive_chat_task()` 注册两个 cron job

**验证**: 
- 手动触发 news_digest mode，确认有文本推送且 SQLite 有记录
- 手动触发 discussion mode，确认卡片内容引用了 digest

### Slice 4: LLM 精选 prompt 调优
文件: `prompts.py`

- [ ] 编写 `NEWS_CURATOR_PROMPT`：要求 LLM 从 10-30 条资讯中选 5-8 条
- [ ] 修改 `DISCUSSION_PROMPT`：增加"优先从今日精选中选择话题"的指令
- [ ] 确保两个 prompt 的 `max_tokens`/`temperature` 差异化（精选用低温度 0.4，讨论用 0.8）

**验证**: 检查精选输出是否包含来源 URL、是否去重、是否按重要性排序

---

## File Map

```
新增:
  src/llm_chat/proactive/prompts.py          (~80 lines)  Prompt 模板
  src/llm_chat/storage/_digest.py            (~60 lines)  DailyDigest CRUD

修改:
  pyproject.toml                             (+1 line)    feedparser 依赖
  src/llm_chat/config/scheduler_config.py    (+4 lines)   rss_feeds + 两时间配置
  src/llm_chat/storage/_core.py              (+1 line)    注册 digest 建表
  src/llm_chat/storage/__init__.py           (+1 line)    mixin 继承
  src/llm_chat/proactive/agent.py            (~120 lines) 核心重构
  src/llm_chat/scheduler/scheduler.py        (~15 lines)  mode 参数传递
  src/llm_chat/app.py                        (~30 lines)  两个 proactive cron job
  config.example.yaml                        (~10 lines)  配置示例
```

---

## Key Data Structures

### `daily_digest` 表

```sql
CREATE TABLE IF NOT EXISTS daily_digest (
    id TEXT PRIMARY KEY,               -- UUID
    date TEXT UNIQUE NOT NULL,         -- "2026-05-23"
    items_json TEXT NOT NULL,          -- JSON: [DigestItem, ...]
    raw_context_json TEXT,             -- 原始采集数据（讨论阶段 fallback 用）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### `DigestItem` (not a DB model, JSON inside `items_json`)

```python
{
    "rank": 1,                         # LLM 排序 (1 = 最重要)
    "title": "GPT-5 论文泄露",
    "source": "Hacker News",
    "source_url": "https://...",
    "summary": "OpenAI 内部文件显示...",   # LLM 生成摘要 (≤ 80 chars)
    "relevance": "与用户的 AI 项目直接相关",  # LLM 解释为什么选这条
}
```

### `generate_and_push(mode)` 分发

```python
def generate_and_push(self, mode: str = "discussion"):
    if mode == "news_digest":
        self._run_news_digest()
    elif mode == "discussion":
        self._run_discussion()
```

### `_run_news_digest()` 流程

```
1. _collect_info()        → ctx (RSS + DDGS 合并)
2. _curate_news(ctx)      → LLM 精选 → list[DigestItem]
3. _save_digest(items)    → SQLite daily_digest
4. _format_digest(items)  → 纯文本 "📰 今日精选 · 5月23日\n\n1. ..."
5. _push_text(text)       → 飞书/GUI
```

### `_run_discussion()` 流程

```
1. digest = _load_today_digest()
2. If digest:
     ctx = digest.raw_context_json + memory context
   Else:
     ctx = _collect_info()           # fallback: 重新采集
3. card = _generate_card(ctx)       # LLM 调用 submit_decision_card
4. _push_card(card)                 # 飞书/GUI
```

---

## Validation Criteria (per slice)

| Slice | 通过条件 |
|-------|----------|
| 1 | `poetry add feedparser` 成功；手动触发后 RSS 条目出现在卡片 context 中 |
| 2 | `test_digest_crud.py` 通过；`save_digest()` + `get_today_digest()` 往返正确 |
| 3 | `--mode news_digest` 输出文本摘要；`--mode discussion` 输出决策卡片 |
| 4 | 精选输出包含 5-8 条、有来源 URL、按重要性排序；讨论卡片引用精选内容 |
