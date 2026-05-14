"""Test App scheduler integration.

Note: Scheduler initialization was moved from App.__init__ to
_start_background_services (called during run()).
"""

import os
from unittest.mock import Mock, patch, MagicMock

import pytest

from llm_chat.app import App
from llm_chat.config import Config, SchedulerConfig
from llm_chat.storage import Storage


DB_PATH = "tests/test_app_scheduler.db"


def setup_module(module):
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


def teardown_module(module):
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


class TestSchedulerIntegration:
    """Scheduler integration with App lifecycle."""

    def test_scheduler_is_none_when_disabled(self):
        """scheduler remains None when config.scheduler.enabled=False."""
        config = Config()
        config.scheduler = SchedulerConfig(enabled=False)

        with patch.object(Storage, "__init__", return_value=None):
            app = App(config=config)
        assert app.scheduler is None

    def test_get_scheduler_none_when_disabled(self):
        """get_scheduler() returns None when disabled."""
        config = Config()
        config.scheduler = SchedulerConfig(enabled=False)

        with patch.object(Storage, "__init__", return_value=None):
            app = App(config=config)
        assert app.get_scheduler() is None

    def test_scheduler_initialized_during_run(self):
        """Scheduler is created and started during app.run()."""
        config = Config()
        config.scheduler = SchedulerConfig(enabled=True, max_workers=2)
        config.enable_tools = False

        with patch.object(Storage, "__init__", return_value=None):
            with patch("llm_chat.scheduler.SchedulerService") as m_cls:
                # Also clear lazy cache
                import llm_chat.scheduler as sched_mod
                sched_mod._SchedulerService = None

                mock_sched = MagicMock()
                m_cls.return_value = mock_sched

                app = App(config=config)
                assert app.scheduler is None

                mock_frontend = MagicMock()
                mock_frontend.start = lambda **kw: kw.get("post_init", lambda: None)()
                app.run(mock_frontend)

                m_cls.assert_called_once()
                assert app.scheduler == mock_sched
                mock_sched.start.assert_called_once()

    def test_scheduler_shutdown_during_stop(self):
        """Scheduler.shutdown is called via ServiceManager during app.stop()."""
        config = Config()
        config.scheduler = SchedulerConfig(enabled=True)

        with patch.object(Storage, "__init__", return_value=None):
            app = App(config=config)
            mock_sched = MagicMock()
            mock_sched.name = "SchedulerService"
            app.scheduler = mock_sched
            # Register and mark as started so stop_all() finds it
            app.service_manager._services[mock_sched.name] = mock_sched
            app.service_manager._started_services.append(mock_sched.name)
            app.current_frontend = MagicMock()

            app.stop()
            mock_sched.shutdown.assert_called_once()

    def test_stop_no_fail_when_scheduler_disabled(self):
        """stop() doesn't crash when scheduler is None."""
        config = Config()
        config.scheduler = SchedulerConfig(enabled=False)

        with patch.object(Storage, "__init__", return_value=None):
            app = App(config=config)
            app.current_frontend = MagicMock()
            app.stop()  # should not raise
            assert app.scheduler is None


def test_scheduler_integration():
    """End-to-end: init → run → stop."""
    config = Config()
    config.scheduler = SchedulerConfig(enabled=True, max_workers=2)
    config.enable_tools = False

    with patch.object(Storage, "__init__", return_value=None):
        with patch("llm_chat.scheduler.SchedulerService") as m_cls:
            import llm_chat.scheduler as sched_mod
            sched_mod._SchedulerService = None

            mock_sched = MagicMock()
            m_cls.return_value = mock_sched

            app = App(config=config)
            assert app.scheduler is None  # deferred

            mock_frontend = MagicMock()
            mock_frontend.start = lambda **kw: kw.get("post_init", lambda: None)()
            app.run(mock_frontend)

            m_cls.assert_called_once()
            mock_sched.start.assert_called_once()

            app.stop()
            mock_sched.shutdown.assert_called_once()
