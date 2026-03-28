"""测试 CLI schedule 子命令"""

import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

import pytest
from click.testing import CliRunner

from llm_chat.cli import cli


DB_PATH = "tests/test_cli_schedule.db"


def setup_module(module):
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


def teardown_module(module):
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


class TestScheduleCommands:
    """schedule 子命令测试"""

    def test_schedule_list_empty(self):
        """测试：空任务列表"""
        runner = CliRunner()

        with patch("llm_chat.cli.Config") as mock_config_class:
            with patch("llm_chat.cli.App") as mock_app_class:
                mock_config = MagicMock()
                mock_config.scheduler.enabled = True
                mock_config_class.from_yaml.return_value = mock_config

                mock_scheduler = MagicMock()
                mock_scheduler.get_all_tasks.return_value = []
                mock_app = MagicMock()
                mock_app.get_scheduler.return_value = mock_scheduler
                mock_app_class.return_value = mock_app

                result = runner.invoke(cli, ["schedule", "list"])

                assert result.exit_code == 0
                assert "暂无调度任务" in result.output

    def test_schedule_list_with_tasks(self):
        """测试：列出任务"""
        runner = CliRunner()

        mock_task = MagicMock()
        mock_task.id = "task-123"
        mock_task.name = "测试任务"
        mock_task.task_type.value = "LLM_CHAT"
        mock_task.enabled = True
        mock_task.trigger_config = {"cron": "0 9 * * *"}
        mock_task.created_at = datetime(2026, 3, 29, 10, 0, 0)

        with patch("llm_chat.cli.Config") as mock_config_class:
            with patch("llm_chat.cli.App") as mock_app_class:
                mock_config = MagicMock()
                mock_config.scheduler.enabled = True
                mock_config_class.from_yaml.return_value = mock_config

                mock_scheduler = MagicMock()
                mock_scheduler.get_all_tasks.return_value = [mock_task]
                mock_app = MagicMock()
                mock_app.get_scheduler.return_value = mock_scheduler
                mock_app_class.return_value = mock_app

                result = runner.invoke(cli, ["schedule", "list"])

                assert result.exit_code == 0
                assert "task-123" in result.output
                assert "测试任务" in result.output
                assert "LLM_CHAT" in result.output

    def test_schedule_create_with_cron(self):
        """测试：创建 cron 任务"""
        runner = CliRunner()

        mock_scheduler = MagicMock()
        mock_scheduler.add_task.return_value = "task-new-123"

        with patch("llm_chat.cli.Config") as mock_config_class:
            with patch("llm_chat.cli.App") as mock_app_class:
                mock_config = MagicMock()
                mock_config.scheduler.enabled = True
                mock_config_class.from_yaml.return_value = mock_config

                mock_app = MagicMock()
                mock_app.get_scheduler.return_value = mock_scheduler
                mock_app_class.return_value = mock_app

                result = runner.invoke(
                    cli,
                    [
                        "schedule",
                        "create",
                        "--name",
                        "每日问候",
                        "--cron",
                        "0 9 * * *",
                        "--message",
                        "早上好！",
                    ],
                )

                assert result.exit_code == 0
                assert "任务已创建" in result.output
                assert "每日问候" in result.output

                mock_scheduler.add_task.assert_called_once()
                task = mock_scheduler.add_task.call_args[0][0]
                assert task.name == "每日问候"
                assert task.trigger_config == {"cron": "0 9 * * *"}
                assert task.params["message"] == "早上好！"

    def test_schedule_create_with_interval(self):
        """测试：创建 interval 任务"""
        runner = CliRunner()

        mock_scheduler = MagicMock()
        mock_scheduler.add_task.return_value = "task-interval-123"

        with patch("llm_chat.cli.Config") as mock_config_class:
            with patch("llm_chat.cli.App") as mock_app_class:
                mock_config = MagicMock()
                mock_config.scheduler.enabled = True
                mock_config_class.from_yaml.return_value = mock_config

                mock_app = MagicMock()
                mock_app.get_scheduler.return_value = mock_scheduler
                mock_app_class.return_value = mock_app

                result = runner.invoke(
                    cli,
                    [
                        "schedule",
                        "create",
                        "--name",
                        "每小时检查",
                        "--interval",
                        "3600",
                        "--message",
                        "检查状态",
                    ],
                )

                assert result.exit_code == 0
                assert "任务已创建" in result.output

                task = mock_scheduler.add_task.call_args[0][0]
                assert task.trigger_config == {"interval": 3600}

    def test_schedule_create_missing_trigger(self):
        """测试：创建任务时缺少触发器配置"""
        runner = CliRunner()

        with patch("llm_chat.cli.Config") as mock_config_class:
            with patch("llm_chat.cli.App") as mock_app_class:
                mock_config = MagicMock()
                mock_config.scheduler.enabled = True
                mock_config_class.from_yaml.return_value = mock_config

                mock_app = MagicMock()
                mock_app.get_scheduler.return_value = MagicMock()
                mock_app_class.return_value = mock_app

                result = runner.invoke(
                    cli,
                    ["schedule", "create", "--name", "测试", "--message", "hello"],
                )

                assert result.exit_code != 0
                assert "必须指定" in result.output

    def test_schedule_delete(self):
        """测试：删除任务"""
        runner = CliRunner()

        mock_scheduler = MagicMock()
        mock_scheduler.remove_task.return_value = True

        with patch("llm_chat.cli.Config") as mock_config_class:
            with patch("llm_chat.cli.App") as mock_app_class:
                mock_config = MagicMock()
                mock_config.scheduler.enabled = True
                mock_config_class.from_yaml.return_value = mock_config

                mock_app = MagicMock()
                mock_app.get_scheduler.return_value = mock_scheduler
                mock_app_class.return_value = mock_app

                result = runner.invoke(cli, ["schedule", "delete", "task-123", "--yes"])

                assert result.exit_code == 0
                assert "任务已删除" in result.output
                mock_scheduler.remove_task.assert_called_once_with("task-123")

    def test_schedule_pause(self):
        """测试：暂停任务"""
        runner = CliRunner()

        mock_scheduler = MagicMock()
        mock_scheduler.pause_task.return_value = True

        with patch("llm_chat.cli.Config") as mock_config_class:
            with patch("llm_chat.cli.App") as mock_app_class:
                mock_config = MagicMock()
                mock_config.scheduler.enabled = True
                mock_config_class.from_yaml.return_value = mock_config

                mock_app = MagicMock()
                mock_app.get_scheduler.return_value = mock_scheduler
                mock_app_class.return_value = mock_app

                result = runner.invoke(cli, ["schedule", "pause", "task-123"])

                assert result.exit_code == 0
                assert "任务已暂停" in result.output
                mock_scheduler.pause_task.assert_called_once_with("task-123")

    def test_schedule_resume(self):
        """测试：恢复任务"""
        runner = CliRunner()

        mock_scheduler = MagicMock()
        mock_scheduler.resume_task.return_value = True

        with patch("llm_chat.cli.Config") as mock_config_class:
            with patch("llm_chat.cli.App") as mock_app_class:
                mock_config = MagicMock()
                mock_config.scheduler.enabled = True
                mock_config_class.from_yaml.return_value = mock_config

                mock_app = MagicMock()
                mock_app.get_scheduler.return_value = mock_scheduler
                mock_app_class.return_value = mock_app

                result = runner.invoke(cli, ["schedule", "resume", "task-123"])

                assert result.exit_code == 0
                assert "任务已恢复" in result.output
                mock_scheduler.resume_task.assert_called_once_with("task-123")

    def test_schedule_trigger(self):
        """测试：手动触发任务"""
        runner = CliRunner()

        mock_scheduler = MagicMock()
        mock_scheduler.trigger_task.return_value = True

        with patch("llm_chat.cli.Config") as mock_config_class:
            with patch("llm_chat.cli.App") as mock_app_class:
                mock_config = MagicMock()
                mock_config.scheduler.enabled = True
                mock_config_class.from_yaml.return_value = mock_config

                mock_app = MagicMock()
                mock_app.get_scheduler.return_value = mock_scheduler
                mock_app_class.return_value = mock_app

                result = runner.invoke(cli, ["schedule", "trigger", "task-123"])

                assert result.exit_code == 0
                assert "任务已触发" in result.output
                mock_scheduler.trigger_task.assert_called_once_with("task-123")

    def test_schedule_info(self):
        """测试：查看任务详情"""
        runner = CliRunner()

        mock_task = MagicMock()
        mock_task.id = "task-123"
        mock_task.name = "测试任务"
        mock_task.task_type.value = "LLM_CHAT"
        mock_task.enabled = True
        mock_task.max_retries = 3
        mock_task.trigger_config = {"cron": "0 9 * * *"}
        mock_task.params = {"message": "hello"}
        mock_task.created_at = datetime(2026, 3, 29, 10, 0, 0)
        mock_task.updated_at = datetime(2026, 3, 29, 10, 0, 0)

        mock_scheduler = MagicMock()
        mock_scheduler.get_task.return_value = mock_task

        with patch("llm_chat.cli.Config") as mock_config_class:
            with patch("llm_chat.cli.App") as mock_app_class:
                mock_config = MagicMock()
                mock_config.scheduler.enabled = True
                mock_config_class.from_yaml.return_value = mock_config

                mock_app = MagicMock()
                mock_app.get_scheduler.return_value = mock_scheduler
                mock_app_class.return_value = mock_app

                result = runner.invoke(cli, ["schedule", "info", "task-123"])

                assert result.exit_code == 0
                assert "测试任务" in result.output
                assert "task-123" in result.output
                assert "LLM_CHAT" in result.output
                mock_scheduler.get_task.assert_called_once_with("task-123")

    def test_schedule_disabled_error(self):
        """测试：调度器禁用时返回错误"""
        runner = CliRunner()

        with patch("llm_chat.cli.Config") as mock_config_class:
            mock_config = MagicMock()
            mock_config.scheduler.enabled = False
            mock_config_class.from_yaml.return_value = mock_config

            result = runner.invoke(cli, ["schedule", "list"])

            assert result.exit_code != 0
            assert "调度器未启用" in result.output
