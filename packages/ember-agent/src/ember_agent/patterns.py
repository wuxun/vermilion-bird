"""MultiAgentPattern — pre-built multi-agent collaboration topologies.

Each method returns a StateGraph definition that can be compiled
and executed with domain-specific state and agent implementations.

Patterns:
    manager_worker   — manager decomposes → workers execute → manager aggregates
    debate           — pro vs con debate → judge decides
    pipeline         — chain: A → B → C with result propagation
    critique_refine  — creator → critics → refine loop
"""

from __future__ import annotations

from typing import Dict, List, Type

from pydantic import BaseModel

from ember_core.graph import StateGraph
from ember_agent.agent.role import AgentRole


class MultiAgentPattern:
    """Factory for pre-built multi-agent collaboration patterns.

    Each pattern returns a StateGraph definition. The caller provides:
    - state_schema: Pydantic model for the graph's state
    - AgentRole definitions for each participating agent

    The caller is responsible for wiring the StateGraph nodes to
    actual LLM-backed agent implementations.
    """

    @staticmethod
    def manager_worker(
        manager: AgentRole,
        workers: List[AgentRole],
        state_schema: Type[BaseModel],
    ) -> StateGraph:
        """Manager decomposes task → Workers execute in parallel → Manager aggregates.

        Graph topology:
            entry → manager_plan → [worker_0, worker_1, ...] → manager_aggregate → finish
        """
        graph = StateGraph(state_schema)

        # Nodes: the caller wires these to actual LLM agents
        graph.add_node("manager_plan", lambda s: s, metadata={
            "role": manager.model_dump(),
            "description": "Manager decomposes task into subtasks",
        })

        graph.add_node("manager_aggregate", lambda s: s, metadata={
            "role": manager.model_dump(),
            "description": "Manager aggregates worker results",
        })

        for i, worker_role in enumerate(workers):
            graph.add_node(f"worker_{i}", lambda s: s, metadata={
                "role": worker_role.model_dump(),
                "description": f"Worker {i}: {worker_role.name}",
            })

        # Edges
        graph.set_entry_point("manager_plan")
        graph.add_edge("manager_plan", "manager_aggregate")
        graph.add_edge("manager_aggregate", "__finish__")

        return graph

    @staticmethod
    def debate(
        pro: AgentRole,
        con: AgentRole,
        judge: AgentRole,
        state_schema: Type[BaseModel],
        rounds: int = 3,
    ) -> StateGraph:
        """Pro vs Con debate → Judge decides.

        Graph topology:
            pro → con → (loop) → judge → finish
        """
        graph = StateGraph(state_schema)

        graph.add_node("pro_argue", lambda s: s, metadata={
            "role": pro.model_dump(),
            "description": "Pro side argues in favor",
        })

        graph.add_node("con_argue", lambda s: s, metadata={
            "role": con.model_dump(),
            "description": "Con side argues against",
        })

        graph.add_node("judge_verdict", lambda s: s, metadata={
            "role": judge.model_dump(),
            "description": "Judge evaluates both sides and decides",
        })

        graph.set_entry_point("pro_argue")
        graph.add_edge("pro_argue", "con_argue")

        # Loop: pro → con → (back to pro or proceed to judge)
        def debate_router(state):
            round_count = getattr(state, "debate_round", 0) + 1
            # Update round count (caller's state schema needs this field)
            if hasattr(state, "debate_round"):
                state.debate_round = round_count
            if round_count < rounds:
                return "pro_argue"
            return "judge_verdict"

        graph.add_conditional_edge(
            "con_argue",
            debate_router,
            {"pro_argue": "pro_argue", "judge_verdict": "judge_verdict"},
        )
        graph.add_edge("judge_verdict", "__finish__")

        return graph

    @staticmethod
    def pipeline_chain(
        roles: List[AgentRole],
        state_schema: Type[BaseModel],
    ) -> StateGraph:
        """Chain: role_0 → role_1 → ... → role_n → finish.

        Each stage's output is passed as context to the next.
        """
        graph = StateGraph(state_schema)

        for i, role in enumerate(roles):
            graph.add_node(f"stage_{i}", lambda s: s, metadata={
                "role": role.model_dump(),
                "description": f"Stage {i}: {role.name}",
            })

        graph.set_entry_point("stage_0")
        for i in range(len(roles) - 1):
            graph.add_edge(f"stage_{i}", f"stage_{i + 1}")
        graph.add_edge(f"stage_{len(roles) - 1}", "__finish__")

        return graph

    @staticmethod
    def critique_refine(
        creator: AgentRole,
        critics: List[AgentRole],
        state_schema: Type[BaseModel],
        max_rounds: int = 3,
    ) -> StateGraph:
        """Creator produces → Critics review → Creator refines → repeat.

        Loop until all critics pass or max_rounds reached.
        """
        graph = StateGraph(state_schema)

        graph.add_node("creator_produce", lambda s: s, metadata={
            "role": creator.model_dump(),
            "description": "Creator produces initial output",
        })

        # Single aggregate critic node
        graph.add_node("critics_review", lambda s: s, metadata={
            "description": f"{len(critics)} critics review the output",
        })

        graph.add_node("creator_refine", lambda s: s, metadata={
            "role": creator.model_dump(),
            "description": "Creator refines based on feedback",
        })

        graph.set_entry_point("creator_produce")
        graph.add_edge("creator_produce", "critics_review")

        def refine_router(state):
            round_count = getattr(state, "refine_round", 0) + 1
            if hasattr(state, "refine_round"):
                state.refine_round = round_count
            all_passed = getattr(state, "all_passed", False)
            if all_passed or round_count >= max_rounds:
                return "__finish__"
            return "creator_refine"

        graph.add_conditional_edge(
            "critics_review",
            refine_router,
            {"creator_refine": "creator_refine", "__finish__": "__finish__"},
        )
        graph.add_edge("creator_refine", "critics_review")

        return graph
