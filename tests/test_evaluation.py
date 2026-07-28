from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from llm_chat.cli import cli
from llm_chat.evaluation import EvalRunner, EvalScenario, load_core_scenarios
from llm_chat.runtime import ActionStatus, EffectStatus, Run, RunStatus, RunType
from llm_chat.work import (
    Artifact,
    ArtifactKind,
    WorkItem,
    WorkItemDetail,
    WorkItemStatus,
)


def _detail(*, status=WorkItemStatus.COMPLETED, artifacts=True):
    started = datetime.now(timezone.utc)
    finished = started + timedelta(seconds=12)
    item = WorkItem(
        id="work_eval",
        title="Eval",
        objective="形成报告",
        status=status,
        latest_run_id="run_eval",
        created_at=started,
        updated_at=finished,
        completed_at=finished if status.terminal else None,
    )
    run = Run(
        id="run_eval",
        work_item_id=item.id,
        type=RunType.WORKFLOW,
        status=RunStatus.COMPLETED,
        started_at=started,
        finished_at=finished,
    )
    output = (
        [
            Artifact(
                id="artifact_eval",
                work_item_id=item.id,
                run_id=run.id,
                kind=ArtifactKind.REPORT,
                name="report.md",
                content="# Report",
            )
        ]
        if artifacts
        else []
    )
    return WorkItemDetail(work_item=item, runs=[run], artifacts=output)


def test_core_scenario_dataset_is_parseable_and_product_focused():
    scenarios = load_core_scenarios()

    assert {scenario.id for scenario in scenarios} == {
        "research_report",
        "workspace_analysis",
        "recurring_digest",
    }
    assert all(scenario.minimum_artifacts >= 1 for scenario in scenarios)


def test_eval_runner_scores_completion_artifact_approval_and_effects():
    scenario = EvalScenario(
        id="approval_report",
        name="Approval report",
        category="workspace",
        objective="write report",
        accepted_artifact_kinds=[ArtifactKind.REPORT],
        requires_approval=True,
        maximum_duration_seconds=20,
    )
    action = SimpleNamespace(status=ActionStatus.COMPLETED)
    effect = SimpleNamespace(status=EffectStatus.COMPLETED)

    result = EvalRunner().evaluate(
        scenario,
        _detail(),
        actions=[action],
        effects=[effect],
    )

    assert result.passed is True
    assert all(result.checks.values())
    assert result.duration_seconds == 12


def test_eval_runner_fails_missing_artifact_and_uncertain_effect():
    scenario = load_core_scenarios()[0]
    uncertain = SimpleNamespace(status=EffectStatus.UNCERTAIN)

    result = EvalRunner().evaluate(
        scenario,
        _detail(artifacts=False),
        effects=[uncertain],
    )

    assert result.passed is False
    assert result.checks["artifact_count"] is False
    assert result.checks["effects_certain"] is False
    assert result.uncertain_effect_count == 1


def test_eval_report_aggregates_product_rates():
    runner = EvalRunner()
    scenario = load_core_scenarios()[0]
    passed = runner.evaluate(scenario, _detail())
    failed = runner.evaluate(scenario, _detail(artifacts=False))

    report = runner.report([passed, failed])

    assert report.scenario_count == 2
    assert report.passed_count == 1
    assert report.completion_rate == 1.0
    assert report.artifact_rate == 0.5


def test_eval_cli_lists_scenarios():
    result = CliRunner().invoke(cli, ["eval", "list"])

    assert result.exit_code == 0
    assert "research_report" in result.output
    assert "workspace_analysis" in result.output


def test_eval_cli_scores_existing_work_item_without_model_call():
    app = MagicMock()
    detail = _detail()
    app.get_work_item_detail.return_value = detail
    app.list_work_item_actions.return_value = []
    app.list_effects.return_value = []

    with patch("llm_chat.cli.eval.App", return_value=app):
        result = CliRunner().invoke(
            cli,
            ["eval", "score", "research_report", "work_eval"],
        )

    assert result.exit_code == 0
    assert "PASS" in result.output
    app.execute_work_item.assert_not_called()
    app.stop.assert_called_once()
