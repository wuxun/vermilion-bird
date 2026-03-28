"""conftest for app tests - mock APScheduler before imports"""

import sys
from unittest.mock import MagicMock


def pytest_configure(config):
    """Mock APScheduler modules before any imports"""
    sys.modules["apscheduler"] = MagicMock()
    sys.modules["apscheduler.schedulers"] = MagicMock()
    sys.modules["apscheduler.schedulers.background"] = MagicMock()
    sys.modules["apscheduler.executors"] = MagicMock()
    sys.modules["apscheduler.executors.pool"] = MagicMock()
    sys.modules["apscheduler.jobstores"] = MagicMock()
    sys.modules["apscheduler.jobstores.sqlalchemy"] = MagicMock()
    sys.modules["apscheduler.triggers"] = MagicMock()
    sys.modules["apscheduler.triggers.cron"] = MagicMock()
    sys.modules["apscheduler.triggers.interval"] = MagicMock()
    sys.modules["apscheduler.triggers.date"] = MagicMock()
    sys.modules["apscheduler.events"] = MagicMock()
