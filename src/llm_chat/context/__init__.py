"""
上下文管理模块
提供多级上下文压缩、缓存管理和子代理上下文传递功能
"""

from .types import (
    CompressionLevel,
    ContextMessage,
    CompressionResult,
    ContextCacheEntry,
)
from .manager import ContextManager
from .compressor import ContextCompressor
from .cache import ContextCache
from .hub import (
    ContextHub,
    ContextItem,
    ContextKind,
    ContextQuery,
    ContextScope,
    Sensitivity,
    build_default_context_hub,
    ResourceContextProvider,
)
from .resources import (
    ContextResource,
    ContextResourceKind,
    ContextResourceService,
    ContextResourceSensitivity,
    ContextResourceStatus,
    ExternalTransferPolicy,
)

__all__ = [
    "CompressionLevel",
    "ContextMessage",
    "CompressionResult",
    "ContextCacheEntry",
    "ContextManager",
    "ContextCompressor",
    "ContextCache",
    "ContextHub",
    "ContextItem",
    "ContextKind",
    "ContextQuery",
    "ContextScope",
    "Sensitivity",
    "build_default_context_hub",
    "ResourceContextProvider",
    "ContextResource",
    "ContextResourceKind",
    "ContextResourceService",
    "ContextResourceSensitivity",
    "ContextResourceStatus",
    "ExternalTransferPolicy",
]
