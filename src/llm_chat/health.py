"""健康检查模块

提供系统各组件的健康检查功能。
"""

import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """健康状态枚举"""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """健康检查结果"""

    name: str
    status: HealthStatus
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


class HealthChecker:
    """健康检查管理器

    注册和执行各个组件的健康检查。
    """

    def __init__(self):
        self._checkers: Dict[str, Callable[[], HealthCheckResult]] = {}
        logger.info("HealthChecker initialized")

    def register_checker(
        self,
        name: str,
        checker: Callable[[], HealthCheckResult],
    ) -> None:
        """注册健康检查器

        Args:
            name: 检查器名称
            checker: 检查函数，返回 HealthCheckResult
        """
        self._checkers[name] = checker
        logger.info(f"Health checker registered: {name}")

    def unregister_checker(self, name: str) -> bool:
        """注销健康检查器

        Args:
            name: 检查器名称

        Returns:
            是否成功注销
        """
        if name in self._checkers:
            del self._checkers[name]
            logger.info(f"Health checker unregistered: {name}")
            return True
        return False

    def check(self, name: str) -> Optional[HealthCheckResult]:
        """执行单个健康检查

        Args:
            name: 检查器名称

        Returns:
            检查结果，如果检查器不存在返回 None
        """
        checker = self._checkers.get(name)
        if checker is None:
            logger.warning(f"Health checker not found: {name}")
            return None

        try:
            result = checker()
            logger.debug(f"Health check {name}: {result.status.value}")
            return result
        except Exception as e:
            logger.error(f"Health check {name} failed: {e}")
            return HealthCheckResult(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=f"检查执行失败: {str(e)}",
                details={"error": str(e)},
            )

    def check_all(self) -> Dict[str, HealthCheckResult]:
        """执行所有健康检查

        Returns:
            检查结果字典，键为检查器名称
        """
        logger.info("Running all health checks...")
        results = {}
        for name in self._checkers.keys():
            result = self.check(name)
            if result:
                results[name] = result
        return results

    def get_overall_status(self, results: Dict[str, HealthCheckResult]) -> HealthStatus:
        """根据所有检查结果获取整体健康状态

        Args:
            results: 健康检查结果字典

        Returns:
            整体健康状态
        """
        if not results:
            return HealthStatus.UNKNOWN

        statuses = [r.status for r in results.values()]

        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY
        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        if all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        return HealthStatus.UNKNOWN

    def get_summary(
        self, results: Optional[Dict[str, HealthCheckResult]] = None
    ) -> Dict[str, Any]:
        """获取健康检查摘要

        Args:
            results: 健康检查结果（可选，如果不提供则重新执行所有检查）

        Returns:
            健康检查摘要字典
        """
        if results is None:
            results = self.check_all()

        overall_status = self.get_overall_status(results)

        return {
            "overall_status": overall_status.value,
            "timestamp": datetime.now().isoformat(),
            "total_checks": len(results),
            "checks": {name: result.to_dict() for name, result in results.items()},
        }


# 全局健康检查器实例
_global_checker: Optional[HealthChecker] = None


def get_checker() -> HealthChecker:
    """获取全局健康检查器实例"""
    global _global_checker
    if _global_checker is None:
        _global_checker = HealthChecker()
    return _global_checker


def create_database_checker(storage) -> Callable[[], HealthCheckResult]:
    """创建数据库健康检查器

    Args:
        storage: Storage 实例

    Returns:
        数据库检查函数
    """

    def checker() -> HealthCheckResult:
        try:
            # 尝试执行一个简单的查询
            conversations = storage.list_conversations()
            return HealthCheckResult(
                name="database",
                status=HealthStatus.HEALTHY,
                message=f"数据库连接正常，会话数: {len(conversations)}",
                details={"conversation_count": len(conversations)},
            )
        except Exception as e:
            return HealthCheckResult(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=f"数据库检查失败: {str(e)}",
                details={"error": str(e)},
            )

    return checker


def create_service_manager_checker(service_manager) -> Callable[[], HealthCheckResult]:
    """创建服务管理器健康检查器

    Args:
        service_manager: ServiceManager 实例

    Returns:
        服务管理器检查函数
    """

    def checker() -> HealthCheckResult:
        try:
            status = service_manager.get_status()
            total_services = status["total_registered"]
            started_services = status["total_started"]

            if started_services == total_services:
                status_enum = HealthStatus.HEALTHY
                message = f"所有服务运行正常 ({started_services}/{total_services})"
            elif started_services > 0:
                status_enum = HealthStatus.DEGRADED
                message = f"部分服务运行 ({started_services}/{total_services})"
            else:
                status_enum = HealthStatus.UNHEALTHY
                message = "没有服务在运行"

            return HealthCheckResult(
                name="services",
                status=status_enum,
                message=message,
                details=status,
            )
        except Exception as e:
            return HealthCheckResult(
                name="services",
                status=HealthStatus.UNHEALTHY,
                message=f"服务检查失败: {str(e)}",
                details={"error": str(e)},
            )

    return checker


def create_llm_checker(client) -> Callable[[], HealthCheckResult]:
    """创建 LLM 连通性健康检查器。

    发送一个最小 token 的测试请求，验证 LLM 是否可达。
    """

    def checker() -> HealthCheckResult:
        try:
            response = client.chat(
                "ping", max_tokens=1, temperature=0
            )
            if response:
                return HealthCheckResult(
                    name="llm",
                    status=HealthStatus.HEALTHY,
                    message=f"LLM ({client.config.llm.model}) 连接正常",
                    details={"model": client.config.llm.model},
                )
            return HealthCheckResult(
                name="llm",
                status=HealthStatus.DEGRADED,
                message="LLM 返回空响应",
            )
        except Exception as e:
            return HealthCheckResult(
                name="llm",
                status=HealthStatus.UNHEALTHY,
                message=f"LLM 连接失败: {str(e)}",
                details={"error": str(e)},
            )

    return checker


def create_disk_checker(path: str = ".") -> Callable[[], HealthCheckResult]:
    """创建磁盘空间健康检查器。"""
    import shutil

    def checker() -> HealthCheckResult:
        try:
            usage = shutil.disk_usage(path)
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            percent_used = (usage.used / usage.total) * 100

            if free_gb < 1:
                status = HealthStatus.UNHEALTHY
                msg = f"磁盘空间严重不足: {free_gb:.1f}GB / {total_gb:.1f}GB"
            elif free_gb < 5:
                status = HealthStatus.DEGRADED
                msg = f"磁盘空间偏低: {free_gb:.1f}GB / {total_gb:.1f}GB"
            else:
                status = HealthStatus.HEALTHY
                msg = f"磁盘空间正常: {free_gb:.1f}GB / {total_gb:.1f}GB"

            return HealthCheckResult(
                name="disk",
                status=status,
                message=msg,
                details={
                    "free_gb": round(free_gb, 1),
                    "total_gb": round(total_gb, 1),
                    "percent_used": round(percent_used, 1),
                },
            )
        except Exception as e:
            return HealthCheckResult(
                name="disk",
                status=HealthStatus.UNKNOWN,
                message=f"磁盘检查失败: {str(e)}",
            )

    return checker


def create_mcp_checker(mcp_manager) -> Callable[[], HealthCheckResult]:
    """创建 MCP 服务器状态健康检查器。"""

    def checker() -> HealthCheckResult:
        try:
            status = mcp_manager.get_all_status()
            if not status:
                return HealthCheckResult(
                    name="mcp",
                    status=HealthStatus.HEALTHY,
                    message="未配置 MCP 服务器",
                    details={"servers": 0},
                )

            connected = sum(
                1 for s in status.values() if s.get("connected", False)
            )
            total = len(status)

            if connected == total:
                hs = HealthStatus.HEALTHY
                msg = f"所有 MCP 服务器已连接 ({connected}/{total})"
            elif connected > 0:
                hs = HealthStatus.DEGRADED
                msg = f"部分 MCP 服务器已连接 ({connected}/{total})"
            else:
                hs = HealthStatus.UNHEALTHY
                msg = f"所有 MCP 服务器未连接 (0/{total})"

            return HealthCheckResult(
                name="mcp",
                status=hs,
                message=msg,
                details={
                    "total": total,
                    "connected": connected,
                    "servers": {
                        name: {"connected": s.get("connected", False)}
                        for name, s in status.items()
                    },
                },
            )
        except Exception as e:
            return HealthCheckResult(
                name="mcp",
                status=HealthStatus.UNKNOWN,
                message=f"MCP 检查失败: {str(e)}",
            )

    return checker
