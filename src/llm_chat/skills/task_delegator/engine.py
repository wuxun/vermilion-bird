"""CollaborationEngine — executes CollaborationPatterns by spawning agents.

Used by spawn_subagent tool when pattern="xxx" is specified.
Walks the pattern stages, spawns agents with AgentRoles, collects results.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ember_agent.patterns import CollaborationPattern, PatternStage
    from llm_chat.skills.task_delegator.tools import SpawnSubagentTool

logger = logging.getLogger(__name__)


class CollaborationEngine:
    """Executes a CollaborationPattern by orchestrating SpawnSubagentTool calls.

    Flow:
        1. Walk stages in dependency order
        2. For each stage, spawn agent(s) with the specified role
        3. Wait for results (blocking within the pattern execution)
        4. Feed results forward as template variables
        5. If aggregator_role is set, spawn final aggregation agent
    """

    def __init__(self, spawn_tool: "SpawnSubagentTool"):
        self._spawn = spawn_tool
        self._results_cache: Dict[str, str] = {}

    def execute(
        self,
        pattern: "CollaborationPattern",
        user_task: str,
        **extra_vars,
    ) -> str:
        """Execute a named pattern and return the final result."""
        from ember_agent.agent.blackboard import SharedBlackboard
        blackboard = SharedBlackboard()
        self._blackboard = blackboard  # Expose for sub-agents

        logger.info(
            f"Pattern '{pattern.name}': {len(pattern.stages)} stages, "
            f"max_rounds={pattern.max_rounds}, aggregator={pattern.aggregator_role or 'none'}"
        )
        start = time.time()

        vars: Dict[str, Any] = {"user_task": user_task, **extra_vars}
        stage_results: Dict[str, str] = {}
        total_agents = 0
        failures: Dict[str, str] = {}  # Track failures per stage

        for round_num in range(pattern.max_rounds):
            if round_num > 0:
                logger.info(f"Pattern '{pattern.name}': round {round_num + 1}/{pattern.max_rounds}")

            round_results = self._execute_stages(
                pattern.stages, vars, stage_results, pattern, round_num,
            )
            total_agents += round_results["_agent_count"]
            failures.update(round_results.get("_errors", {}))
            del round_results["_agent_count"]
            round_results.pop("_errors", None)

            # Check if loop should continue (critique_refine pattern)
            if pattern.max_rounds > 1 and round_num < pattern.max_rounds - 1:
                # Look for PASS signal in any stage result
                if any(
                    r.upper().startswith("PASS")
                    for r in round_results.values()
                ):
                    logger.info(f"Pattern '{pattern.name}': pass signal, breaking loop")
                    break
                # Otherwise: feed last round results as next round input
                stage_results = round_results

        # Aggregation
        if pattern.aggregator_role:
            agg_task = pattern.aggregator_task or "Synthesize results"
            agg_task = self._resolve_template(agg_task, vars, stage_results)
            ctx_parts = []
            for sid, sresult in stage_results.items():
                ctx_parts.append(f"=== {sid} ===\n{sresult}")
            agg_task = agg_task + "\n\nInputs:\n" + "\n\n".join(ctx_parts)

            final = self._spawn_and_wait(
                pattern.aggregator_role, agg_task,
                timeout=pattern.timeout_per_agent,
            )
            total_agents += 1
        else:
            parts = []
            for sid, sresult in stage_results.items():
                parts.append(f"## {sid}\n{sresult}")
            final = "\n\n".join(parts)

        elapsed = time.time() - start
        blackboard_entries = len(blackboard) if hasattr(self, '_blackboard') else 0

        # Structured result summary
        summary = json.dumps({
            "pattern": pattern.name,
            "status": "completed" if not failures else "partial",
            "agents": total_agents,
            "blackboard_entries": blackboard_entries,
            "time_seconds": round(elapsed, 1),
            "errors": failures if failures else {},
            "stages": {
                sid: sr[:200] + "..." if len(sr) > 200 else sr
                for sid, sr in stage_results.items()
            } if stage_results else {},
        }, ensure_ascii=False, indent=2)

        logger.info(
            f"Pattern '{pattern.name}' complete: "
            f"{total_agents} agents, {blackboard_entries} findings, "
            f"{len(failures)} errors, {elapsed:.1f}s"
        )

        return final + "\n\n---\n" + summary

    def _execute_stages(
        self,
        stages: list,
        vars: Dict[str, Any],
        prev_results: Dict[str, str],
        pattern: "CollaborationPattern",
        round_num: int,
    ) -> Dict[str, Any]:
        """Execute one pass through the pattern stages. Returns {stage_id: result, _agent_count: int, _errors: {}}."""
        stage_results: Dict[str, str] = {}
        errors: Dict[str, str] = {}
        total_agents = 0
        completed = set(prev_results.keys())
        remaining = list(stages)

        while remaining:
            ready = [
                s for s in remaining
                if all(d in completed for d in s.depends_on)
            ]
            if not ready:
                remaining_ids = [s.id for s in remaining]
                logger.error(f"Deadlock in stages: {remaining_ids}, completed={completed}")
                for s in remaining:
                    errors[s.id] = f"Deadlocked: depends on {[d for d in s.depends_on if d not in completed]}"
                    stage_results[s.id] = f"[Error: {errors[s.id]}]"
                    completed.add(s.id)
                remaining.clear()
                break

            for stage in ready:
                remaining.remove(stage)
                logger.info(f"Stage '{stage.id}': spawning {stage.parallel}x role='{stage.role}'")

                task = self._resolve_template(stage.task, vars, {**prev_results, **stage_results})

                if stage.parallel == 1:
                    try:
                        result = self._spawn_and_wait(stage.role, task, timeout=pattern.timeout_per_agent)
                        stage_results[stage.id] = result
                        total_agents += 1
                    except Exception as e:
                        error_msg = f"[Error: {e}]"
                        errors[stage.id] = str(e)
                        stage_results[stage.id] = error_msg
                        if not pattern.continue_on_failure:
                            raise
                        logger.warning(f"Stage '{stage.id}' failed (continuing): {e}")
                else:
                    agent_ids = []
                    for i in range(stage.parallel):
                        indexed_task = (
                            f"{task}\n\n=== Sub-task #{i + 1} of {stage.parallel} ===\n"
                            f"Process sub-task #{i + 1}. Use query_findings to check what others have done."
                        )
                        agent_ids.append(
                            self._spawn_async(stage.role, indexed_task, pattern.timeout_per_agent)
                        )
                    parallel_results = []
                    for aid in agent_ids:
                        try:
                            result = self._wait_for(aid, pattern.timeout_per_agent)
                        except Exception as e:
                            result = f"[Error: {e}]"
                            errors[f"{stage.id}/{aid}"] = str(e)
                        parallel_results.append(result)
                        total_agents += 1
                    stage_results[stage.id] = self._collect_results(parallel_results, stage.collect)
                    logger.info(f"Stage '{stage.id}': {stage.parallel} agents completed")

                completed.add(stage.id)

        stage_results["_agent_count"] = total_agents
        stage_results["_errors"] = errors
        return stage_results

    def _resolve_template(
        self,
        template: str,
        vars: Dict[str, Any],
        stage_results: Dict[str, str],
    ) -> str:
        """Resolve {var_name} and {stage_id.result} in template."""
        result = template
        # First: simple variables
        for key, val in vars.items():
            result = result.replace("{" + key + "}", str(val))
        # Then: stage results
        for sid, sresult in stage_results.items():
            result = result.replace("{" + sid + ".result}", sresult)
        return result

    def _spawn_and_wait(
        self, role: str, task: str, timeout: int = 300,
    ) -> str:
        """Spawn a single agent and wait for its result."""
        extra = {}
        if hasattr(self, '_blackboard') and self._blackboard:
            extra["blackboard"] = self._blackboard
        result_json = self._spawn.execute(
            task=task, role=role, wait=True, timeout=timeout, **extra,
        )
        parsed = json.loads(result_json)
        if parsed.get("status") == "completed":
            result = parsed.get("result", "")
            # Store result under agent_id for template resolution
            agent_id = parsed.get("agent_id", "")
            if agent_id and result:
                self._results_cache[agent_id] = result
            return result
        return f"[{parsed.get('status', 'error')}] {parsed.get('error', '')}"

    def _spawn_async(
        self, role: str, task: str, timeout: int = 300,
    ) -> str:
        """Spawn an agent asynchronously, return agent_id."""
        result_json = self._spawn.execute(
            task=task,
            role=role,
            wait=False,
            timeout=timeout,
        )
        parsed = json.loads(result_json)
        return parsed.get("agent_id", "")

    def _wait_for(self, agent_id: str, timeout: int = 300) -> str:
        """Wait for a previously spawned agent and return its result."""
        if not agent_id:
            return "[Error: no agent id]"
        registry = self._spawn.registry
        result = registry.wait_for(agent_id, timeout=timeout)
        if result is not None:
            return result
        ctx = registry.get(agent_id)
        if ctx and ctx.result:
            return ctx.result
        return f"[Agent {agent_id}: timed out or not found]"

    def _collect_results(
        self, results: List[str], strategy: str,
    ) -> str:
        """Collect parallel results into a single string."""
        if not strategy or strategy == "concat":
            return "\n\n".join(
                f"[{i+1}] {r}" for i, r in enumerate(results)
            )
        elif strategy == "numbered":
            return "\n\n".join(
                f"## Finding {i+1}\n{r}" for i, r in enumerate(results)
            )
        elif strategy == "json_array":
            return json.dumps(results, ensure_ascii=False, indent=2)
        else:
            return "\n\n".join(results)
