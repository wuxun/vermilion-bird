"""
Pipeline stage abstraction — formal pipeline decomposition for ChatCore.

Exports (Phase 1):
    PipelineStage — ABC with setup/process/teardown lifecycle
    PipelineContext — per-request state dataclass
    MutableStrHolder — cross-request mutable string holder

"""

from llm_chat.pipeline.stage import PipelineStage, PipelineContext, MutableStrHolder
from llm_chat.pipeline.runner import PipelineRunner

__all__ = [
    "PipelineStage",
    "PipelineContext",
    "PipelineRunner",
    "MutableStrHolder",
]
