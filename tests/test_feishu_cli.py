import os
from pathlib import Path
import textwrap

import pytest
from click.testing import CliRunner

from llm_chat.cli import cli
from llm_chat.frontends.feishu.server import get_running_feishu_server


def write_config(tmp_path: Path, content: str) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent(content), encoding="utf-8")
    return cfg


def test_feishu_command_missing_config(tmp_path: Path):
    runner = CliRunner()
    # No config file provided (uses default path), create a minimal config that disables Feishu
    config_path = write_config(
        tmp_path,
        """
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-3.5-turbo"
  protocol: "openai"
feishu:
  enabled: false
""",
    )
    result = runner.invoke(cli, ["feishu", "--config", str(config_path)])
    assert result.exit_code == 0
    assert "Feishu 集成未开启" in result.output


def test_feishu_command_missing_credentials(tmp_path: Path):
    runner = CliRunner()
    config_path = write_config(
        tmp_path,
        """
feishu:
  enabled: true
  app_id: 
  app_secret: 
""",
    )
    result = runner.invoke(cli, ["feishu", "--config", str(config_path)])
    assert result.exit_code == 0
    assert "需要 app_id 与 app_secret" in result.output or "app_id" in result.output


def test_feishu_command_starts_server(tmp_path: Path):
    runner = CliRunner()
    config_path = write_config(
        tmp_path,
        """
feishu:
  enabled: true
  app_id: test-app-id
  app_secret: test-app-secret
  tenant_key: test-tenant
""",
    )
    result = runner.invoke(cli, ["feishu", "--config", str(config_path)])
    # The command should succeed and start the server in background
    assert result.exit_code == 0
    assert "后台启动" in result.output or "Feishu 服务器" in result.output

    # Stop the background server if it was started
    srv = get_running_feishu_server()
    if srv:
        srv.stop()
