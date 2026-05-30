# 领域知识系统 — 设计方案

> 创建时间: 2026-05-30
> 状态: 设计阶段，待实现

## 1. 背景与目标

### 1.1 现有能力

Vermilion Bird 已有两套沉淀系统：

| 系统 | 沉淀内容 | 生命周期 |
|------|---------|---------|
| **三层记忆** (short/mid/long/soul) | 用户画像、偏好、行为模式 | 时间驱动：短期→中期压缩→长期进化 |
| **Skill 系统** (BaseSkill + PromptSkill) | 操作能力、工具、工作流指令 | 加载即用，PromptSkill 支持渐进式披露 |

### 1.2 缺失的能力

Agent 在与用户长期对话中涉及特定**领域**（如投资、机器学习、烹饪）时，无法沉淀领域专业知识。例如：

- 用户讨论了 20 次投资话题，每次 agent 都是从零开始
- 用户在多次纠正后建立的领域共识（"这里用 PE 分位数不是绝对 PE"），下次对话全忘了
- 无法跨会话、跨项目复用已积累的领域知识

### 1.3 目标

构建**领域知识系统**，使 agent 能够：

1. **自动检测**对话涉及的领域
2. **自动提取**领域知识点并持久化
3. **按需加载**领域知识到 system prompt，不浪费 token
4. **持续进化**：去重、归类、提炼、淘汰过时知识
5. **显式控制**：用户/LLM 可主动写入和查询

---

## 2. 核心设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 组织形式 | **按领域分文件**，非按项目 | 投资知识跨项目通用，不应绑定 git 仓库 |
| 领域创建 | **自然涌现**，非预定义 | 聊到新话题自动创建领域文件 |
| 注入方式 | **混合模式**（对齐 PromptSkill 渐进式披露） | 默认只注摘要，LLM 按需加载全文 |
| 提取频率 | **每 N 轮批量提取** | 减少 LLM 调用，提高提取质量 |
| 文件格式 | **Markdown + YAML frontmatter**（复用 PromptSkill 标准） | 保持一致性，无需新解析逻辑 |
| 进化策略 | **两级管道**：整合 (≥10条) → 提炼 (≥50条) | 对齐记忆系统的进化哲学 |

---

## 3. 架构概览

```
~/.vermilion-bird/knowledge/
├── investment.md           # 每个 .md = 一个领域
├── machine-learning.md
└── ...                     # 领域文件自动创建，自然涌现

src/llm_chat/knowledge/
├── __init__.py             # 公共导出
├── storage.py              # KnowledgeStorage — 扫描发现 + 文件 I/O + 原子写入
├── manager.py              # KnowledgeManager — 编排器 (提取/存储/注入/进化)
├── extractor.py            # KnowledgeExtractor — LLM 提取 + 整合 + 提炼
└── templates.py            # knowledge.md 初始模板

src/llm_chat/skills/knowledge_base/
├── __init__.py
└── skill.py                # KnowledgeBaseSkill — read_knowledge + remember_knowledge 工具
```

### 3.1 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| **KnowledgeStorage** | `storage.py` | 扫描 knowledge/ 目录发现领域；解析 YAML frontmatter；原子写入；追加知识点；全文搜索 |
| **KnowledgeManager** | `manager.py` | 编排：提取→存储→注入→整合→提炼。单例，由 ConversationManager 持有 |
| **KnowledgeExtractor** | `extractor.py` | LLM prompt 工程：从对话提取知识点；检测新领域；整合去重归类；提炼重组淘汰 |
| **KnowledgeBaseSkill** | `skills/knowledge_base/` | 两个工具：`read_knowledge` (加载全文) + `remember_knowledge` (显式写入) |
| **Template** | `templates.py` | knowledge.md 初始模板（含 YAML frontmatter 和章节结构） |

---

## 4. 文件格式

### 4.1 knowledge.md 结构

对齐 PromptSkill 的 SKILL.md 格式（YAML frontmatter + Markdown body）：

```markdown
---
name: investment
display_name: 投资
description: 投资领域专业知识，涵盖价值投资、指数基金、资产配置策略
type: requested
keywords: [股票, 基金, A股, PE, ROE, 仓位, 定投, ETF, 估值, 分红, 基本面, 技术分析]
created_at: "2026-05-30T10:00:00"
updated_at: "2026-05-30T10:00:00"
fact_count: 0
---

# 领域知识：投资

## 概述
(待生成：知识条目积累 ≥50 条后，由 LLM 自动生成领域总览)

## 核心概念
(待整理：知识条目积累 ≥10 条后，由 LLM 自动归类填充)

## 策略与方法
(待整理)

## 经验与教训
(待整理)

## 资源与参考
(待整理)

## 知识条目 (未整理)
> 以下为自动追加的原始知识点。积累 ≥10 条后自动整合归入上述结构化章节；
> 总数 ≥50 条后触发深度提炼。

---
```

### 4.2 Frontmatter 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 领域标识符（英文，用于文件名和工具调用） |
| `display_name` | string | 领域显示名（中文，system prompt 中展示） |
| `description` | string | 一句话描述，渐进式披露的摘要行 |
| `type` | enum | `always` / `requested` / `manual`（对齐 PromptSkill 三模式） |
| `keywords` | list | 关键词表，DomainDetector 匹配用；LLM 自动扩充 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 最后更新时间 |
| `fact_count` | int | 知识点总数（含已整理和未整理） |

### 4.3 type 字段语义

| type | 含义 | system prompt 行为 |
|------|------|-------------------|
| `always` | 核心领域，始终注入全文 | 全文注入，token 预算内 |
| `requested` | 默认模式，按需加载 | 只注入 `display_name + description` 一行摘要；LLM 调用 `read_knowledge` 加载全文 |
| `manual` | 仅用户显式触发 | 只注入摘要行；用户需明确要求才加载 |

---

## 5. 数据流

### 5.1 三条路径总览

```
┌──────────────────────────────────────────────────────────────────────┐
│                           对话管道                                     │
│                                                                      │
│  ① 自动提取 (每 N 轮)                                                 │
│     process_pending_extractions()                                    │
│     └─ KnowledgeManager.extract_domain_knowledge(messages)           │
│         ├─ DomainDetector: 扫描所有领域 frontmatter 的 keywords       │
│         │   命中 → 标记涉及的领域                                      │
│         ├─ 未匹配但话题连贯 → KnowledgeExtractor 建议新领域            │
│         ├─ 每个匹配领域: LLM 提取知识点 → append 到 ## 知识条目        │
│         └─ 自动扩充 frontmatter 的 keywords                           │
│                                                                      │
│  ② 系统注入 (每次 build_system_prompt)                                │
│     KnowledgeManager.build_knowledge_context(user_message)            │
│     ├─ DomainDetector: 匹配当前消息的领域                              │
│     ├─ type=always 的匹配领域 → 全文注入                               │
│     └─ type=requested/manual 的匹配领域 → 一行摘要注入                 │
│         "## 领域知识库 (用 read_knowledge 加载全文)"                    │
│         "- 投资 (investment): 投资领域专业知识，涵盖价值投资..."          │
│                                                                      │
│  ③ LLM 主动调用 (对话中)                                              │
│     LLM 调用 read_knowledge(domain="investment")                      │
│     → 返回 investment.md 全文                                          │
│     LLM 调用 remember_knowledge(domain="投资", fact="...", category)   │
│     → 追加到 ## 知识条目，更新 fact_count                               │
└──────────────────────────────────────────────────────────────────────┘
```

### 5.2 自动提取详细流程

```
process_pending_extractions()          # 现有入口
│
├── (现有) _write_short_term_directly()
├── (现有) _extract_to_mid_term()
├── (现有) _maybe_compress_mid_term()
├── (现有) _maybe_evolve_understanding()
│
└── (新增) _maybe_extract_domain_knowledge()
    │
    ├── 1. 收集近期消息 (最近 N 轮)
    │   2. 拼接为文本 → DomainDetector 关键词匹配
    │      遍历所有 domain.md 的 frontmatter.keywords
    │      统计每个领域命中次数
    │
    ├── 3. 对每个命中数 ≥ 阈值的领域:
    │      KnowledgeExtractor.extract_facts(messages, domain_name)
    │      → LLM prompt: "从以下对话中提取关于'{domain}'的专业知识"
    │      → 返回 list of facts，每条带 category 标签
    │      → 每条: KnowledgeStorage.append_fact(domain, fact)
    │      → 更新 frontmatter.fact_count
    │
    ├── 4. 检测新领域:
    │      如果话题连贯但不匹配任何已知领域:
    │      KnowledgeExtractor.suggest_new_domain(messages)
    │      → LLM prompt: "这段对话是否涉及一个新领域？如果是，建议名称和关键词"
    │      → 如果 LLM 信心高: 创建新 knowledge/{name}.md
    │
    └── 5. 触发进化检查:
           _maybe_consolidate_domain()  # fact_count - 上次整理时 count ≥ 10
           _maybe_refine_domain()       # fact_count ≥ 50
```

### 5.3 System Prompt 注入详细流程

```
ChatCore._build_system_context()
│
├── (现有) MemoryManager.build_system_prompt()
│   → 注入 soul + 行为指引 + long_term + mid_term + short_term
│
├── (现有) PromptSkill 注入
│   → SkillManager.get_prompt_skills_for_context()
│
└── (新增) KnowledgeManager.build_knowledge_context(user_message)
    │
    ├── 1. DomainDetector.match(user_message)
    │      遍历所有领域的关键词 → 返回匹配领域列表
    │
    ├── 2. 对 type=always 的匹配领域:
    │      注入全文 (受 token 预算限制，约 300 tokens/领域)
    │
    └── 3. 对 type=requested/manual 的匹配领域:
           注入一行摘要
           "## 领域知识库 (用 read_knowledge 加载全文)\n"
           "- {display_name} ({name}): {description}\n"
```

---

## 6. 进化模型

### 6.1 两级管道

对齐记忆系统的分层进化哲学：

```
知识条目 (未整理)                        原始积累层
  │ 每轮对话追加 1-N 条
  │
  ├─── 触发条件: 未整理条目 ≥ 10 条 ───
  │
  ▼
整合 (consolidate)                       压缩层
  ├─ 去重合并: 语义相同的条目合并
  ├─ 归类: 分配到 核心概念/策略/经验 章节
  ├─ 冲突检测: 发现矛盾 → 标记 [待确认] 或合并
  ├─ 更新 keywords 表
  └─ 清空"未整理"区，重置计数器
  │
  ├─── 触发条件: 总知识点 ≥ 50 条 ───
  │
  ▼
提炼 (refine)                            进化层
  ├─ 重写"概述": 生成领域总览段落
  ├─ 重组章节: 过长章节拆分子章节
  ├─ 淘汰过时知识: 移至 [历史归档] 折叠区
  ├─ 精炼 frontmatter.description
  └─ 更新 frontmatter.updated_at
```

### 6.2 触发节奏

| 阶段 | 触发条件 | LLM 调用 | 安全网 |
|------|---------|---------|--------|
| 累积 | 每 N 轮对话（N 可配，默认 20） | 提取时 1 次/领域 | — |
| 整合 | 未整理条目数 ≥ 10 | 1 次/领域 | 输入条数 × 70% 阈值，不足则拒绝写入 |
| 提炼 | 总知识点数 ≥ 50 | 1 次/领域 | 保留原有章节结构，不做大改 |

### 6.3 冲突检测示例

```
整合时 LLM 发现：
  [2026-03] A股沪深300 PE分位数 40%，处于低估区间
  [2026-06] A股沪深300 PE分位数 65%，接近高估

LLM 输出处理：
  合并为:
  - [策略] A股估值用PE分位数判断，需结合市场环境（40%以下低估，60%以上高估）
  
  不标记 [待确认] — 因为两条反映不同时点的市场变化，不是逻辑矛盾
```

```
如果 LLM 发现真正矛盾:
  [2026-03] 推荐使用 Black-Scholes 模型定价期权
  [2026-05] Black-Scholes 模型不适用于中国市场，改用蒙特卡洛模拟

LLM 输出处理：
  - [待确认] 期权定价模型选择存在分歧：3月推荐BS模型，5月建议用蒙特卡洛
    保留两条原始记录供用户确认
```

---

## 7. 工具设计

### 7.1 knowledge_base Skill

继承 `BaseSkill`，注册到 `BUILTIN_SKILLS`，提供 2 个工具：

#### read_knowledge

```
read_knowledge(domain: str) → str

加载指定领域的完整知识。
- LLM 看到 system prompt 中的摘要列表后，需要详细知识时调用
- 返回 knowledge/{domain}.md 的全文
- 如果领域不存在，返回可用领域列表
```

#### remember_knowledge

```
remember_knowledge(domain: str, fact: str, category: str = "other") → str

显式写入一条领域知识。
- domain: 领域名称 (如 "investment")
- fact: 知识点，简洁的一句话
- category: 分类标签 — concept / strategy / experience / reference / other
- 写入到 ## 知识条目 下的当前日期段落
- 如果领域不存在，自动创建
```

---

## 8. 配置

### 8.1 Pydantic 配置模型

```python
class KnowledgeConfig(BaseModel):
    enabled: bool = True
    storage_dir: str = "~/.vermilion-bird/knowledge"
    max_knowledge_tokens: int = 300          # system prompt 中的 token 预算
    extraction_interval: int = 20            # 每 N 轮对话触发提取
    consolidate_min_entries: int = 10        # 整合触发阈值
    refine_min_total: int = 50               # 提炼触发阈值
```

### 8.2 config.yaml 示例

```yaml
knowledge:
  enabled: true
  storage_dir: "~/.vermilion-bird/knowledge"
  max_knowledge_tokens: 300
  extraction_interval: 20
  consolidate_min_entries: 10
  refine_min_total: 50
```

---

## 9. 实现计划

| Phase | 内容 | 交付物 | 验证 |
|-------|------|--------|------|
| **1** | `KnowledgeStorage` — 目录扫描 + YAML frontmatter 解析 + 原子写入 + 追加知识点 + `DomainDetector` 关键词匹配 | `src/llm_chat/knowledge/storage.py` + `templates.py` | 单元测试：扫描空目录/有文件目录，解析 frontmatter，追加知识点，关键词匹配 |
| **2** | `knowledge_base` skill — `read_knowledge` + `remember_knowledge` 工具，注册到 SkillManager | `src/llm_chat/skills/knowledge_base/skill.py` | LLM 可调用两个工具读写领域知识 |
| **3** | `KnowledgeManager` + `KnowledgeExtractor` — 自动提取 + 整合 + 提炼 + system prompt 注入，管道集成 | `src/llm_chat/knowledge/manager.py` + `extractor.py` | 多轮对话后自动创建领域文件、提取知识点、触发整合 |

---

## 10. 与现有系统的关系

| 现有系统 | 关系 |
|---------|------|
| **MemoryManager** | 并行层。`process_pending_extractions()` 中新加一步 `_maybe_extract_domain_knowledge()`。`build_system_prompt()` 中新加 `KnowledgeManager.build_knowledge_context()` 注入 |
| **PromptSkill** | 格式对齐（YAML frontmatter + Markdown body + type 字段）。复用渐进式披露模式。领域文件本质是一种特殊的 PromptSkill（知识型而非指令型）|
| **SkillManager** | `knowledge_base` 作为内置 skill 注册到 `BUILTIN_SKILLS` |
| **ChatCore** | 修改 `_build_system_context()` 阶段，追加 KnowledgeManager 注入 |
| **ConversationManager** | 持有 KnowledgeManager 单例（类似 MemoryManager）|
| **Config** | 新增 `KnowledgeConfig` 节点 |
| **Storage (SQLite)** | 不新增表。领域知识纯文件存储，不依赖 SQLite |
