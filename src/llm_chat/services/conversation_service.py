import logging
from typing import Dict, Any, List, Optional, Callable

logger = logging.getLogger(__name__)


class ConversationService:
    """对话服务层 - 封装对话操作的业务逻辑

    职责:
    - 创建/删除/重命名/切换对话
    - 管理对话列表
    - 提供对话操作的回调接口
    """

    def __init__(
        self,
        conversation_manager,
        storage,
        on_list_refresh: Optional[Callable[[], None]] = None,
    ):
        self._manager = conversation_manager
        self._storage = storage
        self._on_list_refresh = on_list_refresh
        self._current_conversation_id: str = "default"

    @property
    def current_conversation_id(self) -> str:
        return self._current_conversation_id

    def set_list_refresh_callback(self, callback: Callable[[], None]):
        self._on_list_refresh = callback

    def create(self, title: Optional[str] = None) -> Dict[str, Any]:
        """创建新对话"""
        conv = self._manager.create_conversation(title)
        self._current_conversation_id = conv.conversation_id
        logger.info(f"创建对话: {conv.conversation_id}")
        self._trigger_list_refresh()
        return {"id": conv.conversation_id, "title": title}

    def delete(self, conversation_id: str) -> bool:
        """删除对话"""
        if conversation_id == self._current_conversation_id:
            conversations = self._manager.list_conversations()
            if conversations:
                next_conv = conversations[0]
                self._current_conversation_id = next_conv.get("id")
            else:
                self.create()
                return True

        result = self._manager.delete_conversation(conversation_id)
        logger.info(f"删除对话: {conversation_id}")
        self._trigger_list_refresh()
        return result

    def rename(self, conversation_id: str, title: str) -> bool:
        """重命名对话"""
        self._storage.update_conversation(conversation_id, title=title)
        logger.info(f"重命名对话: {conversation_id} -> {title}")
        self._trigger_list_refresh()
        return True

    def switch(self, conversation_id: str) -> List[Dict[str, Any]]:
        """切换对话"""
        self._current_conversation_id = conversation_id
        messages = self._storage.get_messages(conversation_id)
        logger.info(f"切换对话: {conversation_id}")
        return messages

    def list(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """获取对话列表"""
        return self._manager.list_conversations(limit, offset)

    def get_messages(
        self, conversation_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取对话消息"""
        conv_id = conversation_id or self._current_conversation_id
        return self._storage.get_messages(conv_id)

    def _trigger_list_refresh(self):
        """触发列表刷新回调"""
        if self._on_list_refresh:
            self._on_list_refresh()

    def get_callbacks(self) -> Dict[str, Callable]:
        """获取对话操作的回调函数字典

        用于与 Frontend 绑定
        """
        return {
            "on_new": self.create,
            "on_delete": self.delete,
            "on_rename": self.rename,
            "on_switch": self.switch,
            "on_list": self.list,
        }
