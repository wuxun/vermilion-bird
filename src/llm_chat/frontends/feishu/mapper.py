import logging
from typing import Tuple, Dict, Optional
import time

logger = logging.getLogger(__name__)


class SessionMapper:
    """Utilities to map Feishu session IDs to conversation identifiers.

    This class provides a simple encoding/decoding scheme:
    - to_conversation_id(chat_type, original_id) -> str
      - p2p: feishu_p2p_<sanitized_id>_<session_number>
      - group: feishu_group_<sanitized_id>_<session_number>
    - from_conversation_id(conversation_id) -> (chat_type, sanitized_id)
      - Returns the chat_type ('p2p'|'group') and the sanitized id portion after the prefix.

    Note: Sanitation replaces any non-alphanumeric character with '_', ensuring the
    final string contains only alphanumeric characters and underscores.

    Session numbers persist across restarts — the mapper queries the database
    for the highest existing session number on first access.
    """

    SESSION_TIMEOUT_SECONDS = 30 * 60  # 30 minutes

    _session_cache: Dict[
        str, Dict
    ] = {}  # chat_id -> {session_number, last_active_time}

    @staticmethod
    def _sanitize_id(original_id: str) -> str:
        s = str(original_id)
        return "".join(ch if ch.isalnum() else "_" for ch in s)

    @classmethod
    def _load_max_session_number(cls, prefix: str, sanitized: str) -> int:
        """从数据库查询该聊天已有会话的最大 session_number。

        跨重启持久化：避免重启后 session_number 重置为 1 导致
        覆盖已有会话 (INSERT OR REPLACE)。

        Returns:
            最大 session_number，无记录时返回 0
        """
        try:
            from llm_chat.storage import Storage

            storage = Storage()
            pattern = f"{prefix}_{sanitized}_%"
            with storage._get_connection() as conn:
                rows = conn.execute(
                    "SELECT id FROM conversations WHERE id LIKE ?",
                    (pattern,),
                ).fetchall()

            max_num = 0
            for row in rows:
                parts = row["id"].rsplit("_", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    max_num = max(max_num, int(parts[1]))

            if max_num > 0:
                logger.debug(
                    f"SessionMapper 从 DB 恢复 {prefix}_{sanitized}: "
                    f"max_session={max_num}"
                )
            return max_num
        except Exception as e:
            logger.debug(f"SessionMapper DB 查询失败 (可能无存储): {e}")
            return 0

    @classmethod
    def to_conversation_id(
        cls, chat_type: str, original_id: str, force_new_session: bool = False
    ) -> str:
        """Generate conversation ID with session management.

        Args:
            chat_type: 'p2p' or 'group'
            original_id: Feishu chat_id
            force_new_session: Force create a new session (e.g., when user sends /new)

        Returns:
            conversation_id with session number
        """
        t = str(chat_type)
        if t not in ("p2p", "group"):
            raise ValueError("Invalid chat_type: must be 'p2p' or 'group'")
        sanitized = cls._sanitize_id(original_id)
        if t == "p2p":
            prefix = "feishu_p2p"
        else:
            prefix = "feishu_group"

        cache_key = f"{prefix}_{sanitized}"
        current_time = time.time()

        if cache_key not in cls._session_cache:
            # 首次访问：从 DB 恢复最大 session_number (跨重启持久化)
            max_from_db = cls._load_max_session_number(prefix, sanitized)
            start_num = max(max_from_db, 1)
            cls._session_cache[cache_key] = {
                "session_number": start_num,
                "last_active_time": current_time,
            }
        else:
            session_info = cls._session_cache[cache_key]
            time_since_last = current_time - session_info["last_active_time"]

            if force_new_session or time_since_last > cls.SESSION_TIMEOUT_SECONDS:
                session_info["session_number"] += 1
                session_info["last_active_time"] = current_time
            else:
                session_info["last_active_time"] = current_time

        session_number = cls._session_cache[cache_key]["session_number"]
        return f"{prefix}_{sanitized}_{session_number}"

    @classmethod
    def check_new_session_command(cls, message_content: str) -> bool:
        """Check if user wants to start a new session.

        Args:
            message_content: The message text

        Returns:
            True if user wants a new session
        """
        if not message_content:
            return False
        content = message_content.strip().lower()
        return content in ("/new", "/reset", "/clear", "新会话", "新建会话")

    @staticmethod
    def from_conversation_id(conversation_id: str) -> Tuple[str, str]:
        cid = str(conversation_id)
        if cid.startswith("feishu_p2p_"):
            rest = cid[len("feishu_p2p_") :]
            if rest == "":
                raise ValueError("Invalid conversation_id: missing original_id")
            parts = rest.rsplit("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                return ("p2p", parts[0])
            return ("p2p", rest)
        if cid.startswith("feishu_group_"):
            rest = cid[len("feishu_group_") :]
            if rest == "":
                raise ValueError("Invalid conversation_id: missing original_id")
            parts = rest.rsplit("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                return ("group", parts[0])
            return ("group", rest)
        raise ValueError("Invalid conversation_id prefix")
