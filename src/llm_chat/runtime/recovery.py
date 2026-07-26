"""应用启动后的安全 Run 恢复协调器。"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List

from .handlers import RunDispatcher
from .manager import RunManager
from .models import RunStatus

logger = logging.getLogger(__name__)


@dataclass
class RecoveryReport:
    resumed: List[str] = field(default_factory=list)
    retried: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)


class RunRecoveryCoordinator:
    """只自动处理框架明确声明安全的恢复动作。"""

    def __init__(
        self,
        *,
        run_manager: RunManager,
        dispatcher: RunDispatcher,
    ):
        self.run_manager = run_manager
        self.dispatcher = dispatcher
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def recover_once(self) -> RecoveryReport:
        report = RecoveryReport()
        for run in self.run_manager.list(limit=1000):
            handler = run.metadata.get("run_handler")
            if handler == "action":
                report.skipped.append(run.id)
                continue
            try:
                if run.status == RunStatus.PAUSED and self.dispatcher.can_resume(run.id):
                    self.dispatcher.resume(run.id, None)
                    report.resumed.append(run.id)
                elif (
                    run.status == RunStatus.FAILED
                    and run.metadata.get("recovery_action") == "retry"
                    and self.dispatcher.can_retry(run.id)
                ):
                    self.dispatcher.retry(run.id)
                    report.retried.append(run.id)
                elif run.status in {RunStatus.PAUSED, RunStatus.FAILED}:
                    report.skipped.append(run.id)
            except Exception as exc:
                report.errors[run.id] = str(exc)
                logger.warning("Automatic recovery failed for %s", run.id, exc_info=True)
        return report

    def start_async(self) -> threading.Thread:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self._thread
            self._thread = threading.Thread(
                target=self.recover_once,
                name="run-recovery",
                daemon=True,
            )
            self._thread.start()
            return self._thread
