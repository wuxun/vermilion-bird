"""产品级任务 CLI。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import click
import yaml

from llm_chat.app import App
from llm_chat.config import Config
from llm_chat.runtime import Capability
from llm_chat.work import (
    GrantScope,
    PlanStepStatus,
    ResourceType,
    WorkItemKind,
    WorkItemStatus,
)


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
        WorkItemStatus.CANCELLING: "…",
        WorkItemStatus.PAUSING: "…",
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
    """请求协作式取消当前任务。"""

    app = _build_app()
    try:
        detail = app.cancel_work_item(work_item_id)
        click.echo(f"取消请求已提交: {detail.work_item.id}")
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


@task.command("pause")
@click.argument("work_item_id")
def pause_task(work_item_id):
    """请求任务在下一个安全 checkpoint 暂停。"""

    app = _build_app()
    try:
        detail = app.pause_work_item(work_item_id)
        click.echo(f"任务状态: {_status_label(detail.work_item.status)}")
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@task.group("plan")
def plan_group():
    """管理版本化任务计划。"""


@plan_group.command("create")
@click.argument("work_item_id")
@click.option("--summary", required=True, help="计划摘要")
@click.option(
    "--step",
    "step_titles",
    multiple=True,
    help="按顺序添加步骤标题，可重复",
)
@click.option(
    "--steps-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="包含 steps 数组的 JSON/YAML 文件",
)
@click.option("--change-summary", default="", help="相对上一版的变更摘要")
@click.option("--approve", is_flag=True, help="创建后立即批准")
@click.option("--json-output", is_flag=True, help="输出 JSON")
def create_plan(
    work_item_id,
    summary,
    step_titles,
    steps_file,
    change_summary,
    approve,
    json_output,
):
    """创建新的不可覆盖计划版本。"""

    if steps_file:
        payload = yaml.safe_load(steps_file.read_text(encoding="utf-8"))
        steps = payload.get("steps", []) if isinstance(payload, dict) else payload
    else:
        steps = [{"title": title} for title in step_titles]
    if not isinstance(steps, list) or not steps:
        raise click.ClickException("至少通过 --step 或 --steps-file 提供一个步骤")

    app = _build_app()
    try:
        plan = app.create_work_item_plan(
            work_item_id,
            summary=summary,
            steps=steps,
            change_summary=change_summary,
            approve=approve,
        )
        if json_output:
            click.echo(_json(plan))
            return
        click.echo(f"计划 v{plan.version}: {plan.id} " f"[{plan.status.value}]，{len(plan.steps)} 个步骤")
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@plan_group.command("show")
@click.argument("work_item_id")
@click.option("--json-output", is_flag=True, help="输出 JSON")
def show_plan(work_item_id, json_output):
    """查看任务的最新计划。"""

    app = _build_app()
    try:
        plan = app.get_work_item_detail(work_item_id).plan
        if plan is None:
            click.echo("该任务暂无计划。")
            return
        if json_output:
            click.echo(_json(plan))
            return
        click.echo(f"计划 v{plan.version}: {plan.summary} [{plan.status.value}]")
        if plan.change_summary:
            click.echo(f"变更: {plan.change_summary}")
        for step in plan.steps:
            dependencies = f" depends={len(step.depends_on)}" if step.depends_on else ""
            click.echo(
                f"  {step.position}. {step.title} "
                f"[{step.status.value}]{dependencies}  {step.id}"
            )
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@plan_group.command("history")
@click.argument("work_item_id")
@click.option("--json-output", is_flag=True, help="输出 JSON")
def plan_history(work_item_id, json_output):
    """查看任务计划修订历史。"""

    app = _build_app()
    try:
        plans = app.list_work_item_plans(work_item_id)
        if json_output:
            click.echo(_json([plan.model_dump(mode="json") for plan in plans]))
            return
        for plan in plans:
            click.echo(f"v{plan.version}  {plan.id}  {plan.status.value}  " f"{plan.summary}")
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@plan_group.command("approve")
@click.argument("work_item_id")
@click.argument("plan_id")
def approve_plan(work_item_id, plan_id):
    """批准最新计划版本。"""

    app = _build_app()
    try:
        plan = app.approve_work_item_plan(work_item_id, plan_id)
        click.echo(f"计划 v{plan.version} 已批准: {plan.id}")
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@plan_group.command("step")
@click.argument("work_item_id")
@click.argument("step_id")
@click.argument(
    "status",
    type=click.Choice([status.value for status in PlanStepStatus]),
)
def update_plan_step(work_item_id, step_id, status):
    """更新已批准计划的步骤状态。"""

    app = _build_app()
    try:
        plan = app.update_work_item_plan_step(
            work_item_id,
            step_id,
            PlanStepStatus(status),
        )
        step = next(item for item in plan.steps if item.id == step_id)
        click.echo(f"步骤 {step.position} 已更新为 {step.status.value}")
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@task.group("grant")
def grant_group():
    """管理任务的资源级授权。"""


@grant_group.command("add")
@click.argument("work_item_id")
@click.option(
    "--capability",
    type=click.Choice([capability.value for capability in Capability]),
    required=True,
)
@click.option(
    "--resource-type",
    type=click.Choice([resource_type.value for resource_type in ResourceType]),
    required=True,
)
@click.option("--resource", required=True, help="目录、域名或消息目标")
@click.option(
    "--scope",
    type=click.Choice([scope.value for scope in GrantScope]),
    default=GrantScope.WORK_ITEM.value,
    show_default=True,
)
@click.option(
    "--expires-hours",
    type=click.FloatRange(min=0.01),
    help="授权有效小时数；省略表示无固定到期时间",
)
@click.option("--reason", default="", help="授权原因")
def add_grant(
    work_item_id,
    capability,
    resource_type,
    resource,
    scope,
    expires_hours,
    reason,
):
    """给任务授予一个明确资源边界。"""

    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=expires_hours) if expires_hours else None
    )
    app = _build_app()
    try:
        grant = app.create_resource_grant(
            work_item_id=work_item_id,
            capability=capability,
            resource_type=ResourceType(resource_type),
            resource=resource,
            scope=GrantScope(scope),
            expires_at=expires_at,
            reason=reason,
        )
        click.echo(
            f"授权已创建: {grant.id}  {grant.capability} "
            f"{grant.resource_type.value}:{grant.resource}"
        )
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@grant_group.command("list")
@click.argument("work_item_id")
@click.option("--all", "include_inactive", is_flag=True, help="包含已撤销和过期授权")
@click.option("--json-output", is_flag=True, help="输出 JSON")
def list_grants(work_item_id, include_inactive, json_output):
    """列出任务资源授权。"""

    app = _build_app()
    try:
        grants = app.list_resource_grants(
            work_item_id=work_item_id,
            include_inactive=include_inactive,
        )
        if json_output:
            click.echo(_json([grant.model_dump(mode="json") for grant in grants]))
            return
        if not grants:
            click.echo("该任务暂无资源授权。")
            return
        for grant in grants:
            click.echo(
                f"{grant.id}  {grant.status.value}  {grant.capability}  "
                f"{grant.resource_type.value}:{grant.resource}  {grant.scope.value}"
            )
    finally:
        app.stop()


@grant_group.command("revoke")
@click.argument("grant_id")
def revoke_grant(grant_id):
    """立即撤销资源授权。"""

    app = _build_app()
    try:
        grant = app.revoke_resource_grant(grant_id)
        click.echo(f"授权已撤销: {grant.id}")
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()
