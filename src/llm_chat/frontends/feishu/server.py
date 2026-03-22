import logging
import signal
import threading
import time
from typing import Optional


def _mask_identifier(identifier: Optional[str]) -> str:
    """Mask sensitive identifiers for logging.

    Avoid logging full IDs. For any non-empty identifier, return a masked form
    that preserves some structure without leaking the value. If no identifier is
    provided, return the string "None".
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
    """A lightweight Feishu server wrapper used by the CLI command.

    This is a minimal, non-blocking background server that simulates a Feishu
    integration. It is designed for testing/CI scenarios where we want to
    verify startup/shutdown behavior without depending on real Feishu APIs.
    """

    def __init__(
        self, app_id: str, app_secret: str, tenant_key: Optional[str] = None
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.tenant_key = tenant_key
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

    def start(self) -> None:
        """Start the Feishu server in a background thread (daemon).

        This method returns immediately after launching the background thread.
        """
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="FeishuServer", daemon=False
        )
        self._thread.start()
        # Register as current running server for tests/consumers
        global _CURRENT_SERVER
        _CURRENT_SERVER = self
        self._logger.info("FeishuServer started in background thread")

    def stop(self) -> None:
        """Request a graceful shutdown of the server."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
            self._logger.info("FeishuServer background thread stopped")
        # Clear current server reference if this is the active one
        global _CURRENT_SERVER
        if _CURRENT_SERVER is self:
            _CURRENT_SERVER = None

    def _run(self) -> None:
        # Simple loop to keep the thread alive until stop is requested.
        try:
            self._logger.info("FeishuServer wiring up (simulated)...")
            while not self._stop_event.is_set():
                time.sleep(0.2)
            self._logger.info("FeishuServer shutting down (simulated)")
        except Exception:  # pragma: no cover - defensive logging
            self._logger.exception(
                "FeishuServer encountered an unexpected error in _run()"
            )

    def __del__(self):
        # Ensure registry is clean when object is garbage collected
        global _CURRENT_SERVER
        if _CURRENT_SERVER is self:
            _CURRENT_SERVER = None

    def process_request(
        self,
        request: dict,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> None:
        """Log a processing of an incoming request without exposing sensitive data."""
        masked_user = _mask_identifier(user_id)
        masked_chat = _mask_identifier(chat_id)
        action = request.get("action") if isinstance(request, dict) else None
        self._logger.info(
            f"Processing Feishu request: action={action}, user_id={masked_user}, chat_id={masked_chat}"
        )


def get_running_feishu_server() -> Optional[FeishuServer]:
    """Return the currently running FeishuServer instance, if any."""
    return _CURRENT_SERVER

    # Optional helper for tests/diagnostics
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())
