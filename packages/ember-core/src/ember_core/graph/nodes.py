"""NodeSpec — node definition for StateGraph.

A node is a named, pure function: (State) → State | dict[str, Any].
It can optionally be marked as an interrupt point.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

StateT = TypeVar("StateT", bound=BaseModel)

#: Node function signature: takes state, returns state or partial update dict
NodeFn = Callable[[StateT], "StateT | dict[str, Any]"]


class NodeSpec(BaseModel, Generic[StateT]):
    """A node in the state graph.

    Attributes:
        name: Unique node identifier within the graph.
        fn: Pure function (State) → State | dict.
        interrupt: If True, execution pauses after this node and waits
                   for external input via compiled.resume().
        metadata: Arbitrary metadata for observability / debugging.
    """

    name: str
    fn: NodeFn[StateT]  # excluded from equality (functions are not comparable)
    interrupt: bool = False
    metadata: Dict[str, Any] = {}

    model_config = ConfigDict(arbitrary_types_allowed=True)
