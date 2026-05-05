"""Decision Engine — 将 LLM 输出转化为结构化决策卡片。

职责:
    1. 生成结构化 prompt → LLM 产出 JSON 格式决策卡片
    2. 解析 LLM 响应为 DecisionCard
    3. 直接构建卡片（当调用方已有结构化数据时）

用法:
    engine = DecisionEngine(llm_client)
    card = engine.generate_card(
        topic="如何优化支付接口延迟",
        context="P99 从 200ms 升到 450ms",
        num_options=3,
    )
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from llm_chat.decision.schema import (
    CardType,
    DecisionCard,
    DecisionOption,
)

logger = logging.getLogger(__name__)

# ── Prompt 模板 ──────────────────────────────────────────────────────

CARD_GENERATION_PROMPT = """你正在生成一张「决策卡片」，帮助用户做选择。

## 卡片格式
请输出一个 JSON 对象，格式如下：
{{
    "title": "卡片标题 — 一句话概括需要决策的问题",
    "context": "背景摘要（1-3 行，说明为什么需要做这个决策）",
    "options": [
        {{
            "id": "A",
            "label": "选项名称（简短，如 '连接池扩容'）",
            "description": "详细说明",
            "expected_effect": "预期效果",
            "risk": "风险描述",
            "confidence": 0.92
        }},
        ...
    ],
    "recommendation": "推荐选项的 id，如 'A'",
    "sources": ["来源 1", "来源 2"]
}}

## 要求
1. 提供 {num_options} 个选项，每个选项的 id 依次为 A, B, C...
2. 每个选项的 confidence 为 0.0~1.0 之间的浮点数
3. recommendation 必须指向 confidence 最高的选项
4. 不要建议用户无法直接做的选项（如"重构整个系统"）
5. 每个选项应该是具体、可执行的行动

## 上下文
用户关注的主题: {topic}
{context_block}
请只在输出中包含 JSON 对象，不要其他文字。"""


class DecisionEngine:
    """决策引擎。

    通过 LLM 生成结构化决策卡片。
    """

    def __init__(self, llm_client: Any):
        self._client = llm_client

    # ── 公开 API ────────────────────────────────────────────────────

    def generate_card(
        self,
        topic: str,
        context: Optional[str] = None,
        num_options: int = 3,
        card_type: CardType = CardType.DECISION,
        conversation_id: Optional[str] = None,
    ) -> DecisionCard:
        """使用 LLM 生成一张决策卡片。

        Args:
            topic: 决策主题。
            context: 背景上下文。
            num_options: 选项数量 (2-4)。
            card_type: 卡片类型。
            conversation_id: 关联的对话 ID。

        Returns:
            生成的 DecisionCard。

        Raises:
            ValueError: LLM 输出无法解析为有效卡片。
        """
        context_block = ""
        if context:
            context_block = f"额外背景信息:\n{context}\n"

        prompt = CARD_GENERATION_PROMPT.format(
            topic=topic,
            context_block=context_block,
            num_options=min(max(num_options, 2), 4),
        )

        response = self._client.chat(
            message=prompt,
            temperature=0.4,
            max_tokens=2000,
        )

        card = self._parse_response(response, card_type, conversation_id)
        return card

    def card_from_structured(
        self,
        title: str,
        options: List[Dict[str, Any]],
        context: Optional[str] = None,
        recommendation: Optional[str] = None,
        sources: Optional[List[str]] = None,
        card_type: CardType = CardType.DECISION,
        conversation_id: Optional[str] = None,
    ) -> DecisionCard:
        """从结构化数据直接构建卡片（无需 LLM 调用）。

        Args:
            title: 卡片标题。
            options: 选项字典列表，每项需包含 id/label/confidence。
            context: 背景摘要。
            recommendation: 推荐选项 ID。
            sources: 信息来源。
            card_type: 卡片类型。
            conversation_id: 关联对话 ID。

        Returns:
            构建的 DecisionCard。
        """
        opts = []
        for o in options:
            opts.append(DecisionOption(**o))

        if recommendation is None:
            # 默认选置信度最高的
            best = max(opts, key=lambda o: o.confidence)
            recommendation = best.id

        return DecisionCard(
            card_type=card_type,
            title=title,
            context=context,
            options=opts,
            recommendation=recommendation,
            sources=sources or [],
            conversation_id=conversation_id,
        )

    # ── 内部实现 ────────────────────────────────────────────────────

    def _parse_response(
        self,
        response: str,
        card_type: CardType = CardType.DECISION,
        conversation_id: Optional[str] = None,
    ) -> DecisionCard:
        """解析 LLM 的 JSON 响应为 DecisionCard。"""
        text = response.strip()

        # 尝试提取 JSON 块 (```json ... ```)
        if "```json" in text:
            text = text.split("```json", 1)[1]
            if "```" in text:
                text = text.split("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1]
            if "```" in text:
                text = text.split("```", 1)[0]

        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"LLM 输出不是有效 JSON: {e}\n原始输出: {response[:500]}"
            )

        errors = self._validate_data(data)
        if errors:
            raise ValueError(
                f"卡片数据不完整: {', '.join(errors)}\n解析数据: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}"
            )

        options = []
        for o in data["options"]:
            options.append(DecisionOption(
                id=o["id"],
                label=o["label"],
                description=o.get("description"),
                expected_effect=o.get("expected_effect"),
                risk=o.get("risk"),
                confidence=float(o.get("confidence", 0.5)),
            ))

        return DecisionCard(
            card_type=card_type,
            title=data["title"],
            context=data.get("context"),
            options=options,
            recommendation=data.get("recommendation"),
            sources=data.get("sources", []),
            conversation_id=conversation_id,
        )

    @staticmethod
    def _validate_data(data: Dict[str, Any]) -> List[str]:
        """验证解析后的数据是否满足卡片必填项。"""
        errors = []
        if not data.get("title"):
            errors.append("缺少 title")
        if not data.get("options"):
            errors.append("缺少 options")
        else:
            if len(data["options"]) < 2:
                errors.append("选项至少需要 2 个")
            for i, o in enumerate(data["options"]):
                if not o.get("id"):
                    errors.append(f"options[{i}] 缺少 id")
                if not o.get("label"):
                    errors.append(f"options[{i}] 缺少 label")
        return errors
