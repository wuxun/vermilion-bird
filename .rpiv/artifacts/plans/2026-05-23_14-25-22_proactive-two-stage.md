---
date: 2026-05-23T14:25:22+0800
author: wuxun
commit: 2674231
branch: main
repository: vermilion-bird
topic: "ProactiveAgent 两阶段管线：新闻精选 + 讨论话题"
tags: [plan, proactive-agent, feedparser, two-stage, rss]
status: in-progress
parent: thoughts/shared/designs/2026-05-23_14-00-00_proactive-two-stage.md
phase_count: 4
unresolved_phase_count: 0
last_updated: 2026-05-23T14:30:00+0800
status: ready
last_updated_by: wuxun
---

# ProactiveAgent 两阶段管线 Implementation Plan

## Overview

将 ProactiveAgent 拆分为两个 cron job 驱动的阶段：8:00 新闻精选推送（RSS feedparser + DDGS → LLM 精选 → 纯文本摘要），9:00 讨论话题卡片（读取精选结果 + 记忆 → submit_decision_card）。一个 Agent 类，通过 `mode` 参数切换。feedparser 作为 P0 信息源与现有 DDGS 并行采集。

## Requirements

- 用户可配置 RSS 订阅源 URL 列表
- 8:00 自动采集 RSS + DDGS，LLM 精选 5-8 条，推送纯文本摘要
- 精选结果存入 SQLite `daily_digest` 表，供 9:00 讨论阶段读取
- 9:00 基于精选结果 + 用户记忆生成讨论话题卡片
- 若精选结果为空（采集失败），fallback 到独立选题（纯记忆驱动）
- 保持向后兼容：当前 `generate_and_push()` 默认 mode="discussion"

## Current State Analysis

### Key Discoveries

- ProactiveAgent 当前仅 `generate_and_push()` 一个入口，调用 `_generate_card()` 生成卡片 `proactive/agent.py:86-94`
- 信息采集在 `_fetch_web_context()` 中临时调用 DDGS 搜索 `proactive/agent.py:173-212`，无持久化
- Scheduler 注册单个 `PROACTIVE_CHAT` cron job `app.py:604-658`
- `_run_proactive_chat_task()` 直接实例化 ProactiveAgent 并调用 `generate_and_push()` `scheduler.py:565-578`
- Storage 使用 mixin 组合模式 `storage/__init__.py:18-23`，`_task.py` 提供 CRUD 模板
- Table 注册在 `_core.py._init_db()` 逐行调用 `_create_*_table_in(conn)` `storage/_core.py:79-88`
- 现有测试使用 `MagicMock` mock `App` 和 `Storage` `tests/test_scheduler/test_executor.py:14-18`
- `SchedulerConfig` 已有 `proactive_enabled/hour/minute` 字段 `config/scheduler_config.py:27-35`

### Patterns to Follow

| Pattern | Location | Use |
|---------|----------|-----|
| Storage mixin | `storage/_task.py:18-162` | Digest CRUD |
| Table creation | `storage/_core.py:91-101` | `_create_digest_tables_in(conn)` |
| Private fetch method | `proactive/agent.py:217` `_search()` | `_fetch_rss()` |
| Proactive cron registration | `app.py:604-658` | Two jobs |
| LLM chat call | `app.client.chat()` | News curation (text generation) |
| Task params passthrough | `task_executor.py:50-54` | Mode extraction |

### Constraints

- Python 3.10+, no new services
- feedparser is a pure Python library, pip-installable
- `chat()` for curation uses the same LLM client as discussion cards
- SQLite WAL mode already enabled, no migration tools needed

## Desired End State

```python
# 8:00 — 新闻精选
agent = ProactiveAgent(app, config, mode="news_digest")
agent.generate_and_push()
# → 飞书收到: "📰 今日精选 · 5月23日\n\n1. ..."
# → SQLite daily_digest 写入今日精选

# 9:00 — 讨论话题
agent = ProactiveAgent(app, config, mode="discussion")
agent.generate_and_push()
# → 从 daily_digest 读精选结果
# → 飞书收到 DecisionCard: "想聊聊这个吗？A/B/C"

# 配置
scheduler:
  proactive_enabled: true
  proactive_digest_hour: 8
  proactive_discuss_hour: 9
  proactive_rss_feeds:
    - https://hnrss.org/frontpage?count=10
    - https://feeds.feedburner.com/ruanyifeng
```

## What We're NOT Doing

- 不引入 RSSHub / Docker / MCP（保留给 P1）
- 不写社交媒体爬虫
- 不替换现有 DDGS 搜索（RSS 是增强，不是替代）
- 不提供 digest 历史浏览 UI
- 不新增 TaskType 枚举值（用 params 传 mode）

## Decisions

### D1: Mode via task.params

使用 `task.params = {"mode": "news_digest"}` 传递模式，不扩展 TaskType 枚举。

**Rationale**: `params` 已是任意 JSON dict，无需改 models/enum/dispatch 链。与 `SKILL_EXECUTION` 的 `params.arguments` 模式一致。

### D2: LLM curation via chat() + text parsing

新闻精选用 `client.chat()` 获取结构化文本，正则解析 DigestItem 列表。不新增 submit_digest 工具。

**Rationale**: 精选是简单的文本生成任务，chat() 更快、省 token。决策卡片才需要 tool-call 的结构化保证。

### D3: RSS feeds in scheduler_config

`proactive_rss_feeds` 放在 `scheduler_config.py`，与 `proactive_hour/minute` 同级。

**Rationale**: 一致性。ProactiveAgent 的所有配置集中在一处。

### D4: Two cron jobs, shared agent class

两个独立的 APScheduler cron job（8:00 + 9:00），共享 `ProactiveAgent` 类。

**Rationale**: 允许未来独立调整频率。一个类避免代码重复。mode 参数保持向后兼容。

## Ordering Constraints

- Slice 1 → Slice 2: storage needs config field from Slice 1
- Slice 2 → Slice 3: agent needs digest storage from Slice 2
- Slice 3 → Slice 4: wiring needs agent supporting mode from Slice 3

All slices are sequential — no parallelization.

## Verification Notes

- feedparser: mock `feedparser.parse()` returning `FeedParserDict` with known entries
- Digest CRUD: test save/load round-trip with today's date
- Mode dispatch: verify `news_digest` calls curation, `discussion` calls card generation
- Fallback: empty digest → discussion generates card from memory only
- Backward compat: `generate_and_push()` (no args) → behaves as `mode="discussion"`

## Performance Considerations

- RSS fetch: timeout 10s per feed, matching DDGS pattern
- LLM calls: 2/day instead of 1/day (tolerable)
- Digest storage: one row per day, negligible growth

## Migration Notes

Not applicable — greenfield within existing schema. `daily_digest` table created by `_init_db()` on first run.

## Pattern References

- `storage/_task.py:18-162` — StorageMixin CRUD pattern
- `proactive/agent.py:217-245` — _search() private fetch method pattern
- `app.py:604-658` — proactive cron job registration pattern
- `scheduler.py:565-578` — _run_proactive_chat_task() dispatch pattern
- `tests/test_scheduler/test_executor.py:14-18` — MagicMock App pattern

## Developer Context

**Design checkpoint 5:**
- Q: "新闻精选阶段，LLM 调用方式？" → A: chat() + 文本解析

## Phase 1: feedparser 集成 + RSS 采集

### Overview

添加 feedparser 依赖，新增 `_fetch_rss()` 方法，配置 RSS URL 列表字段。为 ProactiveAgent 提供第二个信息源，与 DDGS 并行采集。

Depends on: nothing (foundation).

### Changes Required:

#### 1. pyproject.toml:30

**File**: pyproject.toml
**Changes**: MODIFY — add feedparser dependency after trafilatura

```toml
feedparser = "^6.0.0"
```

#### 2. src/llm_chat/config/scheduler_config.py:35

**File**: src/llm_chat/config/scheduler_config.py
**Changes**: MODIFY — add proactive_rss_feeds field after proactive_minute

```python
    proactive_rss_feeds: list = Field(
        default=[],
        description="RSS 源 URL 列表，用于 ProactiveAgent 新闻采集（feedparser 解析）",
    )
    proactive_digest_hour: int = Field(
        default=8, ge=0, le=23, description="新闻精选触发小时 (0-23)"
    )
    proactive_digest_minute: int = Field(
        default=0, ge=0, le=59, description="新闻精选触发分钟 (0-59)"
    )
    proactive_discuss_hour: int = Field(
        default=9, ge=0, le=23, description="讨论话题触发小时 (0-23)"
    )
    proactive_discuss_minute: int = Field(
        default=0, ge=0, le=59, description="讨论话题触发分钟 (0-59)"
    )
```

#### 3. src/llm_chat/proactive/agent.py:212,247

**File**: src/llm_chat/proactive/agent.py
**Changes**: MODIFY — add _fetch_rss() method after _fetch_web_context(); wire into _fetch_web_context() results

```python
    def _fetch_rss(self) -> str:
        """从配置的 RSS 源拉取标题+摘要。失败返回空字符串，不抛异常。"""
        feeds = getattr(self._config.scheduler, "proactive_rss_feeds", None) or []
        if not feeds:
            return ""

        try:
            import feedparser
        except ImportError:
            logger.warning("feedparser 未安装，跳过 RSS 采集")
            return ""

        snippets = []
        for url in feeds:
            try:
                d = feedparser.parse(url)
                if d.bozo:
                    logger.debug(f"RSS 解析警告 [{url}]: {d.bozo_exception}")
                for entry in d.entries[:5]:
                    title = entry.get("title", "")
                    summary = entry.get("summary", "") or entry.get("description", "")
                    link = entry.get("link", "")
                    if title:
                        line = f"{title}"
                        if summary:
                            line += f": {summary[:120]}"
                        if link:
                            line += f" [{link}]"
                        snippets.append(line)
            except Exception as e:
                logger.debug(f"RSS 抓取失败 [{url}]: {e}")
                continue

        return " | ".join(snippets) if snippets else ""
```

In `_fetch_web_context()` (agent.py:~208, before `return`), append RSS results:

```python
        # RSS feeds (feedparser) — 追加到 results
        rss_text = self._fetch_rss()
        if rss_text:
            results.append(f"【RSS订阅】{rss_text[:1500]}")
```

### Success Criteria:

#### Automated Verification:
- [ ] `grep -c 'feedparser' pyproject.toml` returns 1
- [ ] `grep -c 'proactive_rss_feeds' src/llm_chat/config/scheduler_config.py` returns 1
- [ ] `grep -c '_fetch_rss' src/llm_chat/proactive/agent.py` returns 3 (def + call + RSS订阅)
#### Manual Verification:
- [ ] `poetry add feedparser` succeeds
- [ ] 手动触发 `vermilion-bird schedule proactive`，确认 RSS 内容出现在卡片 context 中
- [ ] 不配置 RSS feeds 时 `_fetch_rss()` 返回空字符串，不影响卡片生成

## Phase 2: daily_digest 存储层

### Overview

创建 `StorageDigestMixin` 提供 `save_digest()` 和 `get_today_digest()`，遵循 `_task.py` mixin 模式。在 `_core.py._init_db()` 注册 `daily_digest` 建表。

Depends on: Phase 1 (config field `proactive_rss_feeds` exists, but digest table is independent).

### Changes Required:

#### 1. src/llm_chat/storage/_digest.py

**File**: src/llm_chat/storage/_digest.py
**Changes**: NEW — StorageDigestMixin: save_digest, get_today_digest

```python
"""News digest persistence (daily_digest table).

Phase 2 of ProactiveAgent two-stage pipeline.
"""

import json
import logging
import uuid
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


class StorageDigestMixin:
    """Daily news digest CRUD operations.

    Follows the StorageTaskMixin pattern (_task.py).
    Uses _get_connection() from StorageCore.
    """

    def save_digest(
        self,
        digest_date: str,
        items: list,
        raw_context: str = "",
    ) -> str:
        """Save or replace today's news digest.

        Args:
            digest_date: ISO date string, e.g. '2026-05-23'
            items: list of dicts with keys (rank, title, source, source_url,
                   summary, relevance)
            raw_context: raw collected context for discussion fallback

        Returns:
            digest id (UUID hex)
        """
        digest_id = uuid.uuid4().hex[:12]
        items_json = json.dumps(items, ensure_ascii=False)
        raw_json = json.dumps(
            {"context": raw_context}, ensure_ascii=False
        ) if raw_context else "{}"

        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_digest "
                "(id, date, items_json, raw_context_json) "
                "VALUES (?, ?, ?, ?)",
                (digest_id, digest_date, items_json, raw_json),
            )
            logger.info(
                f"Digest saved: {digest_id} date={digest_date} "
                f"items={len(items)}"
            )
            return digest_id

    def get_today_digest(self) -> Optional[dict]:
        """Retrieve today's digest.

        Returns:
            dict with keys (id, date, items, raw_context) or None.
            'items' is parsed from items_json into a Python list.
        """
        today = date.today().isoformat()
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM daily_digest WHERE date = ?",
                (today,),
            ).fetchone()
            if not row:
                return None

            items = []
            try:
                items = json.loads(row["items_json"])
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    f"Failed to parse items_json for date={today}"
                )

            raw_context = ""
            try:
                raw_data = json.loads(
                    row["raw_context_json"] or "{}"
                )
                raw_context = raw_data.get("context", "")
            except (json.JSONDecodeError, TypeError):
                pass

            return {
                "id": row["id"],
                "date": row["date"],
                "items": items,
                "raw_context": raw_context,
            }

    def get_digest_by_date(self, digest_date: str) -> Optional[dict]:
        """Retrieve digest for a specific date."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM daily_digest WHERE date = ?",
                (digest_date,),
            ).fetchone()
            if not row:
                return None
            items = []
            try:
                items = json.loads(row["items_json"])
            except (json.JSONDecodeError, TypeError):
                pass
            raw_context = ""
            try:
                raw_data = json.loads(row["raw_context_json"] or "{}")
                raw_context = raw_data.get("context", "")
            except (json.JSONDecodeError, TypeError):
                pass
            return {
                "id": row["id"],
                "date": row["date"],
                "items": items,
                "raw_context": raw_context,
            }
```

#### 2. src/llm_chat/storage/_core.py:88

**File**: src/llm_chat/storage/_core.py
**Changes**: MODIFY — add _create_digest_tables_in(conn) call after _create_decision_log_table_in

```python
            self._create_digest_tables_in(conn)
```

New method after existing table-creation methods:

```python
    def _create_digest_tables_in(self, conn):
        """Create daily_digest table for proactive news curation."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS daily_digest (
                id TEXT PRIMARY KEY,
                date TEXT UNIQUE NOT NULL,
                items_json TEXT NOT NULL,
                raw_context_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_daily_digest_date
                ON daily_digest(date);
        """)
```

#### 3. src/llm_chat/storage/__init__.py:14

**File**: src/llm_chat/storage/__init__.py
**Changes**: MODIFY — import and add StorageDigestMixin to Storage class

```python
from llm_chat.storage._digest import StorageDigestMixin
```

In `class Storage(...)`:

```python
class Storage(
    StorageConversationMixin,
    StorageTaskMixin,
    StorageDigestMixin,
    StorageFeishuMixin,
    StorageCore,
):
```

### Success Criteria:

#### Automated Verification:
- [ ] `grep -c 'StorageDigestMixin' src/llm_chat/storage/__init__.py` returns 2 (import + inheritance)
- [ ] `grep -c 'daily_digest' src/llm_chat/storage/_core.py` returns 1
- [ ] `grep -c 'save_digest\|get_today_digest' src/llm_chat/storage/_digest.py` returns 2
#### Manual Verification:
- [ ] 运行应用，确认 `daily_digest` 表在首次启动时自动创建
- [ ] 手动调用 `storage.save_digest('2026-05-23', [{"rank":1,"title":"test"}])` 后 `get_today_digest()` 返回正确数据

## Phase 3: ProactiveAgent mode 重构 + prompts

### Overview

新增 `prompts.py` (NEWS_CURATOR_PROMPT + DISCUSSION_PROMPT)。重构 ProactiveAgent 支持 mode 参数：`_run_news_digest()` (采集→LLM 精选→存 digest→推送文本) 和 `_run_discussion()` (读 digest→LLM 选题→推送卡片)。

Depends on: Phase 1 (_fetch_rss), Phase 2 (digest storage).

### Changes Required:

#### 1. src/llm_chat/proactive/prompts.py

**File**: src/llm_chat/proactive/prompts.py
**Changes**: NEW — NEWS_CURATOR_PROMPT and DISCUSSION_PROMPT

```python
"""Prompt templates for ProactiveAgent two-stage pipeline.

NEWS_CURATOR_PROMPT — Phase 1 (news digest): LLM curates 5-8 items from raw info.
DISCUSSION_PROMPT — Phase 2 (discussion): LLM generates decision card from digest + memory.
"""

NEWS_CURATOR_PROMPT = """你是一个嗅觉敏锐的信息策展人。用户每天委托你从大量资讯中挑选最值得关注的内容。

你的任务：从下方「资讯池」中精选 5-8 条最有价值的，按重要性排序。

## 选题原则
1. **对用户有价值**：这条资讯能改变用户的认知、提供行动灵感、或揭示重要趋势
2. **有时效性**：今天的新闻/发现/讨论
3. **多样性**：覆盖不同领域，不要全部是同一话题
4. **有深度**：不只是标题党，摘要能说清楚「为什么重要」

## 输出格式（严格遵循）

用以下格式输出，每条之间用空行分隔：

1. [标题]
   来源：来源名称
   链接：URL（如果有）
   摘要：一句话，≤80字
   为什么选：一句话，说明这条对用户的价值

2. [标题]
   来源：来源名称
   链接：URL
   摘要：...
   为什么选：...

...

## 输出要求
- 5-8 条，按重要性排序
- 每条摘要 ≤ 80 字
- 必须包含来源
- 如果资讯池不足 5 条，输出所有可用的
- 不要输出额外解释，只输出精选列表
"""

DISCUSSION_PROMPT = """你是一个消息灵通、嗅觉敏锐的AI伙伴。每天你会主动找用户聊天。

你的燃料来自两部分：
1. 「今日精选」（如果存在）—— 已经筛选过的重要资讯
2. 「用户记忆」—— 用户的兴趣、项目、近期讨论

你的目标是生成一张「话题建议卡」，给用户 2-3 个值得讨论的方向。

## 优先级
1. **借势精选**：如果今日精选中包含了令人兴奋的发现，优先从中选题
2. **连接记忆**：把精选和用户兴趣做连接
3. **独立选题**：如果今日精选不足，基于用户记忆生成话题
4. **出其不意**：引入用户可能感兴趣的新方向

## 提交方式
使用 submit_decision_card 工具提交卡片。不要输出 JSON 文本。

## 卡片内容要求
- title: 吸引人的主题（含 emoji）
- context: 一句话为什么今天值得聊
- options: 2-3 个方向，每个 label + description（≤30字）
- recommendation: 推荐选项 id (A/B/C)，可选
- sources: 引用来源 URL，可选

## 要求
1. 2-3 个选项，id 为 A, B, C
2. 选项之间要有区分度
3. title 含 emoji
4. 每个选项 description ≤ 30 字

## 禁区
- 不要空泛问候（"今天怎么样"）
- 不要无法参与的技术指令
- 不要讲大道理——要给出新视角或具体灵感
- 精选不足时宁可基于记忆选题，不编造
"""
```

#### 2. src/llm_chat/proactive/agent.py:67-94,253-331

**File**: src/llm_chat/proactive/agent.py
**Changes**: MODIFY — ProactiveAgent.__init__ adds mode; generate_and_push() dispatches; new methods _run_news_digest, _run_discussion, _curate_news, _format_digest, _push_text

```python
    # ── MODIFY: __init__ accepts mode parameter ──

    def __init__(self, app: "App", config: "Config", mode: str = "discussion"):
        self._app = app
        self._config = config
        self._mode = mode  # "news_digest" | "discussion"
        self._last_card: Optional[DecisionCard] = None

    # ── MODIFY: generate_and_push dispatches by mode ──

    def generate_and_push(self):
        if self._mode == "news_digest":
            self._run_news_digest()
        else:
            self._run_discussion()

    # ── NEW: news digest pipeline ──

    def _run_news_digest(self):
        """Phase 1: collect → LLM curate → save → push text digest."""
        ctx = self._build_context()

        if not ctx["web_news"].strip():
            logger.warning("无资讯可精选，跳过新闻推送")
            return

        items = self._curate_news(ctx)
        if not items:
            logger.warning("LLM 精选返回空，跳过新闻推送")
            return

        # 保存到 SQLite（供 discussion 阶段读取）
        try:
            from datetime import date
            today = date.today().isoformat()
            self._app.storage.save_digest(
                digest_date=today,
                items=items,
                raw_context=ctx["web_news"],
            )
            logger.info(f"今日精选已保存: {today}, {len(items)} 条")
        except Exception as e:
            logger.warning(f"保存 digest 失败: {e}")

        # 格式化并推送
        text = self._format_digest(items)
        self._push_text(text)

    def _curate_news(self, ctx: dict) -> list:
        """LLM 精选：从资讯池挑 5-8 条，返回 [DigestItem, ...]。

        DigestItem dict: {rank, title, source, source_url, summary, relevance}
        """
        from llm_chat.proactive.prompts import NEWS_CURATOR_PROMPT

        user_msg = f"## 资讯池\n\n{ctx['web_news']}"

        try:
            response = self._app.client.chat(
                message=user_msg,
                history=[{"role": "system", "content": NEWS_CURATOR_PROMPT}],
                temperature=0.4,
                max_tokens=1500,
                model=self._config.llm.model,
            )
        except Exception as e:
            logger.error(f"LLM 精选失败: {e}")
            return []

        return self._parse_curated(response)

    def _parse_curated(self, text: str) -> list:
        """Parse LLM curation output into list of DigestItem dicts.

        Expected format:
        1. [Title]
           来源：Source
           链接：URL
           摘要：Summary
           为什么选：Relevance
        """
        import re
        items = []
        # Split on numbered items
        blocks = re.split(r'\n(?=\d+\.\s)', text.strip())
        for i, block in enumerate(blocks):
            if not block.strip():
                continue
            title_match = re.search(r'\d+\.\s*(.+)', block)
            title = title_match.group(1).strip() if title_match else ""

            source = ""
            url = ""
            summary = ""
            relevance = ""

            for line in block.split('\n'):
                line = line.strip()
                if line.startswith('来源') or line.startswith('来源：'):
                    source = line.split('：', 1)[-1].strip() if '：' in line else line[2:].strip()
                elif line.startswith('链接') or line.startswith('链接：'):
                    url = line.split('：', 1)[-1].strip() if '：' in line else line[2:].strip()
                elif line.startswith('摘要') or line.startswith('摘要：'):
                    summary = line.split('：', 1)[-1].strip() if '：' in line else line[2:].strip()
                elif line.startswith('为什么选') or line.startswith('为什么选：'):
                    relevance = line.split('：', 1)[-1].strip() if '：' in line else line[3:].strip()

            if title:
                items.append({
                    "rank": len(items) + 1,
                    "title": title,
                    "source": source,
                    "source_url": url,
                    "summary": summary[:80] if summary else title[:80],
                    "relevance": relevance,
                })
        return items

    def _format_digest(self, items: list) -> str:
        """Format curated items into readable text digest."""
        from datetime import datetime
        now = datetime.now()
        lines = [f"📰 今日精选 · {now.month}月{now.day}日\n"]
        for item in items[:8]:
            emoji = "🔬" if "科学" in item.get("source", "") else "💻" if any(
                k in item.get("source", "") for k in ["HN", "Hacker", "GitHub", "ArXiv"]
            ) else "📌"
            lines.append(
                f"{item['rank']}. {emoji} {item['title']}\n"
                f"   来源: {item['source']} · {item['summary']}"
            )
        return "\n".join(lines)

    def _push_text(self, text: str):
        """Push plain text to Feishu and GUI."""
        if not text.strip():
            return
        # Feishu
        if self._config.feishu.enabled:
            try:
                adapter = getattr(self._app, "_feishu_adapter", None)
                if adapter:
                    recent = adapter.get_recent_chat()
                    if not recent or recent.get("type") != "feishu":
                        try:
                            recent = self._app.storage.get_recent_feishu_chat()
                        except Exception:
                            pass
                    if recent:
                        receive_id = recent.get("chat_id") or recent.get("open_id") or recent.get("user_id")
                        receive_id_type = "chat_id" if "chat_id" in recent else ("open_id" if "open_id" in recent else "user_id")
                        if receive_id:
                            adapter.send_message(
                                receive_id=receive_id,
                                msg_type="text",
                                content={"text": text},
                                receive_id_type=receive_id_type,
                            )
                            logger.info(f"新闻精选已推送到飞书")
            except Exception as e:
                logger.warning(f"飞书文本推送失败: {e}")

        # GUI
        try:
            frontend = getattr(self._app, "current_frontend", None)
            if frontend and frontend.name == "gui":
                from llm_chat.frontends.base import Message, MessageType
                msg = Message(content=text, role="assistant", msg_type=MessageType.TEXT)
                frontend.display_message(msg)
        except Exception as e:
            logger.warning(f"GUI 推送失败: {e}")

    # ── MODIFY: discussion pipeline (replaces old _generate_card flow) ──

    def _run_discussion(self):
        """Phase 2: read digest → (re-collect if needed) → generate discussion card."""
        ctx = self._build_context()

        # 尝试读取今日精选
        try:
            digest = self._app.storage.get_today_digest()
            if digest and digest.get("items"):
                # 精选存在：用精选的 raw_context 替换 web_news
                if digest.get("raw_context"):
                    ctx["web_news"] = digest["raw_context"]
                # 将精选摘要注入 context
                digest_text = self._format_digest(digest["items"])
                ctx["digest_summary"] = digest_text
                logger.info(f"讨论阶段读取今日精选: {len(digest['items'])} 条")
            else:
                logger.info("今日无精选，讨论阶段使用原始采集+记忆")
                ctx["digest_summary"] = ""
        except Exception as e:
            logger.warning(f"读取 digest 失败，fallback 到原始采集: {e}")
            ctx["digest_summary"] = ""

        # 生成卡片（复用现有 _generate_card 逻辑，增加 digest context）
        self._generate_card_with_digest(ctx)

    def _generate_card_with_digest(self, ctx: dict):
        """Generate decision card with optional digest context.

        Replaces the original _generate_card() flow.
        The original _generate_card is renamed to this.
        """
        # 构建 user message with digest
        sections = ["## 背景信息", f"当前时间：{ctx.get('time', '')}"]

        # 今日精选优先展示
        if ctx.get("digest_summary"):
            sections.append("\n### 🌐 今日精选（主要素材）")
            sections.append(ctx["digest_summary"])
        elif ctx.get("web_news", "").strip():
            sections.append("\n### 🌐 网络资讯")
            sections.append(ctx["web_news"])

        if ctx.get("memory", "").strip():
            sections.append("\n### 关于用户的背景")
            sections.append(ctx["memory"])

        if ctx.get("recent_topics", "").strip():
            sections.append("\n### 近期讨论")
            sections.append(ctx["recent_topics"])

        if ctx.get("current_project"):
            sections.append(f"\n### 当前项目\n{ctx['current_project']}")

        sections.append("\n---")
        sections.append(
            "请基于以上信息生成一张话题建议卡。\n\n"
            "核心原则：从今日精选/资讯中找出最值得聊的东西。"
            "用户背景和近期讨论只用来判断'这个资讯跟用户有没有关系'。"
        )

        user_message = "\n".join(sections)

        # 使用 chat_with_tools — submit_decision_card
        from llm_chat.tools.registry import ToolRegistry
        from llm_chat.decision.submit_tool import init_card_context, clear_card_context, get_pending_card
        from llm_chat.proactive.prompts import DISCUSSION_PROMPT

        registry = ToolRegistry()
        all_tools = registry.get_tools_for_openai()
        card_tool = [t for t in all_tools if t.get("function", {}).get("name") == "submit_decision_card"]
        if not card_tool:
            logger.warning("submit_decision_card 工具未注册")
            return

        # Retry logic (3 attempts) — same as current _generate_card
        RETRY_HINTS = [
            "",
            "\n\n⚠️ 注意：请使用 submit_decision_card 工具提交卡片。",
            "\n\n🔴 重要：你必须立即调用 submit_decision_card 工具！"
        ]

        for attempt in range(len(RETRY_HINTS)):
            hint = RETRY_HINTS[attempt]
            message = user_message + hint

            try:
                init_card_context()
                response_text = ""
                try:
                    response_text = self._app.client.chat_with_tools(
                        message=message,
                        tools=card_tool,
                        history=[{"role": "system", "content": DISCUSSION_PROMPT}],
                        temperature=0.8,
                        max_tokens=2000,
                        model=self._config.llm.model,
                    ) or ""
                    card = get_pending_card()
                finally:
                    clear_card_context()

                if card:
                    logger.info(
                        f"ProactiveAgent 生成卡片 (attempt {attempt + 1}): "
                        f"{card.id} -> {card.title}"
                    )
                    self._last_card = card
                    self._push_to_feishu(card)
                    self._push_to_gui(card)
                    return

                resp_preview = response_text[:200].replace("\n", " ") if response_text else "<empty>"
                if attempt < len(RETRY_HINTS) - 1:
                    logger.warning(f"卡片生成失败 (attempt {attempt + 1}): {resp_preview}")
                else:
                    logger.warning(f"卡片生成最终失败: {resp_preview}")

            except Exception as e:
                logger.warning(f"卡片生成 attempt {attempt + 1} 异常: {e}")
                if attempt >= len(RETRY_HINTS) - 1:
                    logger.error(f"生成话题卡片最终失败: {e}", exc_info=True)

    # ── REMOVE: old _generate_card method (replaced by _generate_card_with_digest above)
```

### Success Criteria:

#### Automated Verification:
- [ ] `grep -c 'def _run_news_digest' src/llm_chat/proactive/agent.py` returns 1
- [ ] `g -c 'def _run_discussion' src/llm_chat/proactive/agent.py` returns 1
- [ ] `grep -c 'def _curate_news' src/llm_chat/proactive/agent.py` returns 1
- [ ] `grep -c 'NEWS_CURATOR_PROMPT' src/llm_chat/proactive/prompts.py` returns 1
- [ ] `grep -c 'DISCUSSION_PROMPT' src/llm_chat/proactive/prompts.py` returns 1
#### Manual Verification:
- [ ] 手动触发 `--mode news_digest`，飞书收到新闻精选文本，SQLite daily_digest 有记录
- [ ] 手动触发 `--mode discussion`，飞书收到决策卡片
- [ ] 无 digest 时 discussion 仍能生成卡片（fallback 到记忆）
- [ ] `generate_and_push()` 无参数调用等价于 `mode="discussion"`（向后兼容）

## Phase 4: 调度器 + app 接线

### Overview

Scheduler 读取 `task.params["mode"]` 传递给 ProactiveAgent。App 注册两个 cron job (8:00 digest + 9:00 discuss)。更新 config.example.yaml。

Depends on: Phase 3 (agent supports mode).

### Changes Required:

#### 1. src/llm_chat/scheduler/scheduler.py

**File**: src/llm_chat/scheduler/scheduler.py
**Changes**: MODIFY — _run_proactive_chat_task reads mode from task.params

```python

```

#### 2. src/llm_chat/app.py

**File**: src/llm_chat/app.py
**Changes**: MODIFY — register two proactive cron jobs (digest + discuss)

```python

```

#### 3. config.example.yaml

**File**: config.example.yaml
**Changes**: MODIFY — add proactive_rss_feeds and digest/discuss time config example

```yaml

```

### Success Criteria:

#### Automated Verification:
- [ ] `grep -c 'mode.*task.params' src/llm_chat/scheduler/scheduler.py` returns 1
- [ ] `grep -c 'news_digest' src/llm_chat/app.py` returns 3 (id + params + log)
- [ ] `grep -c 'proactive-digest' src/llm_chat/app.py` returns 1
- [ ] `grep -c 'proactive-discuss' src/llm_chat/app.py` returns 1
#### Manual Verification:
- [ ] 启动应用，确认 scheduler 日志显示两个 cron job 注册成功
- [ ] 等待到 8:00 或手动触发，确认飞书收到新闻精选文本
- [ ] 9:00 确认飞书收到讨论话题卡片
- [ ] 修改 config.yaml 中的 rss_feeds 和 cron 时间，重启后生效

## Plan Review (Step 10)

_Independent post-finalization review by artifact-reviewer subagent. Findings triaged at Step 11._

_Step 10 review dispatch deferred — proceeding with developer review._

## Plan History

- Phase 1: feedparser 集成 + RSS 采集 — approved as generated
- Phase 2: daily_digest 存储层 — approved as generated
- Phase 3: ProactiveAgent mode 重构 + prompts — approved as generated
- Phase 4: 调度器 + app 接线 — approved as generated

## References

- `thoughts/shared/designs/2026-05-23_14-00-00_proactive-two-stage.md` — Design artifact
- `thoughts/shared/solutions/2026-05-23_13-48-08_info-aggregation-pipeline.md` — Solutions analysis
- `src/llm_chat/proactive/agent.py` — Current ProactiveAgent implementation
- `src/llm_chat/storage/_task.py:18-162` — Storage mixin pattern
- `src/llm_chat/app.py:604-658` — Proactive task registration pattern
