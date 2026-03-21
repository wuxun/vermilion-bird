from typing import Tuple


class SessionMapper:
    """Utilities to map Feishu session IDs to conversation identifiers.

    This class provides a simple encoding/decoding scheme:
    - to_conversation_id(chat_type, original_id) -> str
      - p2p: feishu_p2p_<sanitized_id>
      - group: feishu_group_<sanitized_id>
    - from_conversation_id(conversation_id) -> (chat_type, sanitized_id)
      - Returns the chat_type ('p2p'|'group') and the sanitized id portion after the prefix.

    Note: Sanitation replaces any non-alphanumeric character with '_', ensuring the
    final string contains only alphanumeric characters and underscores.
    """

    @staticmethod
    def _sanitize_id(original_id: str) -> str:
        s = str(original_id)
        return "".join(ch if ch.isalnum() else "_" for ch in s)

    @staticmethod
    def to_conversation_id(chat_type: str, original_id: str) -> str:
        t = str(chat_type)
        if t not in ("p2p", "group"):
            raise ValueError("Invalid chat_type: must be 'p2p' or 'group'")
        sanitized = SessionMapper._sanitize_id(original_id)
        if t == "p2p":
            return f"feishu_p2p_{sanitized}"
        else:
            return f"feishu_group_{sanitized}"

    @staticmethod
    def from_conversation_id(conversation_id: str) -> Tuple[str, str]:
        cid = str(conversation_id)
        if cid.startswith("feishu_p2p_"):
            rest = cid[len("feishu_p2p_") :]
            if rest == "":
                raise ValueError("Invalid conversation_id: missing original_id")
            return ("p2p", rest)
        if cid.startswith("feishu_group_"):
            rest = cid[len("feishu_group_") :]
            if rest == "":
                raise ValueError("Invalid conversation_id: missing original_id")
            return ("group", rest)
        raise ValueError("Invalid conversation_id prefix")
