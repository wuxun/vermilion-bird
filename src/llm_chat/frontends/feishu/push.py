"""PushService - 主动消息推送服务。

支持向用户、群聊推送消息，以及广播消息到所有活跃会话。
"""

import logging
from typing import Any, Dict, List, Optional, Set

from llm_chat.frontends.feishu.adapter import FeishuAdapter, FeishuAdapterError

logger = logging.getLogger(__name__)


def _mask_identifier(identifier: Optional[str]) -> str:
    """Mask sensitive identifiers for logging purposes."""
    if not identifier:
        return "None"
    s = str(identifier)
    if len(s) <= 6:
        return "***"
    return f"{s[:2]}{'*' * (len(s) - 4)}{s[-2:]}"


class PushServiceError(Exception):
    """PushService 异常基类。"""

    pass


class PushService:
    """飞书主动消息推送服务。

    封装 FeishuAdapter.send_message() 方法，提供便捷的消息推送功能。

    Usage:
        adapter = FeishuAdapter(app, app_id, app_secret)
        push = PushService(adapter)

        # 推送给单个用户
        push.push_to_user("ou_xxxx", "Hello!")

        # 推送给群聊
        push.push_to_group("oc_xxxx", "Group message!")

        # 广播到所有活跃会话
        push.broadcast("System notification!")
    """

    def __init__(self, adapter: FeishuAdapter):
        """初始化 PushService。

        Args:
            adapter: FeishuAdapter 实例，用于发送消息
        """
        self._adapter = adapter
        self._active_sessions: Set[str] = set()

    def register_session(self, session_id: str) -> None:
        """注册活跃会话。

        Args:
            session_id: 会话 ID (chat_id 或 open_id)
        """
        self._active_sessions.add(session_id)
        logger.debug(f"Session registered: {session_id}")

    def unregister_session(self, session_id: str) -> None:
        """注销活跃会话。

        Args:
            session_id: 会话 ID
        """
        self._active_sessions.discard(session_id)
        logger.debug(f"Session unregistered: {session_id}")

    def get_active_sessions(self) -> Set[str]:
        """获取当前活跃会话列表。

        Returns:
            活跃会话 ID 集合
        """
        return self._active_sessions.copy()

    def push_to_user(
        self,
        open_id: str,
        message: str,
        msg_type: str = "text",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """推送消息给指定用户。

        API Reference: https://open.feishu.cn/document/server-docs/im-v1/message/create

        Args:
            open_id: 用户的 open_id
            message: 消息内容（文本或 JSON 字符串）
            msg_type: 消息类型，默认 "text"
            **kwargs: 额外参数传递给 send_message

        Returns:
            API 响应字典

        Raises:
            PushServiceError: 推送失败时抛出
        """
        content = self._build_content(message, msg_type)

        # Log with safe identifiers and a short preview of the message
        masked_open_id = _mask_identifier(open_id)
        preview = message[:30]
        logger.info(f"Pushing to user {masked_open_id}: preview='{preview}'")

        try:
            result = self._adapter.send_message(
                receive_id=open_id,
                msg_type=msg_type,
                content=content,
                receive_id_type="open_id",
            )
            logger.info(f"Message pushed to user {masked_open_id}")
            return result
        except FeishuAdapterError as e:
            logger.error(
                f"Failed to push message to user {masked_open_id}: {e}",
                exc_info=True,
            )
            raise PushServiceError(f"Failed to push to user {open_id}: {e}") from e

    def push_to_group(
        self,
        chat_id: str,
        message: str,
        msg_type: str = "text",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """推送消息给指定群聊。

        API Reference: https://open.feishu.cn/document/server-docs/im-v1/message/create

        Args:
            chat_id: 群聊的 chat_id
            message: 消息内容（文本或 JSON 字符串）
            msg_type: 消息类型，默认 "text"
            **kwargs: 额外参数传递给 send_message

        Returns:
            API 响应字典

        Raises:
            PushServiceError: 推送失败时抛出
        """
        content = self._build_content(message, msg_type)
        masked_chat_id = _mask_identifier(chat_id)
        preview = message[:30]
        logger.info(f"Pushing to group {masked_chat_id}: preview='{preview}'")

        try:
            result = self._adapter.send_message(
                receive_id=chat_id,
                msg_type=msg_type,
                content=content,
                receive_id_type="chat_id",
            )
            logger.info(f"Message pushed to group {masked_chat_id}")
            return result
        except FeishuAdapterError as e:
            logger.error(
                f"Failed to push message to group {masked_chat_id}: {e}",
                exc_info=True,
            )
            raise PushServiceError(f"Failed to push to group {chat_id}: {e}") from e

    def broadcast(
        self,
        message: str,
        msg_type: str = "text",
        session_ids: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """广播消息到所有活跃会话（或指定会话列表）。

        Args:
            message: 消息内容
            msg_type: 消息类型，默认 "text"
            session_ids: 可选的目标会话列表，为 None 时使用所有活跃会话

        Returns:
            字典，key 为 session_id，value 为 API 响应或错误信息
            {
                "session_1": {"code": 0, "data": {...}},
                "session_2": {"error": "Failed to send: ..."}
            }
        """
        targets = (
            session_ids if session_ids is not None else list(self._active_sessions)
        )

        if not targets:
            logger.warning("No active sessions to broadcast to")
            return {}

        results: Dict[str, Dict[str, Any]] = {}
        content = self._build_content(message, msg_type)

        for session_id in targets:
            masked_session = _mask_identifier(session_id)
            try:
                # 尝试作为 chat_id 发送（群聊优先）
                logger.info(
                    f"Broadcast to session {masked_session}: preview='{message[:30]}'"
                )
                result = self._adapter.send_message(
                    receive_id=session_id,
                    msg_type=msg_type,
                    content=content,
                    receive_id_type="chat_id",
                )
                results[session_id] = result
                logger.info(f"Broadcast sent to {_mask_identifier(session_id)}")
            except FeishuAdapterError as e:
                # 如果 chat_id 失败，尝试作为 open_id 发送
                try:
                    result = self._adapter.send_message(
                        receive_id=session_id,
                        msg_type=msg_type,
                        content=content,
                        receive_id_type="open_id",
                    )
                    results[session_id] = result
                    logger.info(f"Broadcast sent to {_mask_identifier(session_id)}")
                except FeishuAdapterError as e2:
                    results[session_id] = {"error": f"Failed to send: {e2}"}
                    logger.error(
                        f"Broadcast failed for {_mask_identifier(session_id)}: {e2}",
                        exc_info=True,
                    )

        success_count = sum(
            1 for r in results.values() if isinstance(r, dict) and "error" not in r
        )
        logger.info(f"Broadcast completed: {success_count}/{len(targets)} successful")

        return results

    def _build_content(self, message: str, msg_type: str) -> Dict[str, Any]:
        """构建消息内容字典。

        Args:
            message: 消息内容
            msg_type: 消息类型

        Returns:
            消息内容字典
        """
        if msg_type == "text":
            return {"text": message}
        elif msg_type == "post":
            # 富文本消息，如果 message 已经是 JSON 格式则直接使用
            # 否则包装为简单文本格式
            import json

            try:
                parsed = json.loads(message)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

            # 默认包装为简单富文本
            return {
                "zh_cn": {
                    "title": "",
                    "content": [[{"tag": "text", "text": message}]],
                }
            }
        else:
            # 其他类型直接使用文本格式
            return {"text": message}
