---
date: 2026-05-23T13:48:08+0800
author: wuxun
commit: 2674231
branch: main
repository: vermilion-bird
topic: "自动信息采集与整理管道（新闻/社交媒体 RSS 聚合）"
confidence: high
complexity: medium
status: ready
tags: [solutions, proactive-agent, rss, feedparser, rsshub, news]
last_updated: 2026-05-23T13:48:08+0800
last_updated_by: wuxun
---

# Solution Analysis: 自动信息采集与整理管道

**Date**: 2026-05-23T13:48:08+0800
**Author**: wuxun
**Commit**: 2674231
**Branch**: main
**Repository**: vermilion-bird

## Research Question

如何为 vermilion-bird 的 ProactiveAgent 增加自动信息采集能力，定期整理微博、小红书、X/Twitter 及新闻的
有价值信息，替代当前“每日 9 点临时 DDGS 搜索”的被动模式？

## Summary

**Problem**: ProactiveAgent 当前仅依赖 DDGS 即时搜索，无信息沉淀、无时间轴，卡片生成不稳定。
**Recommended**: 两阶段策略 —— 先落地轻量 RSS + feedparser（P0），1-2 天完成；再视需求引入 RSSHub（P1）覆盖社交媒体。
**Effort**: P0: Low (~2 days), P1: Medium (~7 days)
**Confidence**: High

## Problem Statement

**Requirements:**
- 自动采集新闻、微博、小红书、X 的有价值信息
- 定期整理并喂给 ProactiveAgent，而非临时搜索
- 不引入过重的运维负担（桌面应用）
- 与现有 scheduler/ProactiveAgent 无缝集成

**Constraints:**
- Python 3.10+ 桌面应用，不适合部署重量级基础设施
- 微博/小红书反爬严格，直接爬取不可行
- X API v2 收费 $100-5000/月
- 部分平台需要 cookie/认证

**Success criteria:**
- ProactiveAgent 卡片生成成功率提升（从 ~60% 到 >85%）
- 信息有“时间轴”——不只是当天搜索，而是积累的历史
- 用户可以配置关注的信息源（RSS URL）

## Current State

**Existing implementation:**

ProactiveAgent (`src/llm_chat/proactive/agent.py:173-212`) 的 `_fetch_web_context()` 在每次触发时
临时调用 DDGS 搜索 6-12 次，按星期轮换主题。结果以字符串形式直接注入 LLM prompt，不持久化。

**Relevant patterns:**
- DDGS 搜索模式: `agent.py:217-245` — 本地 `from ddgs import DDGS`，30 秒超时，线程安全
- 4-tier 网页抓取: `skills/web_fetch/skill.py:155-172` — Jina→Playwright→req+BS4→req
- 调度器扩展: `scheduler/models.py:10-15` — TaskType 枚举，if/elif 分发
- 存储 mixin: `storage/_task.py` — CRUD + JSON metadata 模式
- Pydantic config: `config/skills_config.py:36` — `extra = "allow"` 接受未知键

**Integration points:**
- `proactive/agent.py:117` — `_build_context()` 构建 `web_news` 字段，新数据源注入点
- `scheduler/scheduler.py:565` — `_run_proactive_chat_task()` 现有触发点
- `scheduler/models.py:10` — TaskType 枚举，可添加新类型

## Solution Options

### Option 1: RSSHub + feedparser (Recommended for P1)

**How it works:**
部署 RSSHub Docker 实例（Node.js, 44k star）生成微博/小红书/X 的 RSS 2.0 源，
Python 端用 `feedparser` 消费。调度器定时拉取→存储到 SQLite→ProactiveAgent 读取。

**Pros:**
- 唯一可行覆盖微博、小红书、X 三个平台的路径
- RSSHub 社区维护 1000+ 路由，反爬更新由社区承担
- `feedparser` 20 年历史，BSD 许可，零风险
- 标准化 RSS/Atom 输出，消费逻辑极简

**Cons:**
- Docker 3 容器占用 1-2 GB RAM（RSSHub + Redis + browserless/Chrome）
- Xiaohongshu 路由需要 cookie，有 captcha 风险，需定期维护
- Weibo 用户路由需要 Puppeteer（`requirePuppeteer: true`）
- Node.js 依赖打破了纯 Python 技术栈

**Complexity:** Medium (~7 days)
- Files to create: 4 (`skills/feed_reader/skill.py`, `storage/_feed.py`, `ingestion/feed_ingestor.py`, `ingestion/__init__.py`)
- Files to modify: 7 (scheduler models/scheduler/executor, storage core/init, proactive/agent.py, config)
- Risk level: Medium (Docker 运维、cookie 过期)

### Option 2: MCP Firecrawl + gnews API

**How it works:**
Firecrawl MCP server 做网页抓取，gnews Python SDK 做新闻聚合。纯 Python 架构，利用已有 MCP 基础设施。

**Pros:**
- 零新服务部署（复用现有 MCPManager + ToolRegistry）
- Firecrawl 14 个工具，爬取引擎成熟（YC 投资，SOC 2）
- gnews SDK 中文支持（`zh-Hans`, `CN`）

**Cons:**
- Firecrawl **无中国平台支持**（微博/小红书/X 均无文档化路由）
- gnews 依赖 Google News RSS，中国国内新闻覆盖有限
- 两项服务合计 ~$20-90/月
- gnews 单人维护，巴士系数 = 1

**Complexity:** Medium (~5 days)
- Risk level: Medium-High (中国内容覆盖是致命短板)

### Option 3: 自研 Playwright 爬虫

**How it works:**
利用已有 Playwright 依赖直接写三个爬虫模块，每个平台一个 skill。

**Pros:**
- 零外部服务依赖，完全自主
- 已有 Playwright/trafilatura/BS4 基础设施可复用

**Cons:**
- **小红书反 Playwright**：需要移动端 API 逆向（X-s/X-t 签名），浏览器自动化无效
- **X/Twitter 有更好的库**：`twikit`、`snscrape` 已在 Python 生态中解决了这个问题
- **Weibo**：需要 cookie + 中国住宅代理，DOM 每季度变化
- 维护成本极高：6+ 新文件，每个平台独立维护
- 已有库（`xhs`、`twikit`、RSSHub）都比自研更成熟

**Complexity:** High (~14 days 初版 + 持续维护)
- Risk level: High (维护陷阱)

### Option 4: 轻量 DDGS 增强 + feedparser (Recommended for P0)

**How it works:**
在 `ProactiveAgent._fetch_web_context()` 中增加 `_fetch_rss()` 调用，用 `feedparser` 解析
用户配置的 RSS 源 URL。零新服务，仅 1 个 pip 依赖 + ~50 行代码。

**Pros:**
- **precedent-fit: STRONG** — 与现有 DDGS 搜索模式完全一致（纯 Python lib、本地 import、字符串结果）
- **migration-cost: LOW** — ~50 LOC，2-3 文件修改，1 个新依赖
- **integration-risk: LOW** — 仅修改 `_fetch_web_context()` 一个方法
- **verification-cost: MODERATE** — `feedparser` 可用静态 XML mock 测试
- 用户可自由配置任何 RSS 源（HN、arXiv、博客、新闻网站）
- 无新增服务、无存储变更、无调度器改动

**Cons:**
- **无微博/小红书/X 专属通道** — RSS 源需用户自行寻找或通过第三方 RSS 桥
- 信息覆盖有限于“有 RSS 的源”
- 无内容去重和持久化（每次触发重新拉取）

**Complexity:** Low (~2 days)
- Files to create: 0 (仅修改)
- Files to modify: 2-3 (`agent.py`, `pyproject.toml`, 可选 `config`)
- Risk level: Low

## Comparison

| Criteria | RSSHub+feedparser | MCP+gnews | Playwright 爬虫 | Light DDGS+feedparser |
|----------|:-:|:-:|:-:|:-:|
| 微博支持 | ✅ | ❌ | ⚠️ 脆弱 | ❌ (需 RSS 桥) |
| 小红书支持 | ⚠️ 需要 cookie | ❌ | ❌ 不可行 | ❌ |
| X/Twitter 支持 | ✅ | ⚠️ API 付费 | ⚠️ 有更好库 | ❌ |
| 新闻支持 | ✅ (RSS 源) | ✅ | ❌ | ✅ (RSS 源) |
| Complexity | Medium | Medium | High | **Low** |
| Codebase fit | Weak | Moderate | Weak | **Strong** |
| 运维负担 | High (Docker) | Low (API) | High (维护) | **None** |
| 月成本 | $0 | $20-90 | $0 (时间) | **$0** |
| 新增依赖 | Docker+feedparser | API keys | 0 | **1 pip** |

## Recommendation

**Selected: 两阶段策略**

### Phase 0: 轻量 DDGS + feedparser（立即落地）

先做 P0 —— 这是投入产出比最高的一步：
1. `poetry add feedparser`
2. 在 `_fetch_web_context()` 中并行调用 `_fetch_rss()`
3. 用户可在 config 中配置 RSS 源 URL 列表
4. ~50 行代码，2 天完成

这一步不改变架构，但立即让 ProactiveAgent 拥有可配置的“信息订阅”能力。
用户可订阅 Hacker News、arXiv、技术博客、新闻 RSS 等任何有 RSS 的平台。

### Phase 1: RSSHub（按需引入）

当用户确实需要微博/小红书/X 的内容时，再引入 RSSHub。此时：
- P0 的 `_fetch_rss()` 和 `feedparser` 消费路径已经存在
- 只需配置 RSSHub URL 为 RSS 源 → 零代码改动
- Docker 运维负担是明确的 trade-off

**Why not alternatives:**
- MCP+gnews: 中国内容覆盖是致命短板，无法满足“微博/小红书/X”需求
- Playwright 爬虫: 小红书不可行，X 有更好的生态库，维护陷阱

**Trade-offs:**
- 接受 P0 阶段无社交媒体覆盖 → 换来零运维、零成本、最低复杂度
- RSSHub 的 Docker 负担 → 换取社区维护的反爬逻辑

**Implementation approach (P0):**
1. `poetry add feedparser` → 添加依赖
2. `proactive/agent.py` 新增 `_fetch_rss()` 方法（~25 行）
3. `_fetch_web_context()` 中调用 `_fetch_rss()`，结果追加到 `results`
4. `config/scheduler_config.py` 新增 `proactive_rss_feeds: list[str] = []`
5. 写 4 个单元测试（mock feedparser 返回）

**Integration points:**
- `proactive/agent.py:173` — `_fetch_web_context()` 增加 RSS 调用
- `config/scheduler_config.py:36` — 新配置字段

**Patterns to follow:**
- `_search()` at `agent.py:217` — 相同的私有方法模式
- `SkillsConfig.extra = "allow"` at `skills_config.py:36` — 配置扩展模式

**Risks:**
- RSS URL 超时阻塞 ProactiveAgent: 设置 `timeout=10`，与 DDGS 一致
- 坏 RSS XML: `feedparser` 自带容错（`bozo_exception`），不会崩溃

## Scope Boundaries
- **做**: RSS 源的拉取、解析、注入 ProactiveAgent context
- **不做**: 社交媒体直接爬取、内容去重存储、RSSHub 部署（留给 P1）
- **不做**: 替换 DDGS 搜索 —— RSS 是增强，不是替代

## Testing Strategy

**Unit tests:**
- `_fetch_rss()` with mocked `feedparser.parse()` returning 2 entries → 验证格式化输出
- `_fetch_rss()` with HTTP timeout → 验证返回空字符串
- `_fetch_rss()` with malformed XML → 验证不崩溃
- `_fetch_web_context()` integration with mocked `_search` + `_fetch_rss` → 验证合并输出

**Manual verification:**
- [ ] 配置一个真实 RSS URL（如 Hacker News），手动触发 `vermilion-bird schedule proactive`
- [ ] 确认卡片中出现了 RSS 来源的标题
- [ ] 配置 3+ RSS URL，确认不会超时阻塞

## Open Questions

**Resolved during research:**
- feedparser 是否兼容 Python 3.13? → 是，v6.0.12 通过 CPython 3.13.7 上传的 `py3-none-any` wheel
- RSSHub 是否覆盖微博/小红书/X? → 是，三个平台均有活跃维护的路由
- 自研 Playwright 爬虫是否可行? → 小红书不可行，X/微博有更好的生态库

**Requires user input:**
- P0 阶段希望订阅哪些 RSS 源? → 默认无，用户自行配置
- 是否接受 P1 阶段的 Docker 部署? → 默认接受，待 P0 验证后再决定

## References

- `src/llm_chat/proactive/agent.py:173-245` — 现有 web context 构建和搜索
- `src/llm_chat/skills/web_fetch/skill.py:253-390` — Playwright + trafilatura 内容提取
- `src/llm_chat/scheduler/models.py:10-15` — TaskType 枚举扩展点
- `src/llm_chat/storage/_task.py` — CRUD mixin 模式（P1 时参考）
- `config.example.yaml:279-281` — proactive 调度配置
- [feedparser PyPI](https://pypi.org/project/feedparser/) — v6.0.12, BSD-2-Clause
- [RSSHub GitHub](https://github.com/DIYgod/RSSHub) — 44.2k stars, AGPL-3.0
- [GNews PyPI](https://pypi.org/project/gnews/) — v0.4.3
- [Firecrawl MCP Docs](https://docs.firecrawl.dev/mcp-server)
