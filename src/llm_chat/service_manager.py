"""ServiceManager - 统一服务管理

统一管理应用中的所有可启动/停止的服务（调度器等）。
"""

import logging
from typing import Dict, List, Optional, Protocol, runtime_checkable, Any
from abc import abstractmethod

logger = logging.getLogger(__name__)


@runtime_checkable
class Service(Protocol):
    """服务协议，定义了可管理服务的接口"""

    @abstractmethod
    def start(self) -> None:
        """启动服务"""
        ...

    @abstractmethod
    def shutdown(self, wait: bool = True) -> None:
        """关闭服务

        Args:
            wait: 是否等待正在执行的任务完成
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """服务名称"""
        ...


class ServiceManager:
    """统一服务管理器

    负责管理应用中的所有可启动/停止的服务，提供统一的接口来：
    - 注册服务
    - 启动所有服务
    - 停止所有服务
    - 查询服务状态
    """

    def __init__(self):
        self._services: Dict[str, Service] = {}
        self._started_services: List[str] = []
        logger.info("ServiceManager initialized")

    def register_service(self, service: Service, name: Optional[str] = None) -> None:
        """注册一个服务

        Args:
            service: 服务实例
            name: 服务名称（可选，默认为 service.name）
        """
        service_name = name or service.name
        if service_name in self._services:
            logger.warning(f"Service already registered: {service_name}, will replace")

        self._services[service_name] = service
        logger.info(f"Service registered: {service_name}")

    def unregister_service(self, name: str) -> Optional[Service]:
        """取消注册一个服务

        Args:
            name: 服务名称

        Returns:
            被取消注册的服务，如果服务不存在返回 None
        """
        if name not in self._services:
            logger.warning(f"Service not registered: {name}")
            return None

        service = self._services.pop(name)
        if name in self._started_services:
            self._started_services.remove(name)

        logger.info(f"Service unregistered: {name}")
        return service

    def get_service(self, name: str) -> Optional[Service]:
        """获取一个已注册的服务

        Args:
            name: 服务名称

        Returns:
            服务实例，如果服务不存在返回 None
        """
        return self._services.get(name)

    def list_services(self) -> List[str]:
        """列出所有已注册的服务

        Returns:
            服务名称列表
        """
        return list(self._services.keys())

    def is_service_started(self, name: str) -> bool:
        """检查服务是否已启动

        Args:
            name: 服务名称

        Returns:
            True 表示服务已启动，False 表示服务未启动或不存在
        """
        return name in self._started_services

    def start_service(self, name: str) -> bool:
        """启动指定服务

        Args:
            name: 服务名称

        Returns:
            True 表示启动成功，False 表示服务不存在或已启动
        """
        if name not in self._services:
            logger.error(f"Cannot start service: {name} (not registered)")
            return False

        if name in self._started_services:
            logger.warning(f"Service already started: {name}")
            return False

        try:
            service = self._services[name]
            logger.info(f"Starting service: {name}")
            service.start()
            self._started_services.append(name)
            logger.info(f"Service started successfully: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to start service {name}: {e}")
            import traceback

            traceback.print_exc()
            return False

    def start_all(self) -> int:
        """启动所有已注册的服务

        Returns:
            成功启动的服务数量
        """
        logger.info("Starting all services...")
        success_count = 0

        for name in self._services.keys():
            if self.start_service(name):
                success_count += 1

        logger.info(f"Started {success_count}/{len(self._services)} services")
        return success_count

    def stop_service(self, name: str, wait: bool = True) -> bool:
        """停止指定服务

        Args:
            name: 服务名称
            wait: 是否等待正在执行的任务完成

        Returns:
            True 表示停止成功，False 表示服务不存在或未启动
        """
        if name not in self._services:
            logger.error(f"Cannot stop service: {name} (not registered)")
            return False

        if name not in self._started_services:
            logger.warning(f"Service not started: {name}")
            return False

        try:
            service = self._services[name]
            logger.info(f"Stopping service: {name} (wait={wait})")
            service.shutdown(wait=wait)
            self._started_services.remove(name)
            logger.info(f"Service stopped successfully: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to stop service {name}: {e}")
            import traceback

            traceback.print_exc()
            return False

    def stop_all(self, wait: bool = True) -> int:
        """停止所有已启动的服务

        Args:
            wait: 是否等待正在执行的任务完成

        Returns:
            成功停止的服务数量
        """
        logger.info("Stopping all services...")
        success_count = 0

        # 按启动顺序的逆序停止
        for name in reversed(self._started_services.copy()):
            if self.stop_service(name, wait=wait):
                success_count += 1

        logger.info(f"Stopped {success_count} services")
        return success_count

    def get_status(self) -> Dict[str, Any]:
        """获取所有服务的状态

        Returns:
            服务状态字典，格式为：
            {
                "services": {
                    "service_name": {
                        "registered": True,
                        "started": True
                    }
                },
                "total_registered": 2,
                "total_started": 1
            }
        """
        status = {
            "services": {},
            "total_registered": len(self._services),
            "total_started": len(self._started_services),
        }

        for name in self._services.keys():
            status["services"][name] = {
                "registered": True,
                "started": name in self._started_services,
            }

        return status
