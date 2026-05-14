"""SubmitDecisionCardTool — LLM 通过 tool call 提交决策卡片。

替代在文本中嵌入 ```decision-card JSON 块，利用 tool call 的结构化保证
卡片数据完整可靠。同时保留 _try_extract_card() 作为 fallback。

请求范围隔离机制：
    - ChatCore 在 LLM 调用前调用 init_card_context() 建立 request_id
    - SubmitDecisionCardTool.execute()（或直接旁路）调用 submit_card()
      写入 _cards[request_id]
    - ChatCore 调用 get_pending_card() 读取并清除当前 request 的卡片
    - contextvars 确保不同并发请求之间完全隔离
"""

from __future__ import annotations

import contextvars
import logging
import threading
import uuid
from typing import Any, Dict, Optional

from llm_chat.tools.base import BaseTool

logger = logging.getLogger(__name__)

# ── 请求级卡片存储 ──
# contextvars 在 Python 3.7+ 的 ThreadPoolExecutor.submit() 中自动传播到工作线程

_card_request_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "card_request_id", default=None
)
_cards: Dict[str, "DecisionCard"] = {}
_cards_lock = threading.Lock()


# ── 公共 API ──


def init_card_context() -> str:
    """初始化卡片上下文，返回唯一的 request_id。

    在 LLM 调用之前调用。request_id 通过 contextvars 传播到
    ThreadPoolExecutor 工作线程。
    """
    request_id = uuid.uuid4().hex[:12]
    _card_request_id.set(request_id)
    logger.debug(f"[卡片上下文] 初始化 request_id={request_id}")
    return request_id


def clear_card_context() -> None:
    """清除当前请求的卡片上下文。

    在 get_pending_card() 之后调用，确保不会泄漏到下一个请求。
    """
    request_id = _card_request_id.get()
    if request_id:
        with _cards_lock:
            _cards.pop(request_id, None)
    _card_request_id.set(None)


def submit_card(card: "DecisionCard") -> None:
    """在当前请求上下文中提交一张决策卡片。

    线程安全：通过 contextvars 获取 request_id，
    使用锁保护共享 dict 写入。
    """
    request_id = _card_request_id.get()
    if request_id:
        with _cards_lock:
            _cards[request_id] = card
        logger.info(f"[提交卡片] {card.id}: {card.title} (request={request_id})")
    else:
        logger.warning("[提交卡片] 无活跃请求上下文，卡片被丢弃")


def get_pending_card() -> Optional["DecisionCard"]:
    """获取并清除当前请求上下文中的待推送决策卡片。

    Returns:
        卡片对象，若当前上下文无卡片则返回 None。
    """
    request_id = _card_request_id.get()
    if not request_id:
        return None
    with _cards_lock:
        return _cards.pop(request_id, None)


class SubmitDecisionCardTool(BaseTool):
    """工具：LLM 调用此工具提交决策卡片。

    与在文本中嵌入 ```decision-card 块不同，此工具利用 LLM 的
    function calling 机制，参数经过 JSON Schema 校验，格式保证正确。

    兼容性：
        - GUI: ChatCore 提取卡片 → CardSignals → DecisionCardWidget 渲染
        - 飞书: ChatCore 提取卡片 → 文本摘要推送（与现有 _try_extract_card 一致）
        - CLI: ChatCore 提取卡片 → 文本提示
    """

    @property
    def name(self) -> str:
        return "submit_decision_card"

    @property
    def description(self) -> str:
        return (
            "提交一张决策卡片给用户。当你完成了多维度分析，需要在文本回复之外"
            "额外提供结构化选项时调用此工具。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "卡片标题，带 emoji，一句话概括决策主题",
                },
                "context": {
                    "type": "string",
                    "description": "背景摘要，1-3 行说明为什么需要决策",
                },
                "options": {
                    "type": "array",
                    "description": "选项列表，至少 2 个",
                    "minItems": 2,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "选项 ID，依次为 A, B, C...",
                            },
                            "label": {
                                "type": "string",
                                "description": "选项名称，简短如 '连接池扩容（推荐）'",
                            },
                            "description": {
                                "type": "string",
                                "description": "选项的详细说明",
                            },
                            "expected_effect": {
                                "type": "string",
                                "description": "预期效果摘要",
                            },
                            "risk": {
                                "type": "string",
                                "description": "风险描述",
                            },
                            "confidence": {
                                "type": "number",
                                "description": "置信度，0.0~1.0",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                        },
                        "required": ["id", "label", "confidence"],
                    },
                },
                "recommendation": {
                    "type": "string",
                    "description": "推荐选项的 id，应为 confidence 最高的选项",
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "信息来源引用，如子 agent 名称、文档路径",
                },
            },
            "required": ["title", "options"],
        }

    def execute(
        self,
        title: str,
        options: list,
        context: str = "",
        recommendation: str = "",
        sources: list = None,
        **kwargs,
    ) -> str:
        """验证并存储决策卡片到共享变量。

        Args:
            title: 卡片标题
            options: 选项列表
            context: 背景摘要
            recommendation: 推荐选项
            sources: 信息来源

        Returns:
            确认消息。ChatCore 会读取 thread-local 中的卡片。
        """
        from llm_chat.decision.schema import DecisionCard, DecisionOption

        try:
            option_objs = []
            for o in options:
                option_objs.append(DecisionOption(
                    id=o.get("id", ""),
                    label=o.get("label", ""),
                    description=o.get("description"),
                    expected_effect=o.get("expected_effect"),
                    risk=o.get("risk"),
                    confidence=float(o.get("confidence", 0.5)),
                ))

            card = DecisionCard(
                title=title,
                context=context or None,
                options=option_objs,
                recommendation=recommendation or None,
                sources=sources or [],
            )

            submit_card(card)
            return (
                f"卡片已提交。ID: {card.id}，"
                f"{len(options)} 个选项，推荐 {recommendation or '无'}。"
            )

        except Exception as e:
            logger.error(f"[提交卡片失败] {e}")
            return f"卡片提交失败: {e}"
