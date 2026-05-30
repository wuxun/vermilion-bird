"""知识领域文件模板 — YAML frontmatter + Markdown body.

对齐 PromptSkill 的 SKILL.md 格式，便于渐进式披露。
"""

from datetime import datetime


KNOWLEDGE_TEMPLATE = """---
name: {name}
display_name: {display_name}
description: {description}
type: {type}
keywords: {keywords}
created_at: "{created_at}"
updated_at: "{updated_at}"
fact_count: 0
---

# 领域知识：{display_name}

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
"""


def get_knowledge_template(
    name: str,
    display_name: str,
    description: str = "",
    keywords: list[str] | None = None,
    type: str = "requested",
) -> str:
    """生成领域知识文件的初始模板。

    Args:
        name: 领域标识符 (英文，如 "investment")
        display_name: 领域显示名 (中文，如 "投资")
        description: 一句话描述
        keywords: 初始关键词列表 (用于 DomainDetector 匹配)
        type: 加载模式 — "always" / "requested" / "manual"

    Returns:
        完整的 knowledge.md 内容 (含 YAML frontmatter)
    """
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    kw_list = keywords or []

    # YAML 序列化关键词列表
    if kw_list:
        import yaml as _yaml
        kw_yaml = _yaml.dump(kw_list, default_flow_style=True, allow_unicode=True).strip()
    else:
        kw_yaml = "[]"

    return KNOWLEDGE_TEMPLATE.format(
        name=name,
        display_name=display_name,
        description=description,
        type=type,
        keywords=kw_yaml,
        created_at=now,
        updated_at=now,
    )
