"""LLMClient generate 方法（纯文本生成）"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class LLMClientGenerateMixin:
    """纯文本生成 mixin

    依赖 LLMClientBase 提供的:
    - self.config, self.session, self.protocol
    """

    def generate(self, prompt: str, **kwargs) -> str:
        url = self.protocol.get_generate_url()
        headers = self.protocol.get_headers()
        data = self.protocol.build_generate_request(prompt, **kwargs)

        logger.info(f"发送生成请求: prompt_length={len(prompt)}")

        result = self._http_post_json_with_retry(url, data, headers, label="generate")

        # Track token usage
        usage = result.get("usage", {})
        if usage:
            from llm_chat.utils.observability import get_observability
            obs = get_observability()
            obs.increment("tokens.prompt", usage.get("prompt_tokens", 0))
            obs.increment("tokens.completion", usage.get("completion_tokens", 0))
            obs.increment("tokens.total", usage.get("total_tokens", 0))
            obs.increment(f"tokens.{self.config.llm.model}", usage.get("total_tokens", 0))

        response_text = self.protocol.parse_generate_response(result)
        logger.info(f"生成响应: length={len(response_text)}")
        return response_text
