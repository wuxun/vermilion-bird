"""KnowledgeStorage — 领域知识文件 I/O + DomainDetector — 关键词匹配。

领域知识文件格式: YAML frontmatter + Markdown body (对齐 PromptSkill SKILL.md)。
每个文件 = 一个领域，存储在 ~/.vermilion-bird/knowledge/{name}.md。
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from llm_chat.knowledge.templates import get_knowledge_template

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DomainMeta — frontmatter 解析结果
# ---------------------------------------------------------------------------


@dataclass
class DomainMeta:
    """从 knowledge.md 的 YAML frontmatter 解析出的领域元数据。"""

    name: str
    display_name: str = ""
    description: str = ""
    type: str = "requested"  # always | requested | manual
    keywords: List[str] = field(default_factory=list)
    file_path: Path = field(default_factory=Path)
    fact_count: int = 0
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_frontmatter(
        cls, data: Dict, file_path: Path
    ) -> "DomainMeta":
        """从解析后的 YAML 字典构造 DomainMeta。"""
        return cls(
            name=data.get("name", file_path.stem),
            display_name=data.get("display_name", data.get("name", "")),
            description=data.get("description", ""),
            type=data.get("type", "requested"),
            keywords=data.get("keywords", []),
            file_path=file_path,
            fact_count=data.get("fact_count", 0),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def to_frontmatter_dict(self) -> Dict:
        """序列化为 YAML frontmatter 字典。"""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "type": self.type,
            "keywords": self.keywords,
            "fact_count": self.fact_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# KnowledgeStorage
# ---------------------------------------------------------------------------


# 知识点分类标签（单一来源，各模块导入）
CATEGORY_LABELS = {
    "concept": "概念",
    "strategy": "策略",
    "experience": "经验",
    "reference": "参考",
    "other": "其他",
}


# ---------------------------------------------------------------------------
# KnowledgeStorage
# ---------------------------------------------------------------------------


class KnowledgeStorage:
    """领域知识文件存储管理器。

    职责：
    - 扫描 knowledge/ 目录发现领域
    - 解析 YAML frontmatter → DomainMeta
    - 原子写入 (tempfile + rename)
    - 追加知识点到 ## 知识条目 章节
    - 全文搜索

    与 MemoryStorage 并行，但更简单：
    - 无分层 (short/mid/long)，领域知识只有一层
    - 生命周期由数量阈值驱动，非时间衰减
    """

    def __init__(self, knowledge_dir: str = "~/.vermilion-bird/knowledge"):
        self.knowledge_dir = Path(knowledge_dir).expanduser()
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)

        # 懒加载的领域缓存
        self._domains: Optional[Dict[str, DomainMeta]] = None

    # ------------------------------------------------------------------
    # 发现与加载
    # ------------------------------------------------------------------

    def discover_domains(self) -> Dict[str, DomainMeta]:
        """扫描 knowledge/ 目录，解析所有 .md 文件的 frontmatter。

        Returns:
            {domain_name: DomainMeta} 字典。
            文件名 stem 作为 key (如 investment.md → "investment")。
        """
        domains: Dict[str, DomainMeta] = {}
        if not self.knowledge_dir.exists():
            return domains

        for entry in sorted(self.knowledge_dir.iterdir()):
            if not entry.is_file() or entry.suffix != ".md":
                continue
            if entry.name.startswith(".") or entry.name.startswith("_"):
                continue

            try:
                meta = self._parse_domain_file(entry)
                if meta and meta.name:
                    domains[meta.name] = meta
            except Exception as e:
                logger.warning(f"跳过无效领域文件 {entry}: {e}")

        self._domains = domains
        logger.debug(f"发现 {len(domains)} 个领域: {list(domains.keys())}")
        return domains

    def _parse_domain_file(self, file_path: Path) -> Optional[DomainMeta]:
        """解析单个 .md 文件的 YAML frontmatter。"""
        raw = file_path.read_text(encoding="utf-8")
        frontmatter, _ = self._split_frontmatter(raw)
        if not frontmatter:
            logger.debug(f"{file_path.name}: 无 frontmatter，跳过")
            return None
        return DomainMeta.from_frontmatter(frontmatter, file_path)

    @staticmethod
    def _split_frontmatter(text: str) -> Tuple[Dict, str]:
        """分离 YAML frontmatter 和 body。

        Returns:
            (frontmatter_dict, body_text)
        """
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, re.DOTALL)
        if not match:
            return {}, text.strip()
        try:
            fm = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            logger.warning("无效 YAML frontmatter")
            return {}, text.strip()
        return fm, match.group(2).strip()

    def _ensure_domains(self) -> Dict[str, DomainMeta]:
        """确保领域缓存已加载。"""
        if self._domains is None:
            self.discover_domains()
        return self._domains or {}

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def load_domain(self, name: str) -> Optional[str]:
        """加载领域知识文件的完整内容。

        Args:
            name: 领域标识符 (如 "investment")

        Returns:
            文件全文 (含 frontmatter)，领域不存在返回 None
        """
        file_path = self._resolve_path(name)
        if not file_path.exists():
            return None
        return file_path.read_text(encoding="utf-8")

    def load_domain_body(self, name: str) -> Optional[str]:
        """加载领域知识文件的 body 部分（不含 frontmatter）。

        用于 system prompt 注入或 LLM 工具返回。
        """
        content = self.load_domain(name)
        if content is None:
            return None
        _, body = self._split_frontmatter(content)
        return body

    def get_domain_meta(self, name: str) -> Optional[DomainMeta]:
        """获取领域的元数据（从 frontmatter 解析）。"""
        domains = self._ensure_domains()
        return domains.get(name)

    def get_all_domains(self) -> Dict[str, DomainMeta]:
        """获取所有已发现的领域元数据。"""
        return self._ensure_domains()

    def domain_exists(self, name: str) -> bool:
        """检查领域是否存在。"""
        return self._resolve_path(name).exists()

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def _resolve_path(self, name: str) -> Path:
        """将领域名解析为文件路径。"""
        # 安全：只取 stem，防止路径遍历
        safe_name = Path(name).stem
        return self.knowledge_dir / f"{safe_name}.md"

    def save_domain(self, name: str, content: str) -> None:
        """保存领域文件（全量原子写入）。"""
        file_path = self._resolve_path(name)
        self._atomic_write(file_path, content)
        logger.info(f"保存领域知识: {name}")
        # 刷新缓存
        self._domains = None

    def _atomic_write(self, file_path: Path, content: str) -> None:
        """原子写入 — 先写临时文件再 rename，防止并发读取到撕裂文件。

        对齐 MemoryStorage._atomic_write 的实现。
        """
        tmp_fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix=file_path.name + ".",
            dir=file_path.parent,
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, file_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _rebuild_file(self, meta: Optional[DomainMeta] = None, body: str = "", fm: Optional[Dict] = None) -> str:
        """根据 DomainMeta 或 fm dict 重建完整的 .md 内容。

        Args:
            meta: DomainMeta 对象（默认路径）
            body: markdown body 文本
            fm: frontmatter dict（fallback，meta 为 None 时使用）
        """
        if meta is not None:
            fm_dict = meta.to_frontmatter_dict()
        elif fm is not None:
            fm_dict = fm
        else:
            raise ValueError("meta or fm must be provided")
        fm_yaml = yaml.dump(fm_dict, allow_unicode=True, default_flow_style=False, sort_keys=False)
        return f"---\n{fm_yaml}---\n\n{body}"

    # ------------------------------------------------------------------
    # 创建领域
    # ------------------------------------------------------------------

    def create_domain(
        self,
        name: str,
        display_name: str,
        description: str = "",
        keywords: Optional[List[str]] = None,
        type: str = "requested",
    ) -> DomainMeta:
        """创建一个新的领域知识文件。

        Args:
            name: 领域标识符 (英文，如 "investment")
            display_name: 领域显示名 (中文，如 "投资")
            description: 一句话描述
            keywords: 初始关键词列表
            type: 加载模式 "always" / "requested" / "manual"

        Returns:
            新领域的 DomainMeta

        Raises:
            FileExistsError: 领域已存在
        """
        file_path = self._resolve_path(name)
        if file_path.exists():
            raise FileExistsError(f"领域 '{name}' 已存在: {file_path}")

        content = get_knowledge_template(
            name=name,
            display_name=display_name,
            description=description,
            keywords=keywords,
            type=type,
        )

        self._atomic_write(file_path, content)
        logger.info(f"创建新领域: {display_name} ({name})")

        # 刷新缓存
        self._domains = None
        return self._parse_domain_file(file_path)

    # ------------------------------------------------------------------
    # 追加知识点
    # ------------------------------------------------------------------

    def append_fact(
        self,
        name: str,
        fact: str,
        category: str = "other",
    ) -> bool:
        """向领域文件的「## 知识条目」章节追加一条知识点。

        按日期分组，格式：
            ### 2026-05-30
            - [策略] 知识点内容

        Args:
            name: 领域标识符
            fact: 知识点内容（一句话）
            category: 分类 — concept / strategy / experience / reference / other

        Returns:
            True 追加成功，False 领域不存在
        """
        content = self.load_domain(name)
        if content is None:
            logger.warning(f"领域 '{name}' 不存在，无法追加知识点")
            return False

        _, body = self._split_frontmatter(content)

        today = datetime.now().strftime("%Y-%m-%d")
        label = CATEGORY_LABELS.get(category, category)
        tagged_fact = f"[{label}] {fact}"

        # 查找 ## 知识条目 章节
        entry_section = re.search(r"## 知识条目.*", body)
        if not entry_section:
            # 章节不存在 — 在末尾追加
            body += f"\n\n## 知识条目 (未整理)\n> 自动追加的原始知识点\n\n### {today}\n- {tagged_fact}\n"
        else:
            section_start = entry_section.start()
            section_body = body[section_start:]

            # 查找今天的日期标题（允许 EOF 无换行）
            today_pattern = rf"### {re.escape(today)}(?:\n|$)"
            today_match = re.search(today_pattern, section_body)

            if today_match:
                # 在今天的日期段末尾追加
                insert_pos = section_start + today_match.end()
                # 找到这个日期段中最后一个非空行之后的换行
                remaining = body[insert_pos:]
                next_section = re.search(r"\n### |\n---|\Z", remaining)
                if next_section:
                    cut = next_section.start()
                    body = (
                        body[: insert_pos + cut]
                        + f"- {tagged_fact}\n"
                        + body[insert_pos + cut :]
                    )
                else:
                    body = body[:insert_pos] + f"- {tagged_fact}\n" + body[insert_pos:]
            else:
                # 今天的日期段不存在 — 在 ## 知识条目 之后插一个新日期段
                # 找到章节标题后的第一个内容行
                insert_pos = section_start + len("## 知识条目")
                # 跳过标题后的描述行和空行
                remaining = body[insert_pos:]
                first_content = re.search(r"\n\S", remaining)
                if first_content:
                    insert_pos += first_content.start() + 1
                else:
                    insert_pos = len(body)
                body = (
                    body[:insert_pos]
                    + f"\n### {today}\n- {tagged_fact}\n"
                    + body[insert_pos:]
                )

        # 构建新内容（先计算增量 count，不修改缓存）
        # 安全：先失效缓存再写文件，写失败则下次重新加载
        meta = self.get_domain_meta(name)
        self._domains = None
        if meta:
            meta.fact_count += 1
            meta.updated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            new_content = self._rebuild_file(meta=meta, body=body)
        else:
            fm, _ = self._split_frontmatter(content)
            fm["fact_count"] = fm.get("fact_count", 0) + 1
            fm["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            new_content = self._rebuild_file(fm=fm, body=body)

        self._atomic_write(self._resolve_path(name), new_content)
        logger.info(f"追加知识点 [{label}] → {name}: {fact[:80]}...")
        return True

    def get_unconsolidated_count(self, name: str) -> int:
        """获取「## 知识条目」章节中未整理的条目数。

        用于判断是否触发整合 (≥ consolidate_min_entries)。
        """
        content = self.load_domain(name)
        if content is None:
            return 0

        _, body = self._split_frontmatter(content)

        # 提取 ## 知识条目 章节
        entry_match = re.search(
            r"## 知识条目.*?\n(.*?)(?=\n## |\n---|\Z)", body, re.DOTALL
        )
        if not entry_match:
            return 0

        section = entry_match.group(1)
        # 统计所有以 "- [" 开头的行
        facts = re.findall(r"^- \[.+\]", section, re.MULTILINE)
        return len(facts)

    # ------------------------------------------------------------------
    # 更新 frontmatter
    # ------------------------------------------------------------------

    def update_frontmatter(self, name: str, updates: Dict) -> bool:
        """更新领域文件的 frontmatter 字段。

        Args:
            name: 领域标识符
            updates: 要更新的字段字典，如 {"fact_count": 15, "keywords": [...]}

        Returns:
            True 更新成功，False 领域不存在
        """
        content = self.load_domain(name)
        if content is None:
            return False

        fm, body = self._split_frontmatter(content)
        fm.update(updates)
        fm_yaml = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
        new_content = f"---\n{fm_yaml}---\n\n{body}"

        self.save_domain(name, new_content)
        logger.debug(f"更新 {name} frontmatter: {list(updates.keys())}")
        return True

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------

    def search(self, query: str) -> List[Dict]:
        """在所有领域文件中搜索关键词。

        Args:
            query: 搜索关键词（不区分大小写）

        Returns:
            匹配结果列表: [{"domain": "investment", "matches": ["匹配行...", ...]}, ...]
        """
        results = []
        query_lower = query.lower()

        for name, meta in self._ensure_domains().items():
            content = meta.file_path.read_text(encoding="utf-8")
            if query_lower in content.lower():
                # 提取匹配行 (保留上下文1行)
                lines = content.split("\n")
                match_lines = []
                for i, line in enumerate(lines):
                    if query_lower in line.lower():
                        start = max(0, i - 1)
                        end = min(len(lines), i + 2)
                        context = "\n".join(lines[start:end])
                        match_lines.append(context)
                results.append(
                    {
                        "domain": name,
                        "display_name": meta.display_name,
                        "matches": match_lines[:10],  # 最多 10 处匹配
                    }
                )

        return results

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------

    def delete_domain(self, name: str) -> bool:
        """删除领域文件。

        Args:
            name: 领域标识符

        Returns:
            True 删除成功，False 领域不存在
        """
        file_path = self._resolve_path(name)
        if not file_path.exists():
            return False
        file_path.unlink()
        logger.info(f"删除领域: {name}")
        self._domains = None
        return True


# ---------------------------------------------------------------------------
# DomainDetector — 轻量关键词匹配 (不调 LLM)
# ---------------------------------------------------------------------------


class DomainDetector:
    """轻量领域检测器 — 基于关键词表匹配文本涉及的领域。

    不调用 LLM，用于：
    - 自动提取时判断对话涉及哪些领域
    - build_system_prompt 时判断当前消息涉及哪些领域
    """

    def __init__(self, storage: KnowledgeStorage):
        self._storage = storage

    def match(self, text: str) -> List[Tuple[str, int]]:
        """检测文本匹配哪些领域及其命中次数。

        Args:
            text: 待检测文本 (用户消息、对话摘要等)

        Returns:
            [(domain_name, hit_count), ...] 按命中次数降序排列
        """
        if not text:
            return []

        domains = self._storage.get_all_domains()
        if not domains:
            return []

        results: List[Tuple[str, int]] = []
        text_lower = text.lower()

        for name, meta in domains.items():
            if not meta.keywords:
                continue
            hits = 0
            for kw in meta.keywords:
                if kw.lower() in text_lower:
                    hits += 1
            if hits > 0:
                results.append((name, hits))

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def match_domains(
        self, text: str, min_hits: int = 1
    ) -> List[str]:
        """返回匹配的领域名列表 (至少命中 min_hits 个关键词)。

        Args:
            text: 待检测文本
            min_hits: 最少命中关键词数

        Returns:
            领域名列表，按命中次数降序
        """
        matched = self.match(text)
        return [name for name, hits in matched if hits >= min_hits]
