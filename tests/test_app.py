"""测试 App 类的调度器集成功能"""

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
    """调度器集成测试"""

    def test_app_scheduler_not_initialized_when_disabled(self):
        """测试：当 scheduler.enabled=False 时，不初始化调度器"""
        config = Config()
        config.scheduler = SchedulerConfig(enabled=False)

        with patch.object(Storage, "__init__", return_value=None):
            with patch.object(Storage, "_init_db"):
                app = App(config=config)

        assert app.scheduler is None

    def test_app_scheduler_initialized_when_enabled(self):
        config = Config()
        config.scheduler = SchedulerConfig(enabled=True, max_workers=2)

        with patch.object(Storage, "__init__", return_value=None):
            with patch.object(Storage, "_init_db"):
                with patch(
                    "llm_chat.scheduler.scheduler.SchedulerService"
                ) as mock_scheduler_class:
                    mock_scheduler = MagicMock()
                    mock_scheduler_class.return_value = mock_scheduler

                    app = App(config=config)

                    mock_scheduler_class.assert_called_once()
                    call_args = mock_scheduler_class.call_args
                    assert call_args[0][0] == config.scheduler
                    assert call_args[0][1] == app.storage
                    assert call_args[0][2] == app

                    assert app.scheduler == mock_scheduler

    def test_app_get_scheduler_returns_instance(self):
        config = Config()
        config.scheduler = SchedulerConfig(enabled=True)

        with patch.object(Storage, "__init__", return_value=None):
            with patch.object(Storage, "_init_db"):
                with patch(
                    "llm_chat.scheduler.scheduler.SchedulerService"
                ) as mock_scheduler_class:
                    mock_scheduler = MagicMock()
                    mock_scheduler_class.return_value = mock_scheduler

                    app = App(config=config)

                    assert app.get_scheduler() == mock_scheduler

    def test_app_get_scheduler_returns_none_when_disabled(self):
        """测试：当调度器禁用时，get_scheduler() 返回 None"""
        config = Config()
        config.scheduler = SchedulerConfig(enabled=False)

        with patch.object(Storage, "__init__", return_value=None):
            with patch.object(Storage, "_init_db"):
                app = App(config=config)

                assert app.get_scheduler() is None

    def test_app_run_starts_scheduler_when_enabled(self):
        config = Config()
        config.scheduler = SchedulerConfig(enabled=True)
        config.enable_tools = False

        with patch.object(Storage, "__init__", return_value=None):
            with patch.object(Storage, "_init_db"):
                with patch(
                    "llm_chat.scheduler.scheduler.SchedulerService"
                ) as mock_scheduler_class:
                    mock_scheduler = MagicMock()
                    mock_scheduler_class.return_value = mock_scheduler

                    app = App(config=config)

                    mock_frontend = MagicMock()
                    mock_frontend.start = MagicMock()

                    app.run(mock_frontend)

                    mock_scheduler.start.assert_called_once()

    def test_app_run_does_not_start_scheduler_when_disabled(self):
        config = Config()
        config.scheduler = SchedulerConfig(enabled=False)
        config.enable_tools = False

        with patch.object(Storage, "__init__", return_value=None):
            with patch.object(Storage, "_init_db"):
                app = App(config=config)

                mock_frontend = MagicMock()
                mock_frontend.start = MagicMock()

                app.run(mock_frontend)

                assert app.scheduler is None

    def test_app_stop_shuts_down_scheduler(self):
        config = Config()
        config.scheduler = SchedulerConfig(enabled=True)

        with patch.object(Storage, "__init__", return_value=None):
            with patch.object(Storage, "_init_db"):
                with patch(
                    "llm_chat.scheduler.scheduler.SchedulerService"
                ) as mock_scheduler_class:
                    mock_scheduler = MagicMock()
                    mock_scheduler_class.return_value = mock_scheduler

                    app = App(config=config)
                    app.current_frontend = MagicMock()

                    app.stop()

                    mock_scheduler.shutdown.assert_called_once()

    def test_app_stop_does_not_fail_when_scheduler_disabled(self):
        config = Config()
        config.scheduler = SchedulerConfig(enabled=False)

        with patch.object(Storage, "__init__", return_value=None):
            with patch.object(Storage, "_init_db"):
                app = App(config=config)
                app.current_frontend = MagicMock()

                app.stop()

                assert app.scheduler is None


def test_scheduler_integration():
    config = Config()
    config.scheduler = SchedulerConfig(enabled=True, max_workers=2)
    config.enable_tools = False

    with patch.object(Storage, "__init__", return_value=None):
        with patch.object(Storage, "_init_db"):
            with patch(
                "llm_chat.scheduler.scheduler.SchedulerService"
            ) as mock_scheduler_class:
                mock_scheduler = MagicMock()
                mock_scheduler_class.return_value = mock_scheduler

                app = App(config=config)

                assert app.scheduler is not None
                assert app.get_scheduler() == mock_scheduler

                mock_frontend = MagicMock()
                mock_frontend.start = MagicMock()

                with patch.object(app.storage, "migrate_from_json"):
                    with patch.object(app, "conversation_manager") as mock_conv_mgr:
                        mock_conv_mgr.list_conversations.return_value = []
                        app.run(mock_frontend)

                mock_scheduler.start.assert_called_once()

                app.stop()

                mock_scheduler.shutdown.assert_called_once()
