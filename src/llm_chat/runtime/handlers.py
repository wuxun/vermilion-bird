"""Run 恢复操作的统一处理器注册表与分发器。"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Protocol

from .manager import RunManager
from .models import Run


class RunHandler(Protocol):
    """一种 Run 的恢复、重试和重放策略。"""

    def resume(self, run_id: str, value: Any = None) -> Run:
        ...

    def retry(self, run_id: str) -> Run:
        ...

    def replay(self, run_id: str) -> Run:
        ...


class RunHandlerRegistry:
    """实例级 handler 注册表，不依赖全局单例。"""

    def __init__(self):
        self._handlers: Dict[str, RunHandler] = {}
        self._lock = threading.RLock()

    def register(
        self,
        name: str,
        handler: RunHandler,
        *,
        replace: bool = False,
    ) -> None:
        if not name:
            raise ValueError("Run handler name cannot be empty")
        with self._lock:
            if name in self._handlers and not replace:
                raise ValueError(f"Run handler already registered: {name}")
            self._handlers[name] = handler

    def unregister(self, name: str) -> None:
        with self._lock:
            self._handlers.pop(name, None)

    def get(self, name: str) -> Optional[RunHandler]:
        with self._lock:
            return self._handlers.get(name)

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._handlers))


class RunDispatcher:
    """根据 Run 元数据把控制操作路由给唯一生产 handler。"""

    HANDLER_KEY = "run_handler"

    def __init__(
        self,
        *,
        run_manager: RunManager,
        registry: RunHandlerRegistry,
    ):
        self.run_manager = run_manager
        self.registry = registry

    def resume(self, run_id: str, value: Any = None) -> Run:
        run, handler = self._resolve(run_id)
        if not run.can_resume:
            raise ValueError(f"Run {run_id} cannot be resumed")
        self._ensure_handler_allows(handler, "resume", run)
        return handler.resume(run_id, value)

    def retry(self, run_id: str) -> Run:
        run, handler = self._resolve(run_id)
        if not run.can_retry:
            raise ValueError(f"Run {run_id} cannot be retried")
        self._ensure_handler_allows(handler, "retry", run)
        return handler.retry(run_id)

    def replay(self, run_id: str) -> Run:
        run, handler = self._resolve(run_id)
        if not run.status.terminal:
            raise ValueError(f"Run {run_id} is not terminal")
        self._ensure_handler_allows(handler, "replay", run)
        return handler.replay(run_id)

    def can_resume(self, run_id: str) -> bool:
        return self._can(run_id, "resume")

    def can_retry(self, run_id: str) -> bool:
        return self._can(run_id, "retry")

    def can_replay(self, run_id: str) -> bool:
        return self._can(run_id, "replay")

    def _can(self, run_id: str, operation: str) -> bool:
        run = self.run_manager.get(run_id)
        if run is None:
            return False
        state_allows = {
            "resume": run.can_resume,
            "retry": run.can_retry,
            "replay": run.status.terminal,
        }[operation]
        if not state_allows:
            return False
        try:
            _, handler = self._resolve(run_id)
        except (KeyError, ValueError):
            return False
        capability = getattr(handler, f"can_{operation}", None)
        return bool(capability(run)) if callable(capability) else True

    @staticmethod
    def _ensure_handler_allows(
        handler: RunHandler,
        operation: str,
        run: Run,
    ) -> None:
        capability = getattr(handler, f"can_{operation}", None)
        if callable(capability) and not capability(run):
            raise ValueError(f"Run handler does not allow {operation} for {run.id}")

    def _resolve(self, run_id: str) -> tuple[Run, RunHandler]:
        run = self.run_manager.get(run_id)
        if run is None:
            raise KeyError(f"Unknown run: {run_id}")
        name = run.metadata.get(self.HANDLER_KEY)
        if not name and run.metadata.get("graph_runtime"):
            name = "graph"
        if not name:
            raise ValueError(f"Run {run_id} has no registered handler")
        handler = self.registry.get(str(name))
        if handler is None:
            raise ValueError(f"Run handler is unavailable: {name}")
        return run, handler
