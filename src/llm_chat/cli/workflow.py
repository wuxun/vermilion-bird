"""可复用 WorkflowDefinition CLI。"""

import json

import click

from llm_chat.app import App
from llm_chat.config import Config
from llm_chat.workflows import WorkflowParameter


def _app():
    return App(Config.from_yaml())


@click.group("workflow")
def workflow_group():
    """从成功任务创建并运行不可变工作流版本。"""


@workflow_group.command("create-from-task")
@click.argument("work_item_id")
@click.option("--name", help="工作流名称")
@click.option("--description", default="", help="说明")
@click.option("--template", "objective_template", help="含 {name} 参数的目标模板")
@click.option(
    "--parameter",
    "parameter_names",
    multiple=True,
    help="声明必填参数名，可重复",
)
def create_from_task(
    work_item_id,
    name,
    description,
    objective_template,
    parameter_names,
):
    """从已完成且有 Artifact 的任务创建 v1。"""

    app = _app()
    try:
        definition, version = app.create_workflow_from_work_item(
            work_item_id,
            name=name,
            description=description,
            objective_template=objective_template,
            parameters=[WorkflowParameter(name=parameter) for parameter in parameter_names],
        )
        click.echo(f"工作流已创建: {definition.id}@{version.version}  " f"{definition.name}")
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@workflow_group.command("list")
@click.option("--json-output", is_flag=True, help="输出 JSON")
def list_workflows(json_output):
    """列出工作流定义。"""

    app = _app()
    try:
        workflows = app.list_workflows()
        if json_output:
            click.echo(
                json.dumps(
                    [item.model_dump(mode="json") for item in workflows],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        for item in workflows:
            click.echo(f"{item.id}@{item.latest_version}  " f"{item.status.value}  {item.name}")
    finally:
        app.stop()


@workflow_group.command("show")
@click.argument("workflow_id")
@click.option("--version", type=click.IntRange(min=1))
@click.option("--json-output", is_flag=True, help="输出 JSON")
def show_workflow(workflow_id, version, json_output):
    """查看定义及指定版本。"""

    app = _app()
    try:
        definition, workflow_version = app.get_workflow(
            workflow_id,
            version=version,
        )
        payload = {
            "definition": definition.model_dump(mode="json"),
            "version": workflow_version.model_dump(mode="json"),
        }
        if json_output:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        click.echo(f"{definition.name}  {definition.id}@{workflow_version.version}")
        click.echo(f"目标模板: {workflow_version.objective_template}")
        click.echo(f"计划步骤: {len(workflow_version.plan_steps)}")
        click.echo(
            "预期产物: " + ", ".join(kind.value for kind in workflow_version.expected_artifact_kinds)
        )
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@workflow_group.command("revise")
@click.argument("workflow_id")
@click.option("--change-summary", required=True, help="本版变更说明")
@click.option("--template", "objective_template", help="新的目标模板")
@click.option(
    "--parameter",
    "parameter_names",
    multiple=True,
    help="新版本必填参数；指定后替换原参数列表",
)
def revise_workflow(
    workflow_id,
    change_summary,
    objective_template,
    parameter_names,
):
    """基于最新版创建新的不可变版本。"""

    app = _app()
    try:
        version = app.revise_workflow(
            workflow_id,
            change_summary=change_summary,
            objective_template=objective_template,
            parameters=(
                [WorkflowParameter(name=parameter) for parameter in parameter_names]
                if parameter_names
                else None
            ),
        )
        click.echo(f"工作流新版本: {workflow_id}@{version.version}  " f"{version.change_summary}")
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()


@workflow_group.command("run")
@click.argument("workflow_id")
@click.option("--version", type=click.IntRange(min=1))
@click.option(
    "--input",
    "input_values",
    multiple=True,
    help="name=value，可重复",
)
@click.option("--workspace", type=click.Path(file_okay=False))
@click.option("--json-output", is_flag=True, help="输出 JSON")
def run_workflow(
    workflow_id,
    version,
    input_values,
    workspace,
    json_output,
):
    """用指定不可变版本创建并执行新任务。"""

    inputs = {}
    for value in input_values:
        if "=" not in value:
            raise click.ClickException(f"输入必须是 name=value: {value}")
        name, content = value.split("=", 1)
        if not name:
            raise click.ClickException("输入参数名不能为空")
        inputs[name] = content
    app = _app()
    try:
        detail = app.run_workflow(
            workflow_id,
            version=version,
            inputs=inputs,
            workspace=workspace,
            entrypoint="cli",
        )
        if json_output:
            click.echo(detail.model_dump_json(indent=2))
            return
        click.echo(f"任务: {detail.work_item.id}  " f"{detail.work_item.status.value}")
        for artifact in detail.artifacts:
            click.echo(f"  {artifact.kind.value}  {artifact.name}")
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        app.stop()
