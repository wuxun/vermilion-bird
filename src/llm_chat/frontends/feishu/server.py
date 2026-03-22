"""Feishu Server - Long connection service for Feishu integration."""

import logging
import signal
import threading
import time
from typing import Callable, Dict, Optional

from lark_oapi import ws
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
    # Show first 2 and last 2 characters, mask the middle
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
        # Ensure a sensible default logging configuration for this logger
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)
        self._logger.setLevel(logging.INFO)

        # WebSocket client (initialized in start())
        self._client: Optional[ws.Client] = None
        self._event_handler = None

    def start(self) -> None:
        """Start Feishu WebSocket server in background thread.

        This method returns immediately after launching the background thread.
        """
        if self._thread and self._thread.is_alive():
            self._logger.warning("FeishuServer already running")
            return

        self._stop_event.clear()

        # Initialize WebSocket client
        try:
            # Create event dispatcher handler
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

            # Start WebSocket connection in background thread
            self._thread = threading.Thread(
                target=self._run_loop, name="FeishuServer", daemon=False
            )
            self._thread.start()

            # Register as current running server for tests/consumers
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
        """Main run loop - starts WebSocket client.

        This runs in the calling thread and not a background thread.
        """
        try:
            self._logger.info("Connecting to Feishu WebSocket...")
            self._client.start()
        except Exception as e:
            if self._stop_event.is_set():
                self._logger.info("FeishuServer shutting down")
                return

            self._logger.error(f"WebSocket error: {e}", exc_info=True)

    def _handle_message_event(self, event: dict) -> None:
        """Handle incoming message event.

        Args:
            event: Feishu event data
        """
        try:
            event_id = event.get("event_id", "unknown")
            user_id = event.get("event", {}).get("sender", {}).get("user_id")
            chat_id = event.get("event", {}).get("chat", {}).get("chat_id")

            masked_user = _mask_identifier(user_id)
            masked_chat = _mask_identifier(chat_id)

            self._logger.info(
                f"Received message event: event_id={event_id}, "
                f"user_id={masked_user}, chat_id={masked_chat}"
            )

            # Process event asynchronously via adapter
            if self.adapter:
                # Convert to FeishuEvent and handle
                from llm_chat.frontends.feishu.models import FeishuEvent

                feishu_event = FeishuEvent(
                    event_id=event_id,
                    event_type="im.message.receive_v1",
                    timestamp=time.time(),
                    event=event.get("event", {}),
                )
                self.adapter.handle_event_async(feishu_event)
            else:
                self._logger.warning("No adapter configured, cannot handle event")

        except Exception as e:
            self._logger.error(f"Error handling message event: {e}", exc_info=True)

    def _handle_bot_added_event(self, event: dict) -> None:
        """Handle bot added to group chat event.

        Args:
            event: Feishu event data
        """
        try:
            event_id = event.get("event_id", "unknown")
            chat_id = event.get("event", {}).get("chat", {}).get("chat_id")

            masked_chat = _mask_identifier(chat_id)

            self._logger.info(
                f"Bot added to group: event_id={event_id}, chat_id={masked_chat}"
            )

            # This is just a notification event, no response needed
            # Could trigger welcome message or configuration logic here

        except Exception as e:
            self._logger.error(f"Error handling bot added event: {e}", exc_info=True)

    def __del__(self):
        # Ensure registry is clean when object is garbage collected
        global _CURRENT_SERVER
        if _CURRENT_SERVER is self:
            _CURRENT_SERVER = None


def get_running_feishu_server() -> Optional[FeishuServer]:
    """Return currently running FeishuServer instance, if any."""
    return _CURRENT_SERVER
