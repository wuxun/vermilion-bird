"""conftest for integration tests - use real APScheduler (not mocked)

This conftest removes the APScheduler mocks from the parent conftest.py
to allow integration tests to use the real scheduler.
"""

import sys


def pytest_configure(config):
    """Remove APScheduler mocks for integration tests"""
    mock_modules = [
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

    for mod in mock_modules:
        if mod in sys.modules:
            del sys.modules[mod]
