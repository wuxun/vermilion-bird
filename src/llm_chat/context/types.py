from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


class CompressionLevel(Enum):
    """上下文压缩级别"""

    NONE = 0  # 无压缩，原始上下文
    MICRO = 1  # 微压缩：替换旧工具结果为占位符，节省~30% token，无精度损失
    AUTO = 2  # 自动压缩：token超阈值时自动总结，保存完整记录到磁盘，节省~60% token，精度损失<5%
    MANUAL = 3  # 手动压缩：手动触发总结，节省~80% token，精度损失<10%


@dataclass
class ContextMessage:
    """上下文消息结构"""

    role: str
    content: str
    metadata: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextMessage":
        return cls(
            role=data["role"],
            content=data["content"],
            metadata=data.get("metadata"),
            timestamp=data.get("timestamp"),
        )


@dataclass
class CompressionResult:
    """压缩结果"""

    level: CompressionLevel
    messages: List[ContextMessage]
    original_token_count: int
    compressed_token_count: int
    compression_ratio: float  # 压缩后/压缩前
    saved_tokens: int  # 节省的token数量
    full_transcript_path: Optional[str] = None  # 完整记录保存路径，仅AUTO/MANUAL级别有


@dataclass
class ContextCacheEntry:
    """上下文缓存条目"""

    cache_key: str
    conversation_id: str
    compression_level: CompressionLevel
    messages: List[ContextMessage]
    token_count: int
    created_at: float
    last_accessed: float
    access_count: int = 0
