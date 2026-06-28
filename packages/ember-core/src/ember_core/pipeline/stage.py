"""PipelineStage — abstract base for sequential pipeline stages.

A stage represents one step in a processing pipeline.
Lifecycle: setup(ctx) → process(ctx) → teardown(ctx).

PipelineRunner guarantees teardown() always runs (via try/finally),
even if process() raises an exception.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeVar

#: Generic context type — callers define their own PipelineContext
ContextT = TypeVar("ContextT")


class PipelineStage(ABC):
    """Abstract base for a pipeline stage.

    Each stage represents one step in a sequential processing pipeline.
    The stage receives a context object, reads/writes to it, and returns it.

    Usage:
        class MyStage(PipelineStage[MyContext]):
            @property
            def name(self) -> str:
                return "my_stage"

            async def process(self, ctx: MyContext) -> MyContext:
                # do work on ctx
                return ctx
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stage name — used for logging, metrics, and stage management."""

    async def setup(self, ctx: Any) -> None:
        """Pre-process hook (optional). Called before process()."""

    @abstractmethod
    async def process(self, ctx: Any) -> Any:
        """Execute the stage's main logic. Must be implemented."""

    async def teardown(self, ctx: Any) -> None:
        """Post-process hook (optional). Always called (via try/finally)."""

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
