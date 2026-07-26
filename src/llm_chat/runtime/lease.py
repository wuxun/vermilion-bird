"""长任务的 Run 租约自动续期。"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from .manager import RunManager

logger = logging.getLogger(__name__)


class RunLeaseHeartbeat:
    """后台续租 context manager；退出时只停止心跳，不改变 Run 状态。"""

    def __init__(
        self,
        run_manager: RunManager,
        run_id: str,
        *,
        lease_seconds: int = 120,
        interval_seconds: Optional[float] = None,
    ):
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        self.run_manager = run_manager
        self.run_id = run_id
        self.lease_seconds = lease_seconds
        self.interval_seconds = interval_seconds or max(0.25, lease_seconds / 3)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "RunLeaseHeartbeat":
        self._thread = threading.Thread(
            target=self._loop,
            name=f"run-heartbeat-{self.run_id[-8:]}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=min(2.0, self.interval_seconds + 0.5))
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            run = self.run_manager.get(self.run_id)
            if run is None or run.status.terminal:
                return
            try:
                self.run_manager.heartbeat(
                    self.run_id,
                    lease_seconds=self.lease_seconds,
                )
            except (KeyError, ValueError):
                run = self.run_manager.get(self.run_id)
                if run is None or run.status.terminal:
                    return
                logger.warning("Run lease heartbeat stopped for %s", self.run_id)
                return
            except Exception:
                logger.warning(
                    "Run lease heartbeat failed for %s",
                    self.run_id,
                    exc_info=True,
                )
