"""EdgeSpec / ConditionalEdge — graph edges for StateGraph.

    EdgeSpec:        unconditional: from_node → to_node
    ConditionalEdge: router(State) → routes to next_node
"""

from __future__ import annotations

from typing import Any, Callable, Dict, TypeVar

from pydantic import BaseModel, ConfigDict

StateT = TypeVar("StateT", bound=BaseModel)

#: Router function: inspects state and returns the next node name
RouterFn = Callable[[StateT], str]


class EdgeSpec(BaseModel):
    """Unconditional edge: always follows from_node → to_node."""

    from_node: str
    to_node: str


class ConditionalEdge(BaseModel):
    """Conditional edge: router inspects state and selects next node.

    The router function returns a key that is looked up in `routes`
    to determine the next node name.
    """

    from_node: str
    router: RouterFn
    routes: Dict[str, str]  # router return value → next node name

    model_config = ConfigDict(arbitrary_types_allowed=True)
