"""框架无关的图执行 Runtime 端口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class GraphInterrupt:
    id: str
    value: Any


@dataclass(frozen=True)
class GraphSnapshot:
    values: Dict[str, Any]
    next_nodes: Sequence[str] = field(default_factory=tuple)
    checkpoint_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    interrupts: Sequence[GraphInterrupt] = field(default_factory=tuple)


@dataclass(frozen=True)
class GraphExecutionResult:
    values: Dict[str, Any]
    interrupts: Sequence[GraphInterrupt] = field(default_factory=tuple)
    snapshot: Optional[GraphSnapshot] = None

    @property
    def interrupted(self) -> bool:
        return bool(self.interrupts)

    @property
    def completed(self) -> bool:
        return not self.interrupts and (self.snapshot is None or not self.snapshot.next_nodes)


class GraphRuntime(ABC):
    """隐藏具体图框架类型的稳定应用端口。"""

    @abstractmethod
    def invoke(
        self,
        graph_name: str,
        *,
        thread_id: str,
        inputs: Dict[str, Any],
    ) -> GraphExecutionResult:
        ...

    @abstractmethod
    def resume(
        self,
        graph_name: str,
        *,
        thread_id: str,
        value: Any,
    ) -> GraphExecutionResult:
        ...

    @abstractmethod
    def get_state(
        self,
        graph_name: str,
        *,
        thread_id: str,
    ) -> Optional[GraphSnapshot]:
        ...

    @abstractmethod
    def get_history(
        self,
        graph_name: str,
        *,
        thread_id: str,
        limit: int = 50,
    ) -> List[GraphSnapshot]:
        ...

    @abstractmethod
    def close(self) -> None:
        ...
