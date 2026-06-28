"""ChannelReducer — strategies for merging state field updates.

When a node returns a partial state update (dict), the graph engine
must decide how to merge each field into the current state.

Built-in strategies:
    ReplaceReducer  — new value overwrites (default)
    AppendReducer   — append to list (for message histories)
    MergeReducer    — deep merge dicts (for nested state)
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from typing import Any


class ChannelReducer(ABC):
    """Abstract strategy for merging a state field update."""

    @abstractmethod
    def apply(self, current: Any, update: Any) -> Any:
        """Merge `update` into `current`, returning the new value."""


class ReplaceReducer(ChannelReducer):
    """Default: new value replaces old value entirely."""

    def apply(self, current: Any, update: Any) -> Any:
        return update


class AppendReducer(ChannelReducer):
    """Append update to a list. Useful for accumulating messages.

    Both current and update should be iterables.
    """

    def apply(self, current: Any, update: Any) -> Any:
        if current is None:
            current = []
        if update is None:
            return current
        if not isinstance(current, list):
            current = [current]
        if isinstance(update, list):
            return current + update
        return current + [update]


class MergeReducer(ChannelReducer):
    """Deep merge update dict into current dict.

    Useful for accumulating structured results across nodes.
    """

    def apply(self, current: Any, update: Any) -> Any:
        if current is None:
            return copy.deepcopy(update) if update is not None else {}
        if update is None:
            return current
        if not isinstance(current, dict) or not isinstance(update, dict):
            return update
        result = copy.deepcopy(current)
        _deep_merge(result, update)
        return result


def _deep_merge(base: dict, update: dict) -> None:
    """Merge `update` into `base` in-place, recursively."""
    for key, value in update.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)


# Default reducer used when no explicit reducer is specified
DEFAULT_REDUCER: ChannelReducer = ReplaceReducer()
