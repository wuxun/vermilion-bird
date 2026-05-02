"""LLMClient - 大模型对话客户端

通过 mixin 组合实现，各模块职责：
- _base.py       LLMClientBase       初始化/技能/工具管理
- _chat.py       LLMClientChatMixin   chat() / chat_stream() + HTTP 发送
- _tools.py      LLMClientToolsMixin  chat_with_tools() 同步工具调用
- _stream_tools.py  LLMClientStreamToolsMixin  chat_stream_with_tools() 流式工具调用
- _generate.py   LLMClientGenerateMixin  generate() 纯文本生成
- _logging.py    log_request_details()  独立日志函数
"""

from llm_chat.client._base import LLMClientBase
from llm_chat.client._chat import LLMClientChatMixin
from llm_chat.client._tools import LLMClientToolsMixin
from llm_chat.client._stream_tools import LLMClientStreamToolsMixin
from llm_chat.client._generate import LLMClientGenerateMixin


class LLMClient(
    LLMClientChatMixin,
    LLMClientStreamToolsMixin,
    LLMClientToolsMixin,
    LLMClientGenerateMixin,
    LLMClientBase,
):
    """大模型对话客户端

    支持：
    - 同步聊天 chat()
    - 流式聊天 chat_stream()
    - 工具调用 chat_with_tools()
    - 流式工具调用 chat_stream_with_tools()
    - 纯文本生成 generate()
    """
