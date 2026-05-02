"""LLMClient generate 方法（纯文本生成）"""

import logging
import time
from typing import Optional

import requests

from llm_chat.exceptions import LLMError

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

        for i in range(self.config.llm.max_retries):
            try:
                response = self.session.post(url, json=data, headers=headers)
                response.raise_for_status()
                result = response.json()
                response_text = self.protocol.parse_generate_response(result)
                logger.info(f"生成响应: length={len(response_text)}")
                return response_text
            except requests.RequestException as e:
                if i == self.config.llm.max_retries - 1:
                    error_msg = str(e)
                    if hasattr(e, "response") and e.response is not None:
                        try:
                            error_detail = e.response.json()
                            error_msg = f"{error_msg}\n详情: {error_detail}"
                        except Exception:
                            error_msg = (
                                f"{error_msg}\n响应内容: {e.response.text}"
                            )
                    logger.error(f"生成请求失败: {error_msg}")
                    raise LLMError(f"API 请求失败: {error_msg}")
                logger.warning(f"请求失败，{i + 1}秒后重试: {e}")
                time.sleep(1)

        return ""
