"""真实核心场景的任务级 Eval CLI。"""

from __future__ import annotations

import click

from llm_chat.app import App
from llm_chat.config import Config
from llm_chat.evaluation import EvalRunner, load_core_scenarios
from llm_chat.work import WorkItemKind


def _scenario(scenario_id):
    scenarios = {item.id: item for item in load_core_scenarios()}
    try:
        return scenarios[scenario_id]
    except KeyError as exc:
        raise click.ClickException(f"Unknown eval scenario: {scenario_id}") from exc


def _score(app, scenario, work_item_id):
    detail = app.get_work_item_detail(work_item_id)
    actions = app.list_work_item_actions(work_item_id)
    run_ids = {run.id for run in detail.runs}
    effects = [
        effect
        for effect in app.list_effects(limit=1000)
        if effect.run_id in run_ids
    ]
    runner = EvalRunner()
    result = runner.evaluate(
        scenario,
        detail,
        actions=actions,
        effects=effects,
    )
    return runner.report([result])


def _print_report(report, json_output):
    if json_output:
        click.echo(report.model_dump_json(indent=2))
        return
    result = report.results[0]
    click.echo(f"场景: {result.scenario_id}")
    click.echo(f"任务: {result.work_item_id}")
    click.echo(f"结果: {'PASS' if result.passed else 'FAIL'}")
    click.echo(f"产物: {result.artifact_count}")
    if result.duration_seconds is not None:
        click.echo(f"耗时: {result.duration_seconds:.3f}s")
    for failure in result.failures:
        click.echo(f"  - {failure}")


@click.group(name="eval")
def eval_group():
    """列出、执行和评分核心产品场景。"""


@eval_group.command("list")
def list_scenarios():
    """列出内置核心场景。"""

    for scenario in load_core_scenarios():
        click.echo(f"{scenario.id:20} {scenario.name}  [{scenario.category}]")


@eval_group.command("score")
@click.argument("scenario_id")
@click.argument("work_item_id")
@click.option("--json-output", is_flag=True, help="输出 JSON")
def score_scenario(scenario_id, work_item_id, json_output):
    """用指定场景验收已有 WorkItem，不调用模型。"""

    scenario = _scenario(scenario_id)
    app = App(Config.from_yaml())
    try:
        report = _score(app, scenario, work_item_id)
        _print_report(report, json_output)
        if not report.results[0].passed:
            raise click.exceptions.Exit(1)
    finally:
        app.stop()


@eval_group.command("run")
@click.argument("scenario_id")
@click.option("--workspace", type=click.Path(file_okay=False), help="工作目录")
@click.option("--json-output", is_flag=True, help="输出 JSON")
def run_scenario(scenario_id, workspace, json_output):
    """真实执行一个核心场景；会调用当前配置的模型和工具。"""

    scenario = _scenario(scenario_id)
    app = App(Config.from_yaml())
    try:
        item = app.create_work_item(
            scenario.objective,
            title=f"Eval · {scenario.name}",
            kind=WorkItemKind.TASK,
            workspace=workspace,
            metadata={
                "source": "eval",
                "eval_scenario_id": scenario.id,
            },
        )
        app.execute_work_item(item.id)
        report = _score(app, scenario, item.id)
        _print_report(report, json_output)
        if not report.results[0].passed:
            raise click.exceptions.Exit(1)
    finally:
        app.stop()
