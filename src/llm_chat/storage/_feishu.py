"""Feishu chat tracking (recent_feishu_chat 表)"""

import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class StorageFeishuMixin:
    """飞书最近对话追踪操作"""

    def set_recent_feishu_chat(
        self, chat_id: str, chat_id_type: str = "chat_id"
    ):
        """保存最近的飞书对话到数据库。

        Args:
            chat_id: 群聊 ID 或用户 ID
            chat_id_type: ID 类型，'chat_id' 或 'open_id' 或 'user_id'
        """
        with self._get_connection() as conn:
            conn.execute("DELETE FROM recent_feishu_chat")
            conn.execute(
                "INSERT INTO recent_feishu_chat (chat_id, chat_id_type) "
                "VALUES (?, ?)",
                (chat_id, chat_id_type),
            )
            logger.info(
                f"Saved recent Feishu chat: {chat_id_type}={chat_id}"
            )

    def get_recent_feishu_chat(self) -> Optional[Dict[str, str]]:
        """从数据库查询最近的飞书对话。

        Returns:
            飞书对话信息字典，格式为 {"type": "feishu", "chat_id": "xxx"} 或 None
        """
        with self._get_connection() as conn:
            # 先从专门的表查询
            row = conn.execute(
                "SELECT chat_id, chat_id_type FROM recent_feishu_chat "
                "ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()

            if row:
                logger.info(
                    f"Found recent Feishu chat from recent_feishu_chat: "
                    f"{row['chat_id_type']}={row['chat_id']}"
                )
                return {
                    "type": "feishu",
                    row["chat_id_type"]: row["chat_id"],
                }

            # 向后兼容：从会话表中查找飞书会话
            return self._find_feishu_from_conversations(conn)

    def _find_feishu_from_conversations(self, conn) -> Optional[Dict[str, str]]:
        rows = conn.execute(
            "SELECT id FROM conversations ORDER BY updated_at DESC LIMIT 20"
        ).fetchall()

        for row in rows:
            conv_id = row["id"]
            if conv_id.startswith("feishu_p2p_") or conv_id.startswith(
                "feishu_group_"
            ):
                try:
                    if conv_id.startswith("feishu_p2p_"):
                        rest = conv_id[len("feishu_p2p_"):]
                    else:
                        rest = conv_id[len("feishu_group_"):]

                    parts = rest.rsplit("_", 1)
                    if len(parts) == 2 and parts[1].isdigit():
                        original_id = parts[0]
                    else:
                        original_id = rest

                    logger.info(
                        f"Found recent Feishu chat from conversations: "
                        f"{original_id}"
                    )
                    return {
                        "type": "feishu",
                        "chat_id": original_id,
                    }
                except Exception as e:
                    logger.warning(
                        f"Failed to parse Feishu conversation ID {conv_id}: {e}"
                    )
                    continue

        logger.info("No recent Feishu chat found in database")
        return None
