"""调度器 & Webhook 配置。"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class SchedulerConfig(BaseSettings):
    """Scheduler 配置，用于调度并发执行任务的参数。

    注意：不包含 db_path 字段，复用现有数据库。
    """

    enabled: bool = Field(default=True, description="是否启用调度器")
    max_workers: int = Field(default=4, description="调度器并发最大工作线程数")
    default_timezone: str = Field(default="UTC", description="默认时区")
    webhook_enabled: bool = Field(
        default=False, description="启用 webhook 事件驱动触发器"
    )
    webhook_port: int = Field(
        default=9100, description="Webhook HTTP 服务器端口"
    )
    webhook_host: str = Field(
        default="127.0.0.1", description="Webhook HTTP 服务器监听地址"
    )
    proactive_enabled: bool = Field(
        default=True, description="启用每日主动聊天"
    )
    proactive_hour: int = Field(
        default=9, ge=0, le=23, description="主动聊天触发小时 (0-23)（兼容旧配置）"
    )
    proactive_minute: int = Field(
        default=0, ge=0, le=59, description="主动聊天触发分钟 (0-59)（兼容旧配置）"
    )
    proactive_rss_feeds: list = Field(
        default=[],
        description="RSS 源 URL 列表，用于 ProactiveAgent 新闻采集（feedparser 解析）",
    )

    class Config:
        env_prefix = "SCHEDULER_"
        case_sensitive = False

    @field_validator("max_workers")
    @classmethod
    def validate_max_workers(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"最大工作线程数必须大于0，得到: {v}")
        return v

    @field_validator("default_timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            import pytz
            pytz.timezone(v)
        except ImportError:
            pass
        except Exception:
            raise ValueError(f"无效的时区: {v}")
        return v
