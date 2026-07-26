"""GraphRuntime 的 LangGraph 实现。"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .graph_runtime import (
    GraphExecutionResult,
    GraphInterrupt,
    GraphRuntime,
    GraphSnapshot,
)


class LangGraphRuntime(GraphRuntime):
    """使用 LangGraph + SQLite 提供 durable execution。"""

    def __init__(self, db_path: str):
        path = Path(db_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            str(path),
            check_same_thread=False,
        )
        # 不允许 pickle fallback，也不允许从 checkpoint 动态加载任意模块。
        serializer = JsonPlusSerializer(
            pickle_fallback=False,
            allowed_msgpack_modules=(),
        )
        self._checkpointer = SqliteSaver(self._connection, serde=serializer)
        self._checkpointer.setup()
        self._graphs: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._closed = False

    def register_builder(self, graph_name: str, builder: Any) -> Any:
        """编译并注册 LangGraph StateGraph。

        builder 类型被限制在本适配器边界，应用层只依赖 GraphRuntime。
        """

        if not graph_name:
            raise ValueError("graph_name cannot be empty")
        with self._lock:
            self._ensure_open()
            if graph_name in self._graphs:
                raise ValueError(f"Graph already registered: {graph_name}")
            compiled = builder.compile(
                checkpointer=self._checkpointer,
                name=graph_name,
            )
            self._graphs[graph_name] = compiled
            return compiled

    def register_compiled(self, graph_name: str, graph: Any) -> None:
        """注册已经绑定兼容 Checkpointer 的图，主要用于外部扩展。"""

        if not graph_name:
            raise ValueError("graph_name cannot be empty")
        with self._lock:
            self._ensure_open()
            if graph_name in self._graphs:
                raise ValueError(f"Graph already registered: {graph_name}")
            self._graphs[graph_name] = graph

    def get_compiled(self, graph_name: str) -> Any:
        """返回已注册图，供需要 LangGraph 原生 async/context API 的适配层使用。"""

        return self._require_graph(graph_name)

    def has_graph(self, graph_name: str) -> bool:
        with self._lock:
            self._ensure_open()
            return graph_name in self._graphs

    def invoke(
        self,
        graph_name: str,
        *,
        thread_id: str,
        inputs: Dict[str, Any],
    ) -> GraphExecutionResult:
        graph = self._require_graph(graph_name)
        config = self._config(thread_id)
        output = graph.invoke(inputs, config=config, version="v2")
        return self._result(graph, config, output)

    def resume(
        self,
        graph_name: str,
        *,
        thread_id: str,
        value: Any,
    ) -> GraphExecutionResult:
        graph = self._require_graph(graph_name)
        config = self._config(thread_id)
        snapshot = graph.get_state(config)
        if snapshot is None or not snapshot.next:
            raise ValueError(f"Graph thread {thread_id} is not interrupted")
        output = graph.invoke(
            Command(resume=value),
            config=config,
            version="v2",
        )
        return self._result(graph, config, output)

    def continue_run(
        self,
        graph_name: str,
        *,
        thread_id: str,
    ) -> GraphExecutionResult:
        graph = self._require_graph(graph_name)
        config = self._config(thread_id)
        snapshot = graph.get_state(config)
        if snapshot is None or not snapshot.next:
            raise ValueError(f"Graph thread {thread_id} has no pending work")
        if getattr(snapshot, "interrupts", ()):
            raise ValueError(f"Graph thread {thread_id} is interrupted and requires a resume value")
        output = graph.invoke(None, config=config, version="v2")
        return self._result(graph, config, output)

    def get_state(
        self,
        graph_name: str,
        *,
        thread_id: str,
    ) -> Optional[GraphSnapshot]:
        graph = self._require_graph(graph_name)
        snapshot = graph.get_state(self._config(thread_id))
        if snapshot is None or snapshot.config is None:
            return None
        portable = self._snapshot(snapshot)
        # LangGraph 对未知 thread 返回一个空 StateSnapshot，而不是 None。
        # checkpoint_id 才表示该 thread 已真正持久化过。
        if portable.checkpoint_id is None:
            return None
        return portable

    def get_history(
        self,
        graph_name: str,
        *,
        thread_id: str,
        limit: int = 50,
    ) -> List[GraphSnapshot]:
        if limit <= 0:
            return []
        graph = self._require_graph(graph_name)
        history = graph.get_state_history(self._config(thread_id))
        return [self._snapshot(snapshot) for index, snapshot in enumerate(history) if index < limit]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def _require_graph(self, graph_name: str) -> Any:
        with self._lock:
            self._ensure_open()
            try:
                return self._graphs[graph_name]
            except KeyError as exc:
                raise KeyError(f"Unknown graph: {graph_name}") from exc

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("LangGraphRuntime is closed")

    @staticmethod
    def _config(thread_id: str) -> Dict[str, Any]:
        if not thread_id:
            raise ValueError("thread_id cannot be empty")
        return {"configurable": {"thread_id": thread_id}}

    @classmethod
    def _result(
        cls,
        graph: Any,
        config: Dict[str, Any],
        output: Any,
    ) -> GraphExecutionResult:
        snapshot = cls._snapshot(graph.get_state(config))
        interrupts = tuple(
            GraphInterrupt(id=item.id, value=item.value)
            for item in getattr(output, "interrupts", ())
        )
        values = getattr(output, "value", output) or {}
        return GraphExecutionResult(
            values=dict(values),
            interrupts=interrupts,
            snapshot=snapshot,
        )

    @staticmethod
    def _snapshot(snapshot: Any) -> GraphSnapshot:
        configurable = (snapshot.config or {}).get("configurable", {})
        interrupts = tuple(
            GraphInterrupt(id=item.id, value=item.value)
            for item in getattr(snapshot, "interrupts", ())
        )
        return GraphSnapshot(
            values=dict(snapshot.values or {}),
            next_nodes=tuple(snapshot.next or ()),
            checkpoint_id=configurable.get("checkpoint_id"),
            metadata=dict(snapshot.metadata or {}),
            interrupts=interrupts,
        )
