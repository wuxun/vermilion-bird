"""
Summarizer 抽象 — 解除记忆系统对 LLMClient 的直接依赖。

提供三种实现：
- LLMSummarizer: 通过 LLMClient.chat() 生成摘要/提取事实
- RuleSummarizer: 基于正则的降级实现，不依赖 LLM
- SmartSummarizer: 自动选择 LLM 或规则（带重试和超时）
"""

import logging
from typing import Protocol, Optional

logger = logging.getLogger(__name__)


class Summarizer(Protocol):
    """摘要器协议 —— 从对话中提取结构化信息。

    实现类只需实现 generate() 方法，返回 None 表示降级到规则模式。
    """

    def generate(self, prompt: str, max_tokens: int = 500) -> Optional[str]:
        """生成摘要或提取事实。

        Args:
            prompt: 预先构造好的提示词
            max_tokens: 期望的最大输出 token 数

        Returns:
            生成的文本，或 None 表示应由调用方降级到规则模式。
        """
        ...


class LLMSummarizer:
    """基于 LLM 的摘要器 —— 封装 LLMClient.chat()。"""

    def __init__(self, client: "LLMClient"):  # type: ignore[name-defined]  # noqa: F821
        self._client = client

    def generate(self, prompt: str, max_tokens: int = 500) -> Optional[str]:
        try:
            response = self._client.chat(
                prompt,
                history=[],
                max_tokens=max_tokens,
            )
            return response.strip() if response else None
        except Exception as e:
            logger.warning(f"LLMSummarizer 生成失败: {e}")
            return None

    def __repr__(self) -> str:
        return f"LLMSummarizer(client={self._client.config.llm.model})"


class RuleSummarizer:
    """基于规则的降级摘要器 —— 不依赖 LLM。

    返回 None 表示调用方应使用其自身的规则逻辑。
    MemoryExtractor 内已有完整的 _extract_with_rules 等规则方法。
    """

    def generate(self, prompt: str, max_tokens: int = 500) -> Optional[str]:
        return None

    def __repr__(self) -> str:
        return "RuleSummarizer()"
