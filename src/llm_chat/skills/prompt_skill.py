"""
PromptSkill — 基于 Agent Skills 标准 (agentskills.io) 的提示词技能。

与 CodeSkill (BaseSkill) 互补：
- CodeSkill: Python 类 → 注册 BaseTool → LLM 工具调用
- PromptSkill: SKILL.md → system prompt 注入 → 领域知识/指令/工作流

标准格式 (SKILL.md):
---
name: my-skill
description: 技能描述（触发时匹配用）
type: always | requested | manual   # 默认 requested
---

# 技能标题

具体的指令、知识、示例...
"""

from __future__ import annotations

import os
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

@dataclass
class PromptSkillManifest:
    """从 SKILL.md 头解析出的元数据。"""
    name: str
    description: str = ""
    type: str = "requested"  # always | requested | manual
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, data: Dict[str, Any], defaults: Optional[Dict[str, Any]] = None) -> "PromptSkillManifest":
        defaults = defaults or {}
        return cls(
            name=data.get("name", defaults.get("name", "")),
            description=data.get("description", defaults.get("description", "")),
            type=data.get("type", defaults.get("type", "requested")),
            version=data.get("version", defaults.get("version", "1.0.0")),
            author=data.get("author", defaults.get("author", "")),
            tags=data.get("tags", defaults.get("tags", [])),
        )


# ---------------------------------------------------------------------------
# PromptSkill
# ---------------------------------------------------------------------------

class PromptSkill:
    """提示词技能 — 不包含代码，只注入知识/指令到 system prompt。

    三种加载模式：
    - always:    每次对话都注入（适合编码规范、品牌语调等）
    - requested: LLM 判定需要时从 system prompt 列表中选择加载
    - manual:    仅用户 `/skill:name` 显式触发

    渐进式加载 (progressive disclosure):
    1. 始终在上下文: name + description (一行)
    2. on-demand:   SKILL.md 全文 (由 ChatCore 根据 requested/manual 触发)
    """

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.manifest: Optional[PromptSkillManifest] = None
        self._body: str = ""
        self._loaded = False

    # -- properties -----------------------------------------------------------

    @property
    def name(self) -> str:
        return self.manifest.name if self.manifest else self.path.name

    @property
    def description(self) -> str:
        return self.manifest.description if self.manifest else ""

    # -- load -----------------------------------------------------------------

    def load(self) -> bool:
        """解析 SKILL.md 文件，提取 frontmatter 和正文。"""
        skill_md = self.path / "SKILL.md"
        if not skill_md.exists():
            skill_md = self.path / "skill.md"
        if not skill_md.exists():
            logger.warning(f"PromptSkill '{self.name}' has no SKILL.md")
            return False

        try:
            raw = skill_md.read_text(encoding="utf-8")
            frontmatter, body = self._parse_frontmatter(raw)
            self.manifest = PromptSkillManifest.from_yaml(frontmatter)
            if not self.manifest.name:
                self.manifest.name = self.path.name
            self._body = body.strip()
            self._loaded = True
            logger.debug(f"Loaded PromptSkill '{self.name}' ({len(self._body)} chars)")
            return True
        except Exception as e:
            logger.error(f"Failed to parse {skill_md}: {e}")
            return False

    def get_content(self) -> str:
        """返回完整的 prompt 内容（注入到 system prompt 时使用）。"""
        if not self._loaded:
            self.load()
        if not self._body:
            return ""
        return f"# Skill: {self.name}\n{self._body}"

    def get_summary(self) -> str:
        """返回一行摘要（始终在上下文中的那部分）。"""
        if not self._loaded:
            self.load()
        return f"- {self.name}: {self.description}"

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple:
        """解析 YAML frontmatter (--- ... ---)。

        Returns: (frontmatter_dict, body_text)
        """
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)', text, re.DOTALL)
        if not match:
            # No frontmatter → treat entire file as body
            return {}, text.strip()
        try:
            fm = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            logger.warning("Invalid YAML frontmatter, treating as plain text")
            return {}, text.strip()
        return fm, match.group(2).strip()

    # -- discover -------------------------------------------------------------

    @staticmethod
    def discover(root: Path) -> List[PromptSkill]:
        """从目录递归发现所有包含 SKILL.md 的子目录。

        Args:
            root: 技能目录根（如 ~/.vermilion-bird/skills/）

        Returns:
            PromptSkill 列表（尚未加载，懒加载）
        """
        skills = []
        if not root.exists():
            return skills
        for entry in root.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                skill_md = entry / "SKILL.md"
                if not skill_md.exists():
                    skill_md = entry / "skill.md"
                if skill_md.exists():
                    skills.append(PromptSkill(entry))
            elif entry.is_file() and entry.suffix == '.md' and not entry.name.startswith('.'):
                # 直接 .md 文件也是有效的 skill（pi 模式）
                skills.append(PromptSkill(entry.parent))
        return skills


# ---------------------------------------------------------------------------
# Installer (CLI 下载)
# ---------------------------------------------------------------------------

def install_skill(url_or_path: str, target_dir: Optional[Path] = None) -> Optional[PromptSkill]:
    """从 URL (GitHub raw/Gist/本地路径) 安装 skill。

    支持格式:
    - GitHub 仓库: owner/repo[/path]  → 从 raw.githubusercontent.com 下载
    - 直接 URL:    https://.../SKILL.md
    - 本地路径:    /path/to/skill/

    Args:
        url_or_path: 技能来源
        target_dir:  安装目标目录（默认 ~/.vermilion-bird/skills/）

    Returns:
        安装成功返回 PromptSkill，失败返回 None
    """
    import urllib.request
    import json

    target_dir = target_dir or (Path.home() / ".vermilion-bird" / "skills")
    target_dir.mkdir(parents=True, exist_ok=True)

    skill_name = None
    md_content = None

    # 1. GitHub shorthand: owner/repo[/path]
    if re.match(r'^[\w.-]+/[\w.-]+', url_or_path) and not url_or_path.startswith(('http', '/', '.')):
        parts = url_or_path.split('/')
        owner, repo = parts[0], parts[1]
        subpath = '/'.join(parts[2:]) if len(parts) > 2 else ''
        # Try GitHub API to get default branch
        try:
            api_url = f"https://api.github.com/repos/{owner}/{repo}"
            req = urllib.request.Request(api_url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                branch = data.get("default_branch", "main")
        except Exception:
            branch = "main"

        skill_path = f"{subpath}/SKILL.md" if subpath else "SKILL.md"
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{skill_path}"
        skill_name = subpath.split('/')[-1] if subpath else repo
        logger.info(f"GitHub skill: {owner}/{repo} → {url}")

    # 2. Direct URL
    elif url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        url = url_or_path
        # Extract name from URL
        name_match = re.search(r'/([^/]+)/SKILL\.md$', url) or re.search(r'/([^/]+?)(?:\.git)?/?$', url)
        skill_name = name_match.group(1) if name_match else "downloaded_skill"

    # 3. Local path
    else:
        src = Path(url_or_path).expanduser().resolve()
        if src.is_dir() and (src / "SKILL.md").exists():
            md_content = (src / "SKILL.md").read_text(encoding="utf-8")
            skill_name = src.name
        elif src.is_file() and src.suffix == '.md':
            md_content = src.read_text(encoding="utf-8")
            skill_name = src.stem
        else:
            logger.error(f"Not a valid skill source: {url_or_path}")
            return None

    # Download if needed
    if md_content is None:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "vermilion-bird"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                md_content = resp.read().decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return None

    # Parse frontmatter for name
    match = re.match(r'^---\s*\n(.*?)\n---', md_content, re.DOTALL)
    if match:
        try:
            fm = yaml.safe_load(match.group(1))
            if fm and fm.get('name'):
                skill_name = fm['name']
        except yaml.YAMLError:
            pass

    skill_name = skill_name or "unnamed_skill"
    skill_dir = target_dir / skill_name
    skill_dir.mkdir(exist_ok=True)

    (skill_dir / "SKILL.md").write_text(md_content, encoding="utf-8")
    logger.info(f"Skill '{skill_name}' installed to {skill_dir}")

    skill = PromptSkill(skill_dir)
    skill.load()
    return skill
