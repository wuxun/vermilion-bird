"""意图识别模块 — 三层路由管道，减少不必要的 LLM 调用。

使用方式:
    from llm_chat.intent import IntentClassifier, RoutingDecision

    classifier = IntentClassifier()
    decision = classifier.classify(user_message)

    if decision.skip_llm:
        return decision.direct_response  # 跳过 LLM

    # 使用 decision.suggested_model, decision.suggested_tools 优化 LLM 调用
"""

from .types import Intent, RoutingDecision
from .classifier import IntentClassifier

__all__ = [
    "Intent",
    "RoutingDecision",
    "IntentClassifier",
]
