"""数据库版本、完整性和备份运维命令。"""

from __future__ import annotations

import json
import os

import click

from llm_chat.storage import Storage


def _storage() -> Storage:
    return Storage(os.environ.get("VB_DB_PATH", Storage.DEFAULT_DB_PATH))


@click.group()
def database():
    """检查数据库版本、完整性并创建安全备份。"""


@database.command("status")
@click.option("--json-output", is_flag=True, help="输出 JSON")
def database_status(json_output):
    """显示 schema 版本和迁移历史。"""

    storage = _storage()
    info = storage.get_schema_info()
    integrity = storage.verify_integrity()
    payload = {**info, "integrity": integrity}
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return
    click.echo(
        f"Schema: {info['current_version']} / {info['supported_version']}"
    )
    click.echo(f"完整性: {'正常' if integrity['ok'] else '异常'}")
    for migration in info["migrations"]:
        click.echo(
            f"  v{migration['version']}  {migration['name']}  "
            f"{migration['applied_at']}"
        )
    report = info["last_report"]
    if report["applied"]:
        click.echo(f"本次升级: {report['from_version']} → {report['to_version']}")
    if report["backup_path"]:
        click.echo(f"升级前备份: {report['backup_path']}")


@database.command("backup")
@click.option("--label", default="manual", show_default=True, help="备份标签")
def database_backup(label):
    """立即创建 WAL 一致的 SQLite 备份。"""

    storage = _storage()
    path = storage.create_backup(label=label)
    click.echo(path)
