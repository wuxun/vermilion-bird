"""任务资源授权的匹配与生命周期服务。"""

from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Set
from urllib.parse import urlparse

from llm_chat.runtime import Capability

from .models import (
    GrantScope,
    GrantStatus,
    ResourceGrant,
    ResourceType,
)


class ResourceGrantRepository(Protocol):
    def create_resource_grant(self, grant: ResourceGrant) -> bool:
        ...

    def save_resource_grant(self, grant: ResourceGrant) -> None:
        ...

    def get_resource_grant(self, grant_id: str) -> Optional[ResourceGrant]:
        ...

    def list_resource_grants(
        self,
        *,
        work_item_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        status: Optional[GrantStatus] = None,
        limit: int = 200,
    ) -> List[ResourceGrant]:
        ...


class ResourceGrantService:
    """按能力和规范化资源匹配授权，不对模糊参数做推断。"""

    _DIRECTORY_ARGUMENTS = (
        "path",
        "file_path",
        "directory",
        "working_directory",
        "cwd",
        "destination",
        "target_path",
    )
    _DOMAIN_ARGUMENTS = ("url", "uri", "domain", "endpoint")
    _MESSAGE_ARGUMENTS = (
        "recipient",
        "target",
        "chat_id",
        "open_id",
        "email",
        "channel",
    )

    def __init__(self, repository: ResourceGrantRepository):
        self.repository = repository

    def create(
        self,
        *,
        capability: str,
        resource_type: ResourceType,
        resource: str,
        work_item_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        scope: GrantScope = GrantScope.WORK_ITEM,
        expires_at: Optional[datetime] = None,
        reason: str = "",
        created_by: str = "local-user",
    ) -> ResourceGrant:
        capability = Capability(capability).value
        if not isinstance(resource_type, ResourceType):
            resource_type = ResourceType(resource_type)
        if not isinstance(scope, GrantScope):
            scope = GrantScope(scope)
        if scope == GrantScope.WORK_ITEM and not work_item_id:
            raise ValueError("work-item grant requires work_item_id")
        if scope == GrantScope.WORKFLOW and not workflow_id:
            raise ValueError("workflow grant requires workflow_id")
        normalized = self._normalize_resource(resource_type, resource)
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        grant = ResourceGrant(
            work_item_id=work_item_id,
            workflow_id=workflow_id,
            capability=capability,
            resource_type=resource_type,
            resource=normalized,
            scope=scope,
            expires_at=expires_at,
            reason=reason.strip(),
            created_by=created_by.strip() or "local-user",
        )
        if not self.repository.create_resource_grant(grant):
            raise ValueError("equivalent active resource grant already exists")
        return grant.model_copy(deep=True)

    def revoke(self, grant_id: str) -> ResourceGrant:
        grant = self.repository.get_resource_grant(grant_id)
        if grant is None:
            raise KeyError(f"Unknown resource grant: {grant_id}")
        if grant.status == GrantStatus.REVOKED:
            return grant
        grant.status = GrantStatus.REVOKED
        grant.revoked_at = datetime.now(timezone.utc)
        self.repository.save_resource_grant(grant)
        return grant.model_copy(deep=True)

    def list(
        self,
        *,
        work_item_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        include_inactive: bool = False,
        limit: int = 200,
    ) -> List[ResourceGrant]:
        grants = self.repository.list_resource_grants(
            work_item_id=work_item_id,
            workflow_id=workflow_id,
            status=None if include_inactive else GrantStatus.ACTIVE,
            limit=limit,
        )
        return [self._expire_if_needed(grant) for grant in grants]

    def authorizes_tool(
        self,
        *,
        work_item_id: Optional[str],
        workflow_id: Optional[str],
        tool_name: str,
        arguments: Dict[str, Any],
        capabilities: Iterable[Capability],
        workspace: Optional[str] = None,
    ) -> bool:
        """所有需审批能力都必须存在精确资源匹配；进程/密钥永不自动放行。"""

        required: Set[Capability] = set(capabilities)
        if not required:
            return False
        if required & {Capability.PROCESS, Capability.SECRETS}:
            return False
        grants = self.list(
            work_item_id=work_item_id,
            workflow_id=workflow_id,
        )
        for capability in required:
            resource_type, resource = self._tool_resource(
                capability,
                arguments,
                workspace=workspace,
            )
            if resource_type is None or resource is None:
                return False
            matching = [
                grant
                for grant in grants
                if grant.status == GrantStatus.ACTIVE
                and grant.capability == capability.value
                and grant.resource_type == resource_type
                and self._matches(grant, resource)
            ]
            if not matching:
                return False
        now = datetime.now(timezone.utc)
        for grant in grants:
            if grant.scope == GrantScope.ONCE and self._grant_matches_call(
                grant,
                required,
                arguments,
                workspace=workspace,
            ):
                grant.status = GrantStatus.REVOKED
                grant.last_used_at = now
                grant.revoked_at = now
                self.repository.save_resource_grant(grant)
            elif self._grant_matches_call(
                grant,
                required,
                arguments,
                workspace=workspace,
            ):
                grant.last_used_at = now
                self.repository.save_resource_grant(grant)
        return True

    def _expire_if_needed(self, grant: ResourceGrant) -> ResourceGrant:
        if (
            grant.status == GrantStatus.ACTIVE
            and grant.expires_at is not None
            and grant.expires_at <= datetime.now(timezone.utc)
        ):
            grant.status = GrantStatus.EXPIRED
            self.repository.save_resource_grant(grant)
        return grant.model_copy(deep=True)

    def _grant_matches_call(
        self,
        grant: ResourceGrant,
        capabilities: Set[Capability],
        arguments: Dict[str, Any],
        *,
        workspace: Optional[str] = None,
    ) -> bool:
        if grant.status != GrantStatus.ACTIVE:
            return False
        capability = Capability(grant.capability)
        if capability not in capabilities:
            return False
        resource_type, resource = self._tool_resource(
            capability,
            arguments,
            workspace=workspace,
        )
        return (
            resource_type == grant.resource_type
            and resource is not None
            and self._matches(grant, resource)
        )

    def _tool_resource(
        self,
        capability: Capability,
        arguments: Dict[str, Any],
        *,
        workspace: Optional[str] = None,
    ):
        if capability in {Capability.WORKSPACE_WRITE, Capability.READ}:
            value = self._first_string(arguments, self._DIRECTORY_ARGUMENTS)
            return (
                ResourceType.DIRECTORY,
                (self._normalize_directory(value, workspace=workspace) if value else None),
            )
        if capability == Capability.NETWORK:
            value = self._first_string(arguments, self._DOMAIN_ARGUMENTS)
            return (
                ResourceType.DOMAIN,
                self._normalize_resource(ResourceType.DOMAIN, value) if value else None,
            )
        if capability == Capability.EXTERNAL_MESSAGE:
            value = self._first_string(arguments, self._MESSAGE_ARGUMENTS)
            return (
                ResourceType.MESSAGE_TARGET,
                self._normalize_resource(ResourceType.MESSAGE_TARGET, value) if value else None,
            )
        return None, None

    @staticmethod
    def _first_string(arguments: Dict[str, Any], names) -> Optional[str]:
        for name in names:
            value = arguments.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _normalize_resource(resource_type: ResourceType, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("resource cannot be empty")
        if resource_type == ResourceType.DIRECTORY:
            return ResourceGrantService._normalize_directory(value)
        if resource_type == ResourceType.DOMAIN:
            parsed = urlparse(value if "://" in value else f"//{value}")
            host = (parsed.hostname or "").lower().rstrip(".")
            if not host:
                raise ValueError("invalid domain resource")
            return host
        return value.casefold()

    @staticmethod
    def _normalize_directory(value: str, *, workspace: Optional[str] = None) -> str:
        path = Path(value).expanduser()
        if not path.is_absolute() and workspace:
            path = Path(workspace).expanduser() / path
        return str(path.resolve(strict=False))

    @staticmethod
    def _matches(grant: ResourceGrant, candidate: str) -> bool:
        if grant.resource_type == ResourceType.DIRECTORY:
            granted = Path(grant.resource)
            target = Path(candidate)
            return target == granted or granted in target.parents
        if grant.resource_type == ResourceType.DOMAIN:
            try:
                ipaddress.ip_address(candidate)
                return candidate == grant.resource
            except ValueError:
                return candidate == grant.resource or candidate.endswith(f".{grant.resource}")
        return candidate.casefold() == grant.resource.casefold()
