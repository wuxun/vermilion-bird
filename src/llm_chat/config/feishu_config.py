"""飞书/Lark 集成配置。"""

from __future__ import annotations

from typing import Optional
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class FeishuConfig(BaseSettings):
    """飞书/Lark 应用配置。"""

    enabled: bool = Field(default=False, description="是否启用飞书集成")
    app_id: Optional[str] = Field(default=None, description="飞书应用 ID")
    app_secret: Optional[str] = Field(default=None, description="飞书应用密钥")
    tenant_key: Optional[str] = Field(default=None, description="飞书租户密钥")
    encrypt_key: Optional[str] = Field(default=None, description="飞书事件加密密钥")
    verification_token: Optional[str] = Field(
        default=None, description="飞书事件验证令牌"
    )

    @model_validator(mode="after")
    def validate_credentials_when_enabled(self) -> "FeishuConfig":
        """当 enabled=True 时，验证 app_id 和 app_secret 必须不为空。"""
        if self.enabled:
            if not self.app_id or not self.app_secret:
                raise ValueError("飞书集成已启用但 app_id 或 app_secret 为空")
        return self
