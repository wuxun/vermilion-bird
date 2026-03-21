from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class FeishuUser:
    user_id: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None


@dataclass
class FeishuChat:
    chat_id: str
    type: Optional[str] = None
    name: Optional[str] = None
    owner_id: Optional[str] = None


@dataclass
class FeishuMessage:
    message_id: str
    chat: Optional[FeishuChat] = None
    sender: Optional[FeishuUser] = None
    text: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    create_time: Optional[int] = None


@dataclass
class FeishuEvent:
    event_id: str
    event_type: Optional[str] = None
    timestamp: Optional[int] = None
    message: Optional[FeishuMessage] = None
    user: Optional[FeishuUser] = None
    payload: Optional[Dict[str, Any]] = None
