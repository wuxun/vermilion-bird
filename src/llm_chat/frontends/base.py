from abc import ABC, abstractmethod
from typing import Callable, Optional, Any, List, Dict
from dataclasses import dataclass
from enum import Enum


class MessageType(Enum):
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"


@dataclass
class Message:
    content: str
    role: str
    msg_type: MessageType = MessageType.TEXT
    metadata: Optional[dict] = None


@dataclass
class ConversationContext:
    conversation_id: str
    user_id: Optional[str] = None
    channel_id: Optional[str] = None
    metadata: Optional[dict] = None


class BaseFrontend(ABC):
    def __init__(self, name: str):
        self.name = name
        self._on_message_callback: Optional[Callable] = None
        self._on_clear_callback: Optional[Callable] = None
        self._on_exit_callback: Optional[Callable] = None
        self._on_new_conversation_callback: Optional[Callable] = None
        self._on_delete_conversation_callback: Optional[Callable] = None
        self._on_rename_conversation_callback: Optional[Callable] = None
        self._on_switch_conversation_callback: Optional[Callable] = None
        self._on_list_conversations_callback: Optional[Callable] = None

    def set_on_message(self, callback: Callable[[Message, ConversationContext], None]):
        self._on_message_callback = callback

    def set_on_clear(self, callback: Callable[[ConversationContext], None]):
        self._on_clear_callback = callback

    def set_on_exit(self, callback: Callable[[], None]):
        self._on_exit_callback = callback

    def set_on_new_conversation(self, callback: Callable[[], None]):
        self._on_new_conversation_callback = callback

    def set_on_delete_conversation(self, callback: Callable[[str], None]):
        self._on_delete_conversation_callback = callback

    def set_on_rename_conversation(self, callback: Callable[[str], None]):
        self._on_rename_conversation_callback = callback

    def set_on_switch_conversation(self, callback: Callable[[str], None]):
        self._on_switch_conversation_callback = callback

    def set_on_list_conversations(self, callback: Callable[[], None]):
        self._on_list_conversations_callback = callback

    def set_conversation_callbacks(
        self,
        on_new: Callable[[], None],
        on_delete: Callable[[str], None],
        on_rename: Callable[[str], None],
        on_switch: Callable[[str], None],
        on_list: Callable[[], None],
    ):
        self._on_new_conversation_callback = on_new
        self._on_delete_conversation_callback = on_delete
        self._on_rename_conversation_callback = on_rename
        self._on_switch_conversation_callback = on_switch
        self._on_list_conversations_callback = on_list

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def stop(self):
        pass

    @abstractmethod
    def display_message(self, message: Message):
        pass

    @abstractmethod
    def display_error(self, error: str):
        pass

    @abstractmethod
    def display_info(self, info: str):
        pass

    @abstractmethod
    def set_current_conversation(
        self, conversation_id: str, messages: List[Dict[str, Any]]
    ):
        pass

    @abstractmethod
    def update_conversation_list(self, conversations: List[Dict[str, Any]]):
        pass

    @abstractmethod
    def request_rename_input(
        self, conversation_id: str, current_title: str
    ) -> Optional[str]:
        pass

    @property
    @abstractmethod
    def conversation_id(self) -> str:
        pass

    @abstractmethod
    def is_current_conversation_empty(self) -> bool:
        pass

    @abstractmethod
    def request_conversation_list_refresh(self):
        pass

    def _handle_message(self, message: Message, context: ConversationContext):
        if self._on_message_callback:
            self._on_message_callback(message, context)

    def _handle_clear(self, context: ConversationContext):
        if self._on_clear_callback:
            self._on_clear_callback(context)

    def _handle_exit(self):
        if self._on_exit_callback:
            self._on_exit_callback()

    def _handle_new_conversation(self):
        if self._on_new_conversation_callback:
            self._on_new_conversation_callback()

    def _handle_delete_conversation(self, conversation_id: str):
        if self._on_delete_conversation_callback:
            self._on_delete_conversation_callback(conversation_id)

    def _handle_rename_conversation(self, conversation_id: str):
        if self._on_rename_conversation_callback:
            self._on_rename_conversation_callback(conversation_id)

    def _handle_switch_conversation(self, conversation_id: str):
        if self._on_switch_conversation_callback:
            self._on_switch_conversation_callback(conversation_id)

    def _handle_list_conversations(self):
        if self._on_list_conversations_callback:
            self._on_list_conversations_callback()
