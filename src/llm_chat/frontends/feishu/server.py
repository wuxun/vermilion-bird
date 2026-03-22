"""Feishu Server - Long connection service for Feishu integration."""

import asyncio
import logging
import os
import signal
import sys
import threading
import time
from typing import Callable, Dict, Optional

from lark_oapi import ws
from lark_oapi.api.im.v1.model.p2_im_message_receive_v1 import P2ImMessageReceiveV1
from lark_oapi.api.im.v1.model.p2_im_chat_member_bot_added_v1 import (
    P2ImChatMemberBotAddedV1,
)
from lark_oapi.core.enum import LogLevel
from lark_oapi.event.dispatcher_handler import EventDispatcherHandlerBuilder

from llm_chat.frontends.feishu.adapter import FeishuAdapter


def _mask_identifier(identifier: Optional[str]) -> str:
    """Mask sensitive identifiers for logging.

    Avoid logging full IDs. For any non-empty identifier, return a masked form
    that preserves some structure without leaking value. If no identifier is
    provided, return string "None".
    """
    if not identifier:
        return "None"
    s = str(identifier)
    if len(s) <= 6:
        return "***"
    return f"{s[:2]}{'*' * (len(s) - 4)}{s[-2:]}"


_CURRENT_SERVER = None


class FeishuServer:
    """Feishu WebSocket server for real-time event handling.

    Uses lark.ws.Client for WebSocket connections with event handlers.
    Implements reconnection logic and graceful shutdown.
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        adapter: FeishuAdapter,
        encrypt_key: str = "",
        verification_token: str = "",
        tenant_key: Optional[str] = None,
        reconnect_interval: int = 5,
    ) -> None:
        """Initialize Feishu server.

        Args:
            app_id: Feishu application ID
            app_secret: Feishu application secret
            adapter: FeishuAdapter instance for handling events
            encrypt_key: Encrypt key for event verification (optional)
            verification_token: Verification token for event verification (optional)
            tenant_key: Optional tenant key
            reconnect_interval: Reconnection interval in seconds (default 5)
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.adapter = adapter
        self.encrypt_key = encrypt_key
        self.verification_token = verification_token
        self.tenant_key = tenant_key
        self.reconnect_interval = reconnect_interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._logger = logging.getLogger(__name__)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)
        self._logger.setLevel(logging.INFO)

        self._client: Optional[ws.Client] = None
        self._event_handler = None

    def start(self) -> None:
        """Start Feishu WebSocket server in background thread."""
        if self._thread and self._thread.is_alive():
            self._logger.warning("FeishuServer already running")
            return

        self._stop_event.clear()

        try:
            self._event_handler = (
                EventDispatcherHandlerBuilder(
                    encrypt_key=self.encrypt_key,
                    verification_token=self.verification_token,
                )
                .register_p2_im_message_receive_v1(self._handle_message_event)
                .register_p2_im_chat_member_bot_added_v1(self._handle_bot_added_event)
                .build()
            )

            self._client = ws.Client(
                app_id=self.app_id,
                app_secret=self.app_secret,
                log_level=LogLevel.INFO,
                event_handler=self._event_handler,
            )

            self._thread = threading.Thread(
                target=self._run_loop, name="FeishuServer", daemon=True
            )
            self._thread.start()

            global _CURRENT_SERVER
            _CURRENT_SERVER = self
            self._logger.info("FeishuServer started successfully")
        except Exception as e:
            self._logger.error(f"Failed to start FeishuServer: {e}", exc_info=True)
            raise

    def stop(self) -> None:
        """Request a graceful shutdown of server."""
        self._logger.info("Stopping FeishuServer...")
        self._stop_event.set()
        self._logger.info("FeishuServer stop requested")

    def _run_loop(self) -> None:
        """Main run loop - starts WebSocket client."""
        try:
            self._logger.info("Connecting to Feishu WebSocket...")
            self._client.start()
        except Exception as e:
            if self._stop_event.is_set():
                self._logger.info("FeishuServer shutting down")
                return
            self._logger.error(f"WebSocket error: {e}", exc_info=True)

    def _handle_message_event(self, event: P2ImMessageReceiveV1) -> None:
        """Handle incoming message event.

        Args:
            event: P2ImMessageReceiveV1 event object
        """
        try:
            # Debug: 打印完整事件对象结构
            self._logger.info(f"DEBUG - Raw event object type: {type(event)}")
            self._logger.info(
                f"DEBUG - Event dir: {[a for a in dir(event) if not a.startswith('_')]}"
            )
            if hasattr(event, "event"):
                self._logger.info(f"DEBUG - event.event type: {type(event.event)}")
                if event.event:
                    self._logger.info(
                        f"DEBUG - event.event dir: {[a for a in dir(event.event) if not a.startswith('_')]}"
                    )

            event_id = (
                getattr(event.header, "event_id", "unknown")
                if event.header
                else "unknown"
            )

            sender_id = None
            chat_id = None
            message_content = None

            if event.event:
                if event.event.sender:
                    sender_id = getattr(event.event.sender, "sender_id", None)
                    if sender_id:
                        sender_id = getattr(sender_id, "user_id", None) or getattr(
                            sender_id, "open_id", None
                        )
                if event.event.message:
                    msg = event.event.message
                    self._logger.info(f"DEBUG - message type: {type(msg)}")
                    self._logger.info(
                        f"DEBUG - message attrs: {[a for a in dir(msg) if not a.startswith('_')]}"
                    )
                    chat_id = getattr(msg, "chat_id", None)
                    message_content = getattr(msg, "content", None)
                    self._logger.info(
                        f"DEBUG - chat_id={chat_id}, content={message_content}"
                    )
                    # 打印所有属性值
                    for attr in dir(msg):
                        if not attr.startswith("_"):
                            try:
                                val = getattr(msg, attr)
                                if not callable(val):
                                    self._logger.info(f"DEBUG - message.{attr} = {val}")
                            except:
                                pass

            masked_sender = _mask_identifier(sender_id)
            masked_chat = _mask_identifier(chat_id)

            self._logger.info(
                f"Received message event: event_id={event_id}, "
                f"sender_id={masked_sender}, chat_id={masked_chat}"
            )

            if message_content:
                self._logger.debug(f"Message content: {message_content[:100]}...")

            if self.adapter:
                from llm_chat.frontends.feishu.models import (
                    FeishuChat,
                    FeishuEvent,
                    FeishuMessage,
                    FeishuUser,
                )

                # 构建 FeishuUser 对象
                feishu_user = None
                if sender_id:
                    feishu_user = FeishuUser(user_id=sender_id)

                # 构建 FeishuChat 对象
                feishu_chat = None
                if chat_id:
                    feishu_chat = FeishuChat(chat_id=chat_id, type="p2p")

                # 解析消息内容
                import json

                text_content = ""
                if message_content:
                    try:
                        content_dict = (
                            json.loads(message_content)
                            if isinstance(message_content, str)
                            else message_content
                        )
                        text_content = content_dict.get("text", "")
                    except (json.JSONDecodeError, TypeError):
                        text_content = str(message_content)
                    # Ensure conversation exists in storage
                    try:
                        chat_type = "p2p"
                        if getattr(event, "event", None) and getattr(
                            event.event, "message", None
                        ):
                            msg = event.event.message
                            if getattr(msg, "chat", None) and getattr(
                                msg.chat, "type", None
                            ):
                                t = msg.chat.type.lower()
                                if t in ("p2p", "group"):
                                    chat_type = t
                        if chat_id:
                            from llm_chat.frontends.feishu.mapper import SessionMapper

                            force_new = SessionMapper.is_new_session_request(
                                text_content
                            )
                            conv_id = SessionMapper.to_conversation_id(
                                chat_type, chat_id, force_new_session=force_new
                            )
                            storage = getattr(self.adapter.app, "storage", None)
                            if storage is not None:
                                if storage.get_conversation(conv_id) is None:
                                    storage.create_conversation(conv_id)
                    except Exception as e:
                        self._logger.error(
                            f"Failed to ensure conversation exists: {e}",
                            exc_info=True,
                        )

                # 构建 FeishuMessage 对象
                # Inbound message id (may be missing in some Feishu events)
                inbound_message_id = (
                    getattr(event.event.message, "message_id", "")
                    if getattr(event, "event", None)
                    and getattr(event.event, "message", None)
                    else ""
                )
                feishu_message = FeishuMessage(
                    message_id=inbound_message_id,
                    chat=feishu_chat,
                    sender=feishu_user,
                    text=text_content,
                    content=json.loads(message_content)
                    if message_content and isinstance(message_content, str)
                    else message_content,
                )

                feishu_event = FeishuEvent(
                    event_id=event_id,
                    event_type="im.message.receive_v1",
                    timestamp=int(time.time()),
                    message=feishu_message,
                    user=feishu_user,
                )
                self.adapter.handle_event_async(feishu_event)
            else:
                self._logger.warning("No adapter configured, cannot handle event")

        except Exception as e:
            self._logger.error(f"Error handling message event: {e}", exc_info=True)

    def _handle_bot_added_event(self, event: P2ImChatMemberBotAddedV1) -> None:
        """Handle bot added to group chat event.

        Args:
            event: P2ImChatMemberBotAddedV1 event object
        """
        try:
            event_id = (
                getattr(event.header, "event_id", "unknown")
                if event.header
                else "unknown"
            )
            chat_id = None

            if event.event and event.event.chat:
                chat_id = getattr(event.event.chat, "chat_id", None)

            masked_chat = _mask_identifier(chat_id)

            self._logger.info(
                f"Bot added to group: event_id={event_id}, chat_id={masked_chat}"
            )

        except Exception as e:
            self._logger.error(f"Error handling bot added event: {e}", exc_info=True)

    def __del__(self):
        global _CURRENT_SERVER
        if _CURRENT_SERVER is self:
            _CURRENT_SERVER = None


def get_running_feishu_server() -> Optional[FeishuServer]:
    """Return currently running FeishuServer instance, if any."""
    return _CURRENT_SERVER
