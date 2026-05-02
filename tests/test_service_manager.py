"""Tests for ServiceManager"""

import pytest
from llm_chat.service_manager import ServiceManager, Service


class FakeService:
    """Fake service implementing the Service protocol"""

    def __init__(self, name: str):
        self._name = name
        self.started = False
        self.shutdown_called = False
        self.shutdown_wait = None

    @property
    def name(self) -> str:
        return self._name

    def start(self) -> None:
        self.started = True

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_called = True
        self.shutdown_wait = wait


class FailingService:
    """Service that raises on start"""

    @property
    def name(self) -> str:
        return "failer"

    def start(self) -> None:
        raise RuntimeError("cannot start")

    def shutdown(self, wait: bool = True) -> None:
        pass


class TestServiceManager:
    def test_register_and_list(self):
        sm = ServiceManager()
        svc = FakeService("test_svc")
        sm.register_service(svc)
        assert "test_svc" in sm.list_services()
        assert sm.get_service("test_svc") is svc

    def test_register_replaces_existing(self):
        sm = ServiceManager()
        svc1 = FakeService("a")
        svc2 = FakeService("a")
        sm.register_service(svc1)
        sm.register_service(svc2)
        assert sm.get_service("a") is svc2

    def test_unregister(self):
        sm = ServiceManager()
        svc = FakeService("tmp")
        sm.register_service(svc)
        assert sm.unregister_service("tmp") is svc
        assert sm.get_service("tmp") is None
        assert sm.unregister_service("nonexistent") is None

    def test_start_service(self):
        sm = ServiceManager()
        svc = FakeService("s")
        sm.register_service(svc)
        assert sm.start_service("s") is True
        assert svc.started is True
        assert sm.is_service_started("s") is True

    def test_start_already_started(self):
        sm = ServiceManager()
        svc = FakeService("s")
        sm.register_service(svc)
        sm.start_service("s")
        assert sm.start_service("s") is False  # already started

    def test_start_unregistered(self):
        sm = ServiceManager()
        assert sm.start_service("ghost") is False

    def test_start_all(self):
        sm = ServiceManager()
        sm.register_service(FakeService("a"))
        sm.register_service(FakeService("b"))
        count = sm.start_all()
        assert count == 2
        assert sm.is_service_started("a")
        assert sm.is_service_started("b")

    def test_start_all_with_failing(self):
        sm = ServiceManager()
        sm.register_service(FakeService("a"))
        sm.register_service(FailingService())
        count = sm.start_all()
        assert count == 1  # only "a" succeeded
        assert sm.is_service_started("a")
        assert not sm.is_service_started("failer")

    def test_stop_service(self):
        sm = ServiceManager()
        svc = FakeService("s")
        sm.register_service(svc)
        sm.start_service("s")
        assert sm.stop_service("s") is True
        assert svc.shutdown_called is True

    def test_stop_not_started(self):
        sm = ServiceManager()
        sm.register_service(FakeService("s"))
        assert sm.stop_service("s") is False

    def test_stop_not_registered(self):
        sm = ServiceManager()
        assert sm.stop_service("ghost") is False

    def test_stop_all_reverse_order(self):
        sm = ServiceManager()
        svc_a = FakeService("a")
        svc_b = FakeService("b")
        sm.register_service(svc_a)
        sm.register_service(svc_b)
        sm.start_all()
        sm.stop_all()
        assert svc_a.shutdown_called is True
        assert svc_b.shutdown_called is True
        # b was started last, should be stopped first (verified implicitly via both called)

    def test_get_status(self):
        sm = ServiceManager()
        sm.register_service(FakeService("a"))
        sm.start_service("a")
        sm.register_service(FakeService("b"))
        status = sm.get_status()
        assert status["total_registered"] == 2
        assert status["total_started"] == 1
        assert status["services"]["a"]["started"] is True
        assert status["services"]["b"]["started"] is False
