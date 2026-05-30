"""KnowledgeExtractor — LLM 驱动的领域知识提取。

职责：
- 从对话中提取领域知识点
- 检测新领域（自然涌现）
- 整合领域知识（去重 + 归类）
- 提炼领域知识（重写概述 + 重组章节 + 淘汰过时）
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, TYPE_CHECKING

import yaml
from llm_chat.knowledge.storage import CATEGORY_LABELS  # 单一来源

if TYPE_CHECKING:
    from llm_chat.memory.summarizer import Summarizer

logger = logging.getLogger(__name__)


class KnowledgeExtractor:
    """LLM 辅助的领域知识提取器。

    依赖 Summarizer (LLM client 抽象) 进行生成。
    """

    def __init__(self, summarizer: Optional["Summarizer"] = None):
        self._summarizer = summarizer

    # ------------------------------------------------------------------
    # 提取知识点
    # ------------------------------------------------------------------

    def extract_facts(
        self, messages: List[Dict], domain_display_name: str
    ) -> List[Dict]:
        """从对话中提取领域知识点。

        Args:
            messages: 对话消息列表 [{"role": "user/assistant", "content": "..."}]
            domain_display_name: 领域显示名，如 "投资"

        Returns:
            知识点列表: [{"fact": "...", "category": "strategy"}, ...]
            如果 LLM 不可用，返回空列表
        """
        if not self._summarizer or not messages:
            return []

        # 格式化对话（最近的消息，截断到 3000 字符）
        lines = []
        total = 0
        for msg in reversed(messages[-30:]):
            role = msg.get("role", "?")
            content = msg.get("content", "")[:300]
            if not content:
                continue
            line = f"[{role}]: {content}"
            if total + len(line) > 3000:
                break
            lines.append(line)
            total += len(line)
        conversation = "\n".join(reversed(lines))

        categories_desc = "\n".join(
            f"- {v} ({k}): 领域相关的{v}" for k, v in CATEGORY_LABELS.items()
        )

        prompt = f"""你是一个知识提取助手。从以下对话中提取关于「{domain_display_name}」领域的专业知识。

## 对话内容
{conversation}

## 提取要求
识别对话中涉及 {domain_display_name} 领域的专业知识，包括：
{categories_desc}

只提取明确讨论的内容，不要推测。每条知识点用一句话概括。
如果没有可提取的知识，返回空数组。

## 输出格式 (JSON array)
[
  {{"fact": "知识点描述", "category": "concept|strategy|experience|reference|other"}},
  ...
]

只返回 JSON，不要其他内容。"""

        try:
            response = self._summarizer.generate(prompt, max_tokens=500)
            if not response:
                return []

            # 解析 JSON
            facts = self._parse_json_list(response)
            if not facts:
                return []

            # 验证并过滤
            valid = []
            for item in facts:
                fact_text = item.get("fact", "")
                cat = item.get("category", "other")
                if fact_text and len(fact_text) >= 5:
                    if cat not in CATEGORY_LABELS:
                        cat = "other"
                    valid.append({"fact": fact_text, "category": cat})

            if valid:
                logger.info(
                    f"提取到 {len(valid)} 条 {domain_display_name} 领域知识"
                )
            return valid

        except Exception as e:
            logger.warning(f"提取 {domain_display_name} 知识失败: {e}")
            return []

    # ------------------------------------------------------------------
    # 检测新领域
    # ------------------------------------------------------------------

    def suggest_new_domain(
        self, messages: List[Dict]
    ) -> Optional[Dict]:
        """检测对话是否涉及一个新领域，并建议创建。

        Args:
            messages: 对话消息列表

        Returns:
            {"name": "domain_name", "display_name": "显示名",
             "description": "描述", "keywords": ["k1","k2"]}
            如果不建议创建，返回 None
        """
        if not self._summarizer or not messages:
            return None

        # 格式化对话
        lines = []
        total = 0
        for msg in reversed(messages[-20:]):
            content = msg.get("content", "")[:200]
            if not content:
                continue
            line = f"[{msg.get('role','?')}]: {content}"
            if total + len(line) > 2000:
                break
            lines.append(line)
            total += len(line)
        conversation = "\n".join(reversed(lines))

        prompt = f"""你是一个领域分类助手。分析以下对话，判断是否涉及一个特定的专业领域。

## 对话内容
{conversation}

## 任务
1. 判断这段对话是否集中讨论某个专业领域（如投资、机器学习、烹饪、摄影等）
2. 如果涉及闲聊、通用问答、或不集中的话题 → 返回 null
3. 如果是专业领域 → 建议创建该领域

## 输出格式 (JSON)
如果涉及专业领域:
{{
  "name": "english_identifier",
  "display_name": "中文显示名",
  "description": "一句话领域描述",
  "keywords": ["关键词1", "关键词2", ...]
}}

如果不涉及:
null

只返回 JSON 或 null，不要其他内容。"""

        try:
            response = self._summarizer.generate(prompt, max_tokens=300)
            if not response:
                return None

            # 检测 null
            if response.strip().lower() == "null":
                return None

            data = self._parse_json_dict(response)
            if not data:
                return None

            name = data.get("name", "")
            display_name = data.get("display_name", "")
            keywords = data.get("keywords", [])

            if name and display_name and len(keywords) >= 2:
                logger.info(
                    f"建议创建新领域: {display_name} ({name}), "
                    f"关键词: {keywords}"
                )
                return {
                    "name": name,
                    "display_name": display_name,
                    "description": data.get("description", ""),
                    "keywords": keywords,
                }
            return None

        except Exception as e:
            logger.warning(f"检测新领域失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 整合 — 去重 + 归类 (触发条件: 未整理条目 ≥ consolidate_min_entries)
    # ------------------------------------------------------------------

    def consolidate_domain(
        self, domain_content: str, domain_name: str
    ) -> Optional[str]:
        """整合领域知识：去重合并 + 重新归类到结构化章节。

        Args:
            domain_content: 领域文件的完整内容 (含 frontmatter)
            domain_name: 领域名（用于日志）

        Returns:
            整合后重建的完整文件内容，或 None (LLM 不可用/失败)
        """
        if not self._summarizer:
            return None

        from llm_chat.knowledge.storage import KnowledgeStorage

        # 分离 frontmatter 和 body
        fm, body = KnowledgeStorage._split_frontmatter(domain_content)

        # 提取「## 知识条目」中的原始条
        entry_match = re.search(
            r"## 知识条目.*?\n(.*?)(?=\n## |\n---|\Z)", body, re.DOTALL
        )
        if not entry_match:
            return None

        raw_entries = entry_match.group(1).strip()

        # 提取现有结构化章节
        concept = self._extract_section(body, "## 核心概念")
        strategy = self._extract_section(body, "## 策略与方法")
        experience = self._extract_section(body, "## 经验与教训")

        # 统计未整理条目数
        unconsolidated = re.findall(r"^- \[.+\]", raw_entries, re.MULTILINE)
        if len(unconsolidated) < 3:
            logger.debug(f"{domain_name}: 未整理条目 {len(unconsolidated)} < 3，跳过")
            return None

        prompt = f"""你是一个知识整理助手。请整理以下领域知识。

## 已有结构化知识
### 核心概念
{concept[:500] if concept else "(暂无)"}

### 策略与方法
{strategy[:500] if strategy else "(暂无)"}

### 经验与教训
{experience[:500] if experience else "(暂无)"}

## 待整理的知识条目 ({len(unconsolidated)} 条)
{raw_entries[:3000]}

## 任务
1. **去重合并**：语义完全相同的条目合并为一条。相近但不同 → 分别保留。
2. **归类**：将每条分配到：concept / strategy / experience / reference / other
3. **清理**：去掉 [概念][策略] 等标签，精炼表述，每条 ≤60 字
4. **冲突处理**：发现矛盾 → 保留两条，标注 "(较新)" 和 "(较早)"
5. 保留所有事实，不删除

## 输出格式 (JSON)
{{
  "concept": ["概念条目1", "概念条目2"],
  "strategy": ["策略条目1"],
  "experience": ["经验条目1"],
  "reference": ["参考条目1"],
  "other": ["其他条目1"]
}}

只返回 JSON，不要其他内容。"""

        try:
            response = self._summarizer.generate(prompt, max_tokens=1500)
            if not response:
                return None

            categorized = self._parse_json_dict(response)
            if not categorized:
                return None

            # 安全网：总输出条目数 < 输入 × 70% → 拒绝
            out_count = sum(
                len(v) for v in categorized.values() if isinstance(v, list)
            )
            if out_count < max(1, int(len(unconsolidated) * 0.7)):
                logger.warning(
                    f"{domain_name} 整合: 输出 {out_count} < {int(len(unconsolidated)*0.7)} (70%)，拒绝写入"
                )
                return None

            # 重建 body
            body = self._rebuild_consolidated_body(
                body, categorized, entry_match
            )

            # 更新 fact_count 和 updated_at
            fm["fact_count"] = out_count
            fm["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

            fm_yaml = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
            new_content = f"---\n{fm_yaml}---\n\n{body}"

            logger.info(f"{domain_name}: 整合完成 {len(unconsolidated)} → {out_count} 条")
            return new_content

        except Exception as e:
            logger.warning(f"{domain_name} 整合失败: {e}")
            return None

    def _rebuild_consolidated_body(
        self, body: str, categorized: Dict, entry_match: re.Match
    ) -> str:
        """用整合后的分类重建 body 的结构化章节。"""
        label_map = {
            "concept": "## 核心概念",
            "strategy": "## 策略与方法",
            "experience": "## 经验与教训",
            "reference": "## 资源与参考",
            "other": "## 其他",
        }

        # 构建各章节
        sections = []
        for cat_key, header in label_map.items():
            items = categorized.get(cat_key, [])
            if isinstance(items, list) and items:
                items_text = "\n".join(f"- {item}" for item in items)
                sections.append(f"{header}\n{items_text}")
            else:
                sections.append(f"{header}\n(待整理)")

        # 替换结构化章节区域（从 ## 核心概念 到 ## 知识条目 之前）
        concept_start = re.search(r"## 核心概念", body)
        entry_start = entry_match

        if concept_start and entry_start:
            before = body[: concept_start.start()]
            after = body[entry_start.start():]
            # 清空知识条目：保留标题+描述，清除旧条目
            after = re.sub(
                r"(## 知识条目[^\n]*).*",
                r"\1 (未整理)\n> 自动追加的原始知识点\n\n",
                after,
                flags=re.DOTALL,
            )
            body = before + "\n\n".join(sections) + "\n\n" + after
        else:
            # 找不到章节标记 → 在末尾追加
            body += "\n\n" + "\n\n".join(sections)

        return body

    # ------------------------------------------------------------------
    # 提炼 — 重写概述 + 重组 + 淘汰 (触发条件: fact_count ≥ refine_min_total)
    # ------------------------------------------------------------------

    def refine_domain(
        self, domain_content: str, domain_name: str
    ) -> Optional[str]:
        """提炼领域知识：重写概述、重组章节、淘汰过时知识。

        Args:
            domain_content: 领域文件完整内容
            domain_name: 领域名

        Returns:
            提炼后重建的完整文件内容，或 None
        """
        if not self._summarizer:
            return None

        from llm_chat.knowledge.storage import KnowledgeStorage

        fm, body = KnowledgeStorage._split_frontmatter(domain_content)

        # 提取概述
        overview = self._extract_section(body, "## 概述")
        # 提取所有结构化章节
        concept = self._extract_section(body, "## 核心概念")
        strategy = self._extract_section(body, "## 策略与方法")
        experience = self._extract_section(body, "## 经验与教训")

        prompt = f"""你是一个知识提炼助手。请提炼以下领域知识。

## 当前概述
{overview[:300] if overview else "(待生成)"}

## 核心概念
{concept[:800] if concept else "(暂无)"}

## 策略与方法
{strategy[:800] if strategy else "(暂无)"}

## 经验与教训
{experience[:800] if experience else "(暂无)"}

## 任务
1. **重写概述**：生成一段 50-150 字的领域总览
2. **重组章节**：如果某章节超过 6 条，考虑拆分子章节 (如 ## 核心概念 / ### 术语，### 原理)
3. **淘汰过时**：识别明显过时的知识 → 标记为 "(历史归档)"
4. **更新描述**：生成一句更新后的 frontmatter description

## 输出格式 (JSON)
{{
  "overview": "新的概述段落",
  "concept": ["条目1", "条目2"],
  "strategy": ["条目1"],
  "experience": ["条目1", {"fact": "条目2", "note": "历史归档"}],
  "description": "更新后的领域描述",
  "restructured": false,
  "new_subsections": []
}}

说明：
- 如果要分拆章节，restructured = true，new_subsections = ["术语定义", "核心原理"]
- experience 中的历史归档用 {{"fact": "...", "note": "历史归档"}} 表示
- 只返回 JSON，不要其他内容。"""

        try:
            response = self._summarizer.generate(prompt, max_tokens=1500)
            if not response:
                return None

            refined = self._parse_json_dict(response)
            if not refined:
                return None

            new_overview = refined.get("overview", "")
            new_description = refined.get("description", "")

            # 安全网：概述过短 → 拒绝
            if new_overview and len(new_overview) < 20:
                logger.warning(f"{domain_name} 提炼: 概述过短 ({len(new_overview)} chars)，跳过")
                return None

            # 重建 body
            body = self._rebuild_refined_body(
                body, refined, new_overview
            )

            # 更新 frontmatter
            if new_description:
                fm["description"] = new_description
            fm["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

            fm_yaml = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
            new_content = f"---\n{fm_yaml}---\n\n{body}"

            logger.info(f"{domain_name}: 提炼完成 (概述 {len(new_overview)} chars)")
            return new_content

        except Exception as e:
            logger.warning(f"{domain_name} 提炼失败: {e}")
            return None

    def _rebuild_refined_body(
        self, body: str, refined: Dict, new_overview: str
    ) -> str:
        """用提炼后的内容重建 body。"""
        # 替换概述
        if new_overview:
            overview_match = re.search(r"## 概述\n.*?(?=\n##|\Z)", body, re.DOTALL)
            if overview_match:
                body = body.replace(overview_match.group(0), f"## 概述\n{new_overview}")
            else:
                # 在 # 领域知识 之后插入
                first_h1 = re.search(r"# .*\n", body)
                if first_h1:
                    insert = first_h1.end()
                    body = body[:insert] + f"\n## 概述\n{new_overview}\n" + body[insert:]

        # 更新结构化章节
        label_map = {
            "concept": "## 核心概念",
            "strategy": "## 策略与方法",
            "experience": "## 经验与教训",
            "reference": "## 资源与参考",
        }
        for cat_key, header in label_map.items():
            items = refined.get(cat_key, [])
            if not isinstance(items, list) or not items:
                continue
            # 构建章节内容（处理历史归档标记）
            item_lines = []
            for item in items:
                if isinstance(item, dict):
                    fact_text = item.get("fact", "")
                    note = item.get("note", "")
                    line = f"- {fact_text}"
                    if note:
                        line += f" *({note})*"
                    item_lines.append(line)
                elif isinstance(item, str):
                    item_lines.append(f"- {item}")
            if item_lines:
                new_section = f"{header}\n" + "\n".join(item_lines)
                # 替换已有章节
                section_match = re.search(
                    rf"{re.escape(header)}\n.*?(?=\n## |\n---|\Z)", body, re.DOTALL
                )
                if section_match:
                    body = body.replace(section_match.group(0), new_section)
                else:
                    body += f"\n\n{new_section}"

        return body

    # ------------------------------------------------------------------
    # JSON 解析工具
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_list(text: str) -> List:
        """从 LLM 响应中解析 JSON 数组，容错处理。"""
        json_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        # 直接尝试解析
        try:
            result = json.loads(text.strip())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass
        return []

    @staticmethod
    def _parse_json_dict(text: str) -> Dict:
        """从 LLM 响应中解析 JSON 对象，容错处理。"""
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        try:
            result = json.loads(text.strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
        return {}

    @staticmethod
    def _extract_section(content: str, header: str) -> str:
        """从 Markdown 提取指定 H2 章节的内容。"""
        pattern = rf"{re.escape(header)}\n(.*?)(?=\n## |\Z)"
        match = re.search(pattern, content, re.DOTALL)
        return match.group(1).strip() if match else ""
