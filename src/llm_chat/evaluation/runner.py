"""把 WorkItem 事实投影为可回归的产品质量指标。"""

from __future__ import annotations

from importlib.resources import files
from typing import Any, Iterable, List, Sequence

import yaml

from llm_chat.runtime import ActionStatus, EffectStatus
from llm_chat.work import WorkItemDetail

from .models import EvalReport, EvalResult, EvalScenario


def load_core_scenarios() -> List[EvalScenario]:
    resource = files("llm_chat.evaluation").joinpath("core_scenarios.yaml")
    payload = yaml.safe_load(resource.read_text(encoding="utf-8")) or {}
    return [
        EvalScenario.model_validate(item)
        for item in payload.get("scenarios", [])
    ]


class EvalRunner:
    """评分已有任务；执行实时任务由 CLI/Application Service 显式触发。"""

    def evaluate(
        self,
        scenario: EvalScenario,
        detail: WorkItemDetail,
        *,
        actions: Sequence[Any] = (),
        effects: Sequence[Any] = (),
    ) -> EvalResult:
        item = detail.work_item
        failures: List[str] = []
        checks = {}

        checks["status"] = item.status == scenario.expected_status
        if not checks["status"]:
            failures.append(
                f"status={item.status.value}, expected={scenario.expected_status.value}"
            )

        checks["artifact_count"] = (
            len(detail.artifacts) >= scenario.minimum_artifacts
        )
        if not checks["artifact_count"]:
            failures.append(
                f"artifacts={len(detail.artifacts)}, "
                f"minimum={scenario.minimum_artifacts}"
            )

        if scenario.accepted_artifact_kinds:
            accepted = set(scenario.accepted_artifact_kinds)
            checks["artifact_kind"] = any(
                artifact.kind in accepted for artifact in detail.artifacts
            )
            if not checks["artifact_kind"]:
                failures.append(
                    "no accepted artifact kind: "
                    + ", ".join(kind.value for kind in accepted)
                )
        else:
            checks["artifact_kind"] = True

        decided_actions = [
            action
            for action in actions
            if action.status != ActionStatus.PENDING
        ]
        checks["approval"] = (
            not scenario.requires_approval or bool(decided_actions)
        )
        if not checks["approval"]:
            failures.append("required approval was not decided")

        uncertain_effects = [
            effect
            for effect in effects
            if effect.status == EffectStatus.UNCERTAIN
        ]
        checks["effects_certain"] = not uncertain_effects
        if uncertain_effects:
            failures.append(
                f"{len(uncertain_effects)} external effects are uncertain"
            )

        duration = self._duration_seconds(detail)
        if scenario.maximum_duration_seconds is not None:
            checks["duration"] = bool(
                duration is not None
                and duration <= scenario.maximum_duration_seconds
            )
            if not checks["duration"]:
                failures.append(
                    f"duration={duration}, "
                    f"maximum={scenario.maximum_duration_seconds}"
                )
        else:
            checks["duration"] = True

        return EvalResult(
            scenario_id=scenario.id,
            work_item_id=item.id,
            passed=all(checks.values()),
            checks=checks,
            failures=failures,
            duration_seconds=duration,
            artifact_count=len(detail.artifacts),
            approval_count=len(decided_actions),
            uncertain_effect_count=len(uncertain_effects),
        )

    def report(self, results: Iterable[EvalResult]) -> EvalReport:
        values = list(results)
        count = len(values)
        durations = [
            result.duration_seconds
            for result in values
            if result.duration_seconds is not None
        ]
        return EvalReport(
            results=values,
            scenario_count=count,
            passed_count=sum(result.passed for result in values),
            completion_rate=self._rate(
                sum(result.checks.get("status", False) for result in values),
                count,
            ),
            artifact_rate=self._rate(
                sum(
                    result.checks.get("artifact_count", False)
                    and result.checks.get("artifact_kind", False)
                    for result in values
                ),
                count,
            ),
            approval_compliance_rate=self._rate(
                sum(result.checks.get("approval", False) for result in values),
                count,
            ),
            uncertain_effect_count=sum(
                result.uncertain_effect_count for result in values
            ),
            average_duration_seconds=(
                round(sum(durations) / len(durations), 3)
                if durations
                else None
            ),
        )

    @staticmethod
    def _duration_seconds(detail: WorkItemDetail):
        item = detail.work_item
        latest = next(
            (run for run in detail.runs if run.id == item.latest_run_id),
            None,
        )
        if (
            latest is None
            or latest.started_at is None
            or latest.finished_at is None
        ):
            return None
        return max(
            0.0,
            (latest.finished_at - latest.started_at).total_seconds(),
        )

    @staticmethod
    def _rate(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 0.0
