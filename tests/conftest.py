"""conftest - shared test fixtures and configuration.

Mocking Strategy:
    APScheduler modules are mocked at session level via pytest_configure().
    This is REQUIRED because:
    1. Python 3.14 deprecated pkg_resources, which APScheduler's SQLAlchemyJobStore
       imports at module level.
    2. Our lazy-load mechanism (scheduler/__init__.py __getattr__) only protects
       production code, not any test that imports anything from llm_chat.scheduler.
    3. pytest_configure runs before any test module imports, ensuring mock is in
       place before the import chain fires.

    For tests that need real scheduler behavior, use the test_scheduler/ subdirectory
    which provides its own conftest with isolated mocks.
"""

import sys
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Session-level APScheduler mock (set up before any imports)
# ---------------------------------------------------------------------------


def pytest_configure(config):
    """Mock all APScheduler submodules before any test imports.

    Without this, Python 3.14 will fail at:
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    because SQLAlchemyJobStore does `import pkg_resources` at module level.
    """
    _APSCHEDULER_MODULES = [
        "apscheduler",
        "apscheduler.schedulers",
        "apscheduler.schedulers.background",
        "apscheduler.executors",
        "apscheduler.executors.pool",
        "apscheduler.jobstores",
        "apscheduler.jobstores.sqlalchemy",
        "apscheduler.triggers",
        "apscheduler.triggers.cron",
        "apscheduler.triggers.interval",
        "apscheduler.triggers.date",
        "apscheduler.events",
    ]
    for mod_name in _APSCHEDULER_MODULES:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()


# ---------------------------------------------------------------------------
# Reusable fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_apscheduler():
    """Return the shared APScheduler MagicMock.

    Use this in tests that need to verify APScheduler interactions.
    Example:
        def test_scheduler_start(mock_apscheduler):
            from apscheduler.schedulers.background import BackgroundScheduler
            assert BackgroundScheduler.called
    """
    return sys.modules["apscheduler"]


@pytest.fixture
def mock_scheduler_service(mocker):
    """Fixture providing a mock SchedulerService for tests that need one.

    Returns (mock_service, mock_app) tuple.
    """
    mock_app = mocker.MagicMock()
    mock_service = mocker.MagicMock()
    mock_service.name = "scheduler"
    return mock_service, mock_app
