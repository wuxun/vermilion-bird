"""Tests for health checker module"""

import pytest
from unittest.mock import MagicMock
from llm_chat.health import (
    HealthStatus,
    HealthCheckResult,
    HealthChecker,
    get_checker,
    create_database_checker,
    create_service_manager_checker,
)


class TestHealthCheckResult:
    def test_create_result(self):
        result = HealthCheckResult(
            name="test",
            status=HealthStatus.HEALTHY,
            message="all good",
            details={"count": 5},
        )
        assert result.name == "test"
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "all good"
        assert result.details == {"count": 5}
        assert result.timestamp is not None

    def test_to_dict(self):
        result = HealthCheckResult(
            name="db", status=HealthStatus.UNHEALTHY, message="down"
        )
        d = result.to_dict()
        assert d["name"] == "db"
        assert d["status"] == "unhealthy"
        assert d["message"] == "down"
        assert "timestamp" in d


class TestHealthChecker:
    def test_register_and_check(self):
        checker = HealthChecker()
        checker.register_checker(
            "test_ok",
            lambda: HealthCheckResult(
                name="test_ok", status=HealthStatus.HEALTHY, message="ok"
            ),
        )
        result = checker.check("test_ok")
        assert result is not None
        assert result.status == HealthStatus.HEALTHY

    def test_check_unknown_returns_none(self):
        checker = HealthChecker()
        assert checker.check("nonexistent") is None

    def test_check_all(self):
        checker = HealthChecker()
        checker.register_checker(
            "a", lambda: HealthCheckResult("a", HealthStatus.HEALTHY, "a ok")
        )
        checker.register_checker(
            "b", lambda: HealthCheckResult("b", HealthStatus.DEGRADED, "b warn")
        )
        results = checker.check_all()
        assert len(results) == 2
        assert "a" in results
        assert "b" in results

    def test_overall_status(self):
        checker = HealthChecker()
        # Empty → UNKNOWN
        assert checker.get_overall_status({}) == HealthStatus.UNKNOWN

        # All healthy
        results = {"a": HealthCheckResult("a", HealthStatus.HEALTHY, "ok")}
        assert checker.get_overall_status(results) == HealthStatus.HEALTHY

        # One unhealthy
        results["b"] = HealthCheckResult("b", HealthStatus.UNHEALTHY, "down")
        assert checker.get_overall_status(results) == HealthStatus.UNHEALTHY

        # One degraded
        results["b"] = HealthCheckResult("b", HealthStatus.DEGRADED, "slow")
        assert checker.get_overall_status(results) == HealthStatus.DEGRADED

    def test_get_summary(self):
        checker = HealthChecker()
        checker.register_checker(
            "svc", lambda: HealthCheckResult("svc", HealthStatus.HEALTHY, "ok")
        )
        summary = checker.get_summary()
        assert summary["overall_status"] == "healthy"
        assert summary["total_checks"] == 1
        assert "svc" in summary["checks"]

    def test_unregister_checker(self):
        checker = HealthChecker()
        checker.register_checker(
            "tmp", lambda: HealthCheckResult("tmp", HealthStatus.HEALTHY, "ok")
        )
        assert checker.unregister_checker("tmp") is True
        assert checker.check("tmp") is None
        assert checker.unregister_checker("tmp") is False  # already gone

    def test_checker_exception_is_caught(self):
        checker = HealthChecker()

        def bad_checker():
            raise RuntimeError("boom")

        checker.register_checker("bad", bad_checker)
        result = checker.check("bad")
        assert result is not None
        assert result.status == HealthStatus.UNHEALTHY
        assert "boom" in result.message


class TestGlobalChecker:
    def test_get_checker_singleton(self):
        c1 = get_checker()
        c2 = get_checker()
        assert c1 is c2


class TestDatabaseChecker:
    def test_create_database_checker(self):
        mock_storage = MagicMock()
        mock_storage.list_conversations.return_value = [{"id": "1"}, {"id": "2"}]

        checker_fn = create_database_checker(mock_storage)
        result = checker_fn()
        assert result.status == HealthStatus.HEALTHY
        assert "2" in result.message
        assert result.details["conversation_count"] == 2

    def test_database_checker_error(self):
        mock_storage = MagicMock()
        mock_storage.list_conversations.side_effect = RuntimeError("db down")

        checker_fn = create_database_checker(mock_storage)
        result = checker_fn()
        assert result.status == HealthStatus.UNHEALTHY
        assert "db down" in result.message


class TestServiceManagerChecker:
    def test_all_started(self):
        mock_sm = MagicMock()
        mock_sm.get_status.return_value = {
            "services": {"scheduler": {"registered": True, "started": True}},
            "total_registered": 1,
            "total_started": 1,
        }

        checker_fn = create_service_manager_checker(mock_sm)
        result = checker_fn()
        assert result.status == HealthStatus.HEALTHY

    def test_degraded(self):
        mock_sm = MagicMock()
        mock_sm.get_status.return_value = {
            "total_registered": 2,
            "total_started": 1,
        }

        checker_fn = create_service_manager_checker(mock_sm)
        result = checker_fn()
        assert result.status == HealthStatus.DEGRADED

    def test_none_started(self):
        mock_sm = MagicMock()
        mock_sm.get_status.return_value = {
            "total_registered": 1,
            "total_started": 0,
        }

        checker_fn = create_service_manager_checker(mock_sm)
        result = checker_fn()
        assert result.status == HealthStatus.UNHEALTHY
