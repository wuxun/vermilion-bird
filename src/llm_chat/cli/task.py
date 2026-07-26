"""产品级任务 CLI。"""

from __future__ import annotations

import json
from typing import Any

import click

from llm_chat.app import App
from llm_chat.config import Config
from llm_chat.work import WorkItemKind, WorkItemStatus


def _build_app() -> App:
    return App(Config.from_yaml())


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _status_label(status: WorkItemStatus) -> str:
    icons = {
        WorkItemStatus.DRAFT: "○",
        WorkItemStatus.READY: "○",
        WorkItemStatus.RUNNING: "▶",
        WorkItemStatus.WAITING_APPROVAL: "!",
        WorkItemStatus.PAUSED: "Ⅱ",
        WorkItemStatus.COMPLETED: "✓",
        WorkItemStatus.FAILED: "✗",
        WorkItemStatus.CANCELLED: "—",
    }
    return f"{icons[status]} {status.value}"


@click.group()
def task():
    """创建、执行和查看用户任务。"""


@task.command("start")
@click.argument("objective")
@click.option("--title", help="任务标题；默认从目标截取")
@click.option(
    "--kind",
    type=click.Choice([item.value for item in WorkItemKind]),
    default=WorkItemKind.TASK.value,
    show_default=True,
)
@click.option("--conversation-id", help="复用指定对话")
@click.option("--workspace", type=click.Path(file_okay=False), help="任务工作目录")
@click.option("--idempotency-key", help="外部触发幂等键")
@click.option("--json-output", is_flag=True, help="输出 JSON")
def start_task(
    objective,
    title,
    kind,
    conversation_id,
    workspace,
    idempotency_key,
    json_output,
):
    """立即执行一个持久化任务。"""

    app = _build_app()
    try:
        item = app.create_work_item(
            objective,
            title=title,
            kind=WorkItemKind(kind),
            conversation_id=conversation_id,
            workspace=workspace,
            idempotency_key=idempotency_key,
            metadata={"source": "cli"},
        )
        detail = app.execute_work_item(item.id)
        if json_output:
            click.echo(_json(detail))
            return
        click.echo(f"任务: {detail.work_item.title}")
        click.echo(f"ID: {detail.work_item.id}")
        click.echo(f"状态: {_status_label(detail.work_item.status)}")
        if detail.artifacts:
            click.echo("\n结果:")
            primary = detail.artifacts[0]
            result = primary.content or primary.content_preview or primary.uri or "已生成产物"
            click.echo(result)
        elif detail.work_item.status == WorkItemStatus.WAITING_APPROVAL:
            click.echo("任务正在等待审批，请在执行与审批中心处理。")
        else:
            latest = detail.runs[0] if detail.runs else None
            if latest and latest.error:
                click.echo(f"错误: {latest.error}", err=True)
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@task.command("list")
@click.option(
    "--status",
    type=click.Choice([item.value for item in WorkItemStatus]),
    help="按状态筛选",
)
@click.option(
    "--kind",
    type=click.Choice([item.value for item in WorkItemKind]),
    help="按类型筛选",
)
@click.option("--limit", type=click.IntRange(1, 500), default=50, show_default=True)
@click.option("--json-output", is_flag=True, help="输出 JSON")
def list_tasks(status, kind, limit, json_output):
    """列出最近的用户任务。"""

    app = _build_app()
    try:
        items = app.list_work_items(
            status=WorkItemStatus(status) if status else None,
            kind=WorkItemKind(kind) if kind else None,
            limit=limit,
        )
        if json_output:
            click.echo(_json([item.model_dump(mode="json") for item in items]))
            return
        if not items:
            click.echo("暂无用户任务。")
            return
        for item in items:
            updated = item.updated_at.astimezone().strftime("%Y-%m-%d %H:%M")
            click.echo(f"{_status_label(item.status):14} {item.id}  {item.title}  {updated}")
    finally:
        app.stop()


@task.command("show")
@click.argument("work_item_id")
@click.option("--json-output", is_flag=True, help="输出 JSON")
def show_task(work_item_id, json_output):
    """查看任务、执行尝试和产物。"""

    app = _build_app()
    try:
        detail = app.get_work_item_detail(work_item_id)
        if json_output:
            click.echo(_json(detail))
            return
        item = detail.work_item
        click.echo(f"任务: {item.title}")
        click.echo(f"ID: {item.id}")
        click.echo(f"类型: {item.kind.value}")
        click.echo(f"状态: {_status_label(item.status)}")
        click.echo(f"目标: {item.objective}")
        if item.workspace:
            click.echo(f"工作目录: {item.workspace}")
        click.echo(f"执行次数: {len(detail.runs)}")
        click.echo(f"产物数量: {len(detail.artifacts)}")
        if detail.runs:
            click.echo("\n执行:")
            for run in detail.runs:
                click.echo(
                    f"  {run.id}  {run.type.value}/{run.status.value}  attempt={run.attempt}"
                )
        if detail.artifacts:
            click.echo("\n产物:")
            for artifact in detail.artifacts:
                location = artifact.uri or "内嵌内容"
                click.echo(f"  {artifact.id}  {artifact.kind.value}  {artifact.name}  {location}")
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@task.command("artifacts")
@click.argument("work_item_id")
@click.option("--json-output", is_flag=True, help="输出 JSON")
def list_artifacts(work_item_id, json_output):
    """列出任务交付物。"""

    app = _build_app()
    try:
        artifacts = app.get_work_item_detail(work_item_id).artifacts
        if json_output:
            click.echo(_json([item.model_dump(mode="json") for item in artifacts]))
            return
        if not artifacts:
            click.echo("该任务暂无产物。")
            return
        for artifact in artifacts:
            click.echo(f"{artifact.id}  {artifact.kind.value}  {artifact.name}")
            if artifact.uri:
                click.echo(f"  {artifact.uri}")
            elif artifact.content_preview:
                click.echo(f"  {artifact.content_preview}")
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@task.command("cancel")
@click.argument("work_item_id")
def cancel_task(work_item_id):
    """取消任务的当前主执行。"""

    app = _build_app()
    try:
        detail = app.cancel_work_item(work_item_id)
        click.echo(f"任务已取消: {detail.work_item.id}")
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@task.command("retry")
@click.argument("work_item_id")
def retry_task(work_item_id):
    """从持久化状态重试失败任务。"""

    app = _build_app()
    try:
        detail = app.retry_work_item(work_item_id)
        click.echo(f"任务状态: {_status_label(detail.work_item.status)}")
        if detail.artifacts:
            click.echo(detail.artifacts[0].content or detail.artifacts[0].content_preview or "")
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@task.command("resume")
@click.argument("work_item_id")
def resume_task(work_item_id):
    """从持久化检查点恢复已暂停任务。"""

    app = _build_app()
    try:
        detail = app.resume_work_item(work_item_id)
        click.echo(f"任务状态: {_status_label(detail.work_item.status)}")
        if detail.artifacts:
            click.echo(detail.artifacts[0].content or detail.artifacts[0].content_preview or "")
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()
