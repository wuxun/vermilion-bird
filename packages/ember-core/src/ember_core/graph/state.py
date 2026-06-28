"""StateGraph — typed state graph builder and compiled executor.

Usage:
    class MyState(BaseModel):
        messages: list = Field(default_factory=list,
                               json_schema_extra={"reducer": AppendReducer()})
        result: str = ""

    graph = StateGraph(MyState)
    graph.add_node("process", my_fn)
    graph.add_conditional_edge("process", router_fn, {"loop": "process", "end": "__finish__"})
    graph.set_entry_point("process")

    compiled = graph.compile(checkpointer=SQLiteCheckpointer(store))
    result = compiled.invoke(MyState())
"""

from __future__ import annotations

import copy
import uuid
import logging
from typing import (
    Any, Callable, Dict, Generic, Iterator, List, Optional, Set, TypeVar, Union,
)

from pydantic import BaseModel, ConfigDict

from ember_core.graph.reducer import (
    ChannelReducer, ReplaceReducer, DEFAULT_REDUCER,
)
from ember_core.graph.nodes import NodeSpec, NodeFn
from ember_core.graph.edges import EdgeSpec, ConditionalEdge, RouterFn
from ember_core.graph.checkpoint import Checkpointer, MemoryCheckpointer

logger = logging.getLogger(__name__)

StateT = TypeVar("StateT", bound=BaseModel)

# Sentinel for "finish execution"
_FINISH = "__finish__"


# ── State update event ─────────────────────────────────────────────


class StateUpdate(BaseModel, Generic[StateT]):
    """Emitted by compiled.stream() for each node execution."""

    node_name: str
    state: StateT
    step: int
    interrupt: bool = False  # True if paused at this node

    model_config = ConfigDict(arbitrary_types_allowed=True)


# ── State merge helpers ────────────────────────────────────────────


def _get_reducers(state_schema: type[BaseModel]) -> Dict[str, ChannelReducer]:
    """Extract per-field reducers from Pydantic model Field annotations.

    Looks for `json_schema_extra={"reducer": MyReducer()}` in Field() calls.
    """
    reducers: Dict[str, ChannelReducer] = {}
    for field_name, field_info in state_schema.model_fields.items():
        extra = field_info.json_schema_extra
        if isinstance(extra, dict) and "reducer" in extra:
            reducers[field_name] = extra["reducer"]
    return reducers


def _apply_update(
    state: BaseModel, update: dict, reducers: Dict[str, ChannelReducer]
) -> BaseModel:
    """Apply a partial dict update to a Pydantic state, respecting reducers.

    Returns a new state instance (state is never mutated in place).
    """
    merged = dict(state)
    for key, value in update.items():
        if value is None and key not in merged:
            continue
        reducer = reducers.get(key, DEFAULT_REDUCER)
        current = merged.get(key)
        merged[key] = reducer.apply(current, value)
    return state.__class__(**merged)


# ── StateGraph builder ─────────────────────────────────────────────


class StateGraph(Generic[StateT]):
    """Typed state graph builder.

    Nodes are pure functions: (State) → State | dict.
    Edges are either unconditional or conditional (router-based).
    """

    def __init__(self, state_schema: type[StateT]):
        self._state_schema = state_schema
        self._nodes: Dict[str, NodeSpec[StateT]] = {}
        self._edges: List[EdgeSpec | ConditionalEdge] = []
        self._entry_point: Optional[str] = None
        self._reducers = _get_reducers(state_schema)

    # ── Build ──────────────────────────────────────────────────

    def add_node(
        self,
        name: str,
        fn: NodeFn[StateT],
        *,
        interrupt: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "StateGraph[StateT]":
        """Register a node."""
        if name in ("__finish__", "__start__"):
            raise ValueError(f"Reserved node name: {name}")
        self._nodes[name] = NodeSpec(
            name=name,
            fn=fn,
            interrupt=interrupt,
            metadata=metadata or {},
        )
        return self

    def add_edge(self, from_node: str, to_node: str) -> "StateGraph[StateT]":
        """Add an unconditional edge."""
        self._edges.append(EdgeSpec(from_node=from_node, to_node=to_node))
        return self

    def add_conditional_edge(
        self,
        from_node: str,
        router: RouterFn,
        routes: Dict[str, str],
    ) -> "StateGraph[StateT]":
        """Add a conditional edge with a router function.

        The router receives the current state and returns a key.
        That key is looked up in `routes` to determine the next node.
        """
        self._edges.append(
            ConditionalEdge(from_node=from_node, router=router, routes=routes)
        )
        return self

    def set_entry_point(self, node: str) -> "StateGraph[StateT]":
        """Set the graph's entry point node."""
        self._entry_point = node
        return self

    # ── Compile ────────────────────────────────────────────────

    def compile(
        self,
        *,
        checkpointer: Optional[Checkpointer] = None,
        interrupt_before: Optional[List[str]] = None,
        interrupt_after: Optional[List[str]] = None,
    ) -> "CompiledGraph[StateT]":
        """Compile the graph into an executable.

        Args:
            checkpointer: Optional persistence for state snapshots.
            interrupt_before: Node names to pause BEFORE executing.
            interrupt_after: Node names to pause AFTER executing.
        """
        if self._entry_point is None:
            raise ValueError("No entry point set. Call set_entry_point().")

        # Build adjacency maps
        unconditional: Dict[str, List[str]] = {}
        conditional: Dict[str, ConditionalEdge] = {}

        for edge in self._edges:
            if isinstance(edge, EdgeSpec):
                unconditional.setdefault(edge.from_node, []).append(edge.to_node)
            elif isinstance(edge, ConditionalEdge):
                if edge.from_node in conditional:
                    raise ValueError(
                        f"Node '{edge.from_node}' already has a conditional edge. "
                        "Only one conditional edge per node."
                    )
                conditional[edge.from_node] = edge

        # Resolve interrupt sets
        ib_set: Set[str] = set(interrupt_before or [])
        ia_set: Set[str] = set(interrupt_after or [])

        # Validate
        all_node_names = set(self._nodes.keys())
        for edge in self._edges:
            if edge.from_node not in all_node_names:
                raise ValueError(f"Edge from unknown node: {edge.from_node}")
        for ib in ib_set:
            if ib not in all_node_names:
                raise ValueError(f"interrupt_before unknown node: {ib}")
        for ia in ia_set:
            if ia not in all_node_names:
                raise ValueError(f"interrupt_after unknown node: {ia}")

        return CompiledGraph(
            state_schema=self._state_schema,
            nodes=self._nodes,
            entry_point=self._entry_point,
            unconditional=unconditional,
            conditional=conditional,
            reducers=self._reducers,
            checkpointer=checkpointer,
            interrupt_before=ib_set,
            interrupt_after=ia_set,
        )


# ── CompiledGraph (executable) ────────────────────────────────────


class CompiledGraph(Generic[StateT]):
    """Compiled, executable state graph.

    Supports three execution modes:
        invoke(state)   — run synchronously
        stream(state)   — yield state after each node
        ainvoke(state)  — async invoke (supports async node functions)
        astream(state)  — async stream
        resume(id, input) — resume from an interrupt point
    """

    def __init__(
        self,
        state_schema: type[StateT],
        nodes: Dict[str, NodeSpec[StateT]],
        entry_point: str,
        unconditional: Dict[str, List[str]],
        conditional: Dict[str, ConditionalEdge],
        reducers: Dict[str, ChannelReducer],
        checkpointer: Optional[Checkpointer] = None,
        interrupt_before: Optional[Set[str]] = None,
        interrupt_after: Optional[Set[str]] = None,
    ):
        self._state_schema = state_schema
        self._nodes = nodes
        self._entry_point = entry_point
        self._unconditional = unconditional
        self._conditional = conditional
        self._reducers = reducers
        self._checkpointer = checkpointer or MemoryCheckpointer()
        self._interrupt_before = interrupt_before or set()
        self._interrupt_after = interrupt_after or set()

    # ── Invoke ─────────────────────────────────────────────────

    def invoke(
        self, state: StateT, *,
        thread_id: Optional[str] = None,
        _start_node: Optional[str] = None,  # internal: used by resume()
    ) -> StateT:
        """Run to completion. Returns final state."""
        thread_id = thread_id or uuid.uuid4().hex[:12]
        current_node = _start_node or self._entry_point
        step = 0

        while current_node != _FINISH:
            # Check for interrupt BEFORE
            if current_node in self._interrupt_before:
                self._checkpointer.save(
                    thread_id, step, current_node,
                    state.model_dump(),
                )
                # Return current state — caller must call resume()
                return state

            node_spec = self._nodes[current_node]

            # Execute
            update = node_spec.fn(state)

            if isinstance(update, dict):
                state = _apply_update(state, update, self._reducers)
            elif isinstance(update, self._state_schema):
                state = update
            elif update is None:
                pass  # no state change
            else:
                logger.warning(
                    "Node '%s' returned unexpected type %s, ignoring",
                    current_node, type(update),
                )

            step += 1

            # Check for interrupt AFTER
            if current_node in self._interrupt_after or node_spec.interrupt:
                self._checkpointer.save(
                    thread_id, step, current_node,
                    state.model_dump(),
                )
                return state

            # Save checkpoint
            self._checkpointer.save(
                thread_id, step, current_node,
                state.model_dump(),
            )

            # Determine next node
            current_node = self._resolve_next(current_node, state)

        return state

    # ── Stream ─────────────────────────────────────────────────

    def stream(
        self, state: StateT, *, thread_id: Optional[str] = None
    ) -> Iterator[StateUpdate[StateT]]:
        """Run to completion, yielding StateUpdate after each node."""
        thread_id = thread_id or uuid.uuid4().hex[:12]
        current_node = self._entry_point
        step = 0

        while current_node != _FINISH:
            if current_node in self._interrupt_before:
                yield StateUpdate(
                    node_name=current_node,
                    state=state,
                    step=step,
                    interrupt=True,
                )
                return

            node_spec = self._nodes[current_node]
            update = node_spec.fn(state)

            if isinstance(update, dict):
                state = _apply_update(state, update, self._reducers)
            elif isinstance(update, self._state_schema):
                state = update

            step += 1
            interrupt = (
                current_node in self._interrupt_after
                or node_spec.interrupt
            )

            yield StateUpdate(
                node_name=current_node,
                state=state,
                step=step,
                interrupt=interrupt,
            )

            if interrupt:
                self._checkpointer.save(
                    thread_id, step, current_node,
                    state.model_dump(),
                )
                return

            self._checkpointer.save(
                thread_id, step, current_node,
                state.model_dump(),
            )

            current_node = self._resolve_next(current_node, state)

    # ── Async Invoke ───────────────────────────────────────────

    async def ainvoke(
        self, state: StateT, *,
        thread_id: Optional[str] = None,
        _start_node: Optional[str] = None,
    ) -> StateT:
        """Async invoke — supports async node functions."""
        import inspect
        thread_id = thread_id or uuid.uuid4().hex[:12]
        current_node = _start_node or self._entry_point
        step = 0

        while current_node != _FINISH:
            if current_node in self._interrupt_before:
                self._checkpointer.save(thread_id, step, current_node, state.model_dump())
                return state

            node_spec = self._nodes[current_node]

            # Execute — support both sync and async node functions
            if inspect.iscoroutinefunction(node_spec.fn):
                update = await node_spec.fn(state)
            else:
                update = node_spec.fn(state)

            if isinstance(update, dict):
                state = _apply_update(state, update, self._reducers)
            elif isinstance(update, self._state_schema):
                state = update

            step += 1

            if current_node in self._interrupt_after or node_spec.interrupt:
                self._checkpointer.save(thread_id, step, current_node, state.model_dump())
                return state

            self._checkpointer.save(thread_id, step, current_node, state.model_dump())
            current_node = self._resolve_next(current_node, state)

        return state

    # ── Async Stream ───────────────────────────────────────────

    async def astream(
        self, state: StateT, *,
        thread_id: Optional[str] = None,
    ):
        """Async stream — yields StateUpdate, supports async node functions."""
        import inspect
        thread_id = thread_id or uuid.uuid4().hex[:12]
        current_node = self._entry_point
        step = 0

        while current_node != _FINISH:
            if current_node in self._interrupt_before:
                yield StateUpdate(node_name=current_node, state=state, step=step, interrupt=True)
                return

            node_spec = self._nodes[current_node]

            if inspect.iscoroutinefunction(node_spec.fn):
                update = await node_spec.fn(state)
            else:
                update = node_spec.fn(state)

            if isinstance(update, dict):
                state = _apply_update(state, update, self._reducers)
            elif isinstance(update, self._state_schema):
                state = update

            step += 1
            interrupt = current_node in self._interrupt_after or node_spec.interrupt

            yield StateUpdate(node_name=current_node, state=state, step=step, interrupt=interrupt)

            if interrupt:
                self._checkpointer.save(thread_id, step, current_node, state.model_dump())
                return

            self._checkpointer.save(thread_id, step, current_node, state.model_dump())
            current_node = self._resolve_next(current_node, state)

    # ── Resume ─────────────────────────────────────────────────

    def resume(
        self, thread_id: str, user_input: Optional[dict] = None
    ) -> Optional[StateT]:
        """Resume execution from the last interrupt point.

        Args:
            thread_id: Same thread_id used in the original invoke/stream.
            user_input: Optional dict to merge into state (e.g., user approval).

        Returns:
            Final state, or None if no checkpoint found.
        """
        checkpoint = self._checkpointer.load(thread_id)
        if checkpoint is None:
            logger.warning("No checkpoint found for thread '%s'", thread_id)
            return None

        step, node_name, state_dict = checkpoint
        state = self._state_schema(**state_dict)

        if user_input:
            state = _apply_update(state, user_input, self._reducers)

        # Resume from the node AFTER the one that was interrupted.
        # Clear the interrupted node from both interrupt sets so it
        # won't re-trigger on loop re-entry.
        next_node = self._resolve_next(node_name, state)
        saved_ib = self._interrupt_before
        saved_ia = self._interrupt_after
        self._interrupt_before = self._interrupt_before - {node_name}
        self._interrupt_after = self._interrupt_after - {node_name}
        try:
            return self.invoke(state, thread_id=thread_id, _start_node=next_node)
        finally:
            self._interrupt_before = saved_ib
            self._interrupt_after = saved_ia

    # ── Internal ────────────────────────────────────────────────

    def _resolve_next(self, current_node: str, state: StateT) -> str:
        """Determine the next node from the current node."""
        # Check conditional edge first
        if current_node in self._conditional:
            ce = self._conditional[current_node]
            key = ce.router(state)
            if key not in ce.routes:
                raise ValueError(
                    f"Router for node '{current_node}' returned '{key}', "
                    f"which is not in routes: {list(ce.routes.keys())}"
                )
            return ce.routes[key]

        # Check unconditional edges
        targets = self._unconditional.get(current_node, [])
        if len(targets) == 1:
            return targets[0]
        elif len(targets) == 0:
            return _FINISH
        else:
            raise ValueError(
                f"Node '{current_node}' has {len(targets)} unconditional edges. "
                "Use a conditional edge for branching."
            )
