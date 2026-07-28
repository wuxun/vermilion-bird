import logging
import os
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List, TYPE_CHECKING

logger = logging.getLogger(__name__)

from llm_chat.client import LLMClient
from llm_chat.config import Config
from llm_chat.conversation import Conversation, ConversationManager
from llm_chat.chat_core_graph import ChatCoreGraph as ChatCore
from llm_chat.frontends.base import (
    BaseFrontend,
    Message,
    ConversationContext,
    MessageType,
)
from llm_chat.storage import Storage
from llm_chat.skills import SkillManager
from llm_chat.service_manager import ServiceManager
from llm_chat.health import get_checker, create_database_checker, create_service_manager_checker
from llm_chat.runtime import (
    ActionProposal,
    ActionProposalManager,
    ActionStatus,
    CapabilityPolicy,
    EffectOutbox,
    EffectReconciliationService,
    EffectResolution,
    EffectStatus,
    RunDispatcher,
    RunHandlerRegistry,
    RunRecoveryCoordinator,
    RunManager,
    RunStatus,
    RunType,
)
from llm_chat.work import (
    ArtifactKind,
    GrantScope,
    PlanStepStatus,
    ResourceGrantService,
    ResourceType,
    WorkItemKind,
    WorkItemService,
    WorkItemStatus,
)

if TYPE_CHECKING:
    from llm_chat.scheduler.scheduler import SchedulerService
    from llm_chat.mcp import MCPManager


class App:
    """应用协调器

    职责：
    - 创建并装配所有组件 (client, storage, ChatCore, MCP, scheduler, health)
    - 管理 MCP 工具连接
    - 管理前端生命周期 (set_frontend / run / stop)
    - 会话 CRUD 回调

    NOT 负责：
    - 对话处理管道 → 委托给 ChatCore
    - 前端渲染 → 各前端自行处理
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        *,
        client: Optional[LLMClient] = None,
        storage: Optional[Storage] = None,
    ):
        import time

        _t0 = time.time()

        self.config = config or Config()
        self.current_frontend: Optional[BaseFrontend] = None
        self._mcp_manager = None  # MCPManager, lazy import
        self._tools_enabled = False
        self._current_conversation_id: str = "default"
        self.scheduler: Optional["SchedulerService"] = None
        self._client_override = client
        self._storage_override = storage

        # 组件分层初始化（保持依赖顺序）
        self.tool_registry = self._init_tool_registry()
        _t1 = time.time()
        logger.info(f"⏱ _init_tool_registry: {_t1-_t0:.3f}s")
        self._init_role_presets()
        _t1b = time.time()
        logger.info(f"⏱ _init_role_presets: {_t1b-_t1:.3f}s")
        self._init_ghosts()
        _t1c = time.time()
        logger.info(f"⏱ _init_ghosts: {_t1c-_t1b:.3f}s")
        self.storage = self._init_storage()
        _t2 = time.time()
        logger.info(f"⏱ _init_storage: {_t2-_t1:.3f}s")
        self.client = self._init_client()
        _t3 = time.time()
        logger.info(f"⏱ _init_client: {_t3-_t2:.3f}s")
        self.conversation_manager = self._init_conversation_manager()
        _t4 = time.time()
        logger.info(f"⏱ _init_conversation_manager: {_t4-_t3:.3f}s")
        self.run_manager = RunManager(repository=self.storage)
        self.work_items = WorkItemService(
            repository=self.storage,
            runs=self.run_manager,
        )
        self.resource_grants = ResourceGrantService(self.storage)
        self.capability_policy = CapabilityPolicy()
        self.action_proposals = ActionProposalManager(repository=self.storage)
        self.effect_outbox = EffectOutbox(self.storage)
        self.uncertain_effects = self.effect_outbox.reconcile_interrupted()
        self.effect_reconciliation = EffectReconciliationService(
            outbox=self.effect_outbox,
            proposals=self.action_proposals,
            runs=self.run_manager,
        )
        self.repaired_effects = self.effect_reconciliation.repair_linked_state()
        self._graph_lock = threading.RLock()
        self.graph_runtime = None
        self.graph_execution = None
        self._action_coordinator = None
        self.run_handlers = RunHandlerRegistry()
        self.run_dispatcher = RunDispatcher(
            run_manager=self.run_manager,
            registry=self.run_handlers,
        )
        self._bind_skill_runtime()
        self._ensure_graph_infrastructure()
        self.chat_core = self._init_chat_core()
        self.run_handlers.register("chat", self.chat_core)
        self.run_recovery = RunRecoveryCoordinator(
            run_manager=self.run_manager,
            dispatcher=self.run_dispatcher,
        )
        _t5 = time.time()
        logger.info(f"⏱ _init_chat_core: {_t5-_t4:.3f}s")
        self._init_prompt_skills()
        _t6 = time.time()
        logger.info(f"⏱ _init_prompt_skills: {_t6-_t5:.3f}s")
        self.service_manager = self._init_service_manager()
        _t7 = time.time()
        logger.info(f"⏱ _init_service_manager: {_t7-_t6:.3f}s")
        self._health_checker = self._init_health_checker()
        _t8 = time.time()
        logger.info(f"⏱ _init_health_checker: {_t8-_t7:.3f}s")
        # Scheduler 延迟到 _start_background_services 中初始化

        logger.info(f"⏱ App init total: {_t8-_t0:.3f}s")

    # ------------------------------------------------------------------
    # Factory methods (按依赖顺序)
    # ------------------------------------------------------------------

    def _init_tool_registry(self):
        from llm_chat.tools.registry import ToolRegistry

        tr = ToolRegistry()
        ToolRegistry.set_instance(tr)
        return tr

    def _init_storage(self):
        db_path = os.environ.get("VB_DB_PATH", Storage.DEFAULT_DB_PATH)
        s = self._storage_override if self._storage_override is not None else Storage(db_path)
        Storage.set_instance(s)
        return s

    def approve_action(
        self,
        proposal_id: str,
        *,
        conversation_id: Optional[str] = None,
        parent_run_id: Optional[str] = None,
    ) -> ActionProposal:
        """批准并执行持久化动作，由 CLI 与 GUI 共用。"""

        current = self.action_proposals.get(proposal_id)
        if current is None:
            raise KeyError(f"Unknown action proposal: {proposal_id}")
        if current.execution_run_id:
            proposal = self._ensure_action_coordinator().approve(
                proposal_id,
                conversation_id=conversation_id,
            )
        else:
            # 兼容升级前已持久化、尚未绑定 durable Run 的提案。
            proposal = self.action_proposals.approve_and_execute(
                proposal_id,
                tool_registry=self.tool_registry,
                run_manager=self.run_manager,
                parent_run_id=parent_run_id,
                conversation_id=conversation_id,
            )
        if self.run_manager.get(proposal.run_id):
            self.run_manager.emit(
                proposal.run_id,
                f"action.{proposal.status.value}",
                {"proposal_id": proposal.id},
            )
        return proposal

    def create_work_item(
        self,
        objective: str,
        *,
        title: Optional[str] = None,
        kind: WorkItemKind = WorkItemKind.TASK,
        conversation_id: Optional[str] = None,
        workspace: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """创建用户可见任务；执行由具体应用用例随后启动。"""

        return self.work_items.create(
            objective=objective,
            title=title,
            kind=kind,
            conversation_id=conversation_id,
            workspace=workspace,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )

    def list_work_items(
        self,
        *,
        status: Optional[WorkItemStatus] = None,
        kind: Optional[WorkItemKind] = None,
        limit: int = 100,
    ):
        return self.work_items.list(
            limit=limit,
            status=status,
            kind=kind,
        )

    def get_work_item_detail(self, work_item_id: str):
        return self.work_items.detail(work_item_id)

    def create_work_item_plan(
        self,
        work_item_id: str,
        *,
        summary: str,
        steps: List[Dict[str, Any]],
        change_summary: str = "",
        approve: bool = False,
    ):
        return self.work_items.create_plan_revision(
            work_item_id,
            summary=summary,
            steps=steps,
            change_summary=change_summary,
            approve=approve,
        )

    def approve_work_item_plan(self, work_item_id: str, plan_id: str):
        return self.work_items.approve_plan_revision(work_item_id, plan_id)

    def update_work_item_plan_step(
        self,
        work_item_id: str,
        step_id: str,
        status: PlanStepStatus,
    ):
        return self.work_items.update_plan_step(work_item_id, step_id, status)

    def list_work_item_plans(self, work_item_id: str, *, limit: int = 50):
        return self.work_items.list_plan_revisions(work_item_id, limit=limit)

    def create_resource_grant(
        self,
        *,
        work_item_id: str,
        capability: str,
        resource_type: ResourceType,
        resource: str,
        scope: GrantScope = GrantScope.WORK_ITEM,
        expires_at=None,
        reason: str = "",
    ):
        item = self.work_items.get(work_item_id)
        if item is None:
            raise KeyError(f"Unknown work item: {work_item_id}")
        return self.resource_grants.create(
            work_item_id=work_item_id,
            workflow_id=item.workflow_id,
            capability=capability,
            resource_type=resource_type,
            resource=resource,
            scope=scope,
            expires_at=expires_at,
            reason=reason,
        )

    def revoke_resource_grant(self, grant_id: str):
        return self.resource_grants.revoke(grant_id)

    def list_resource_grants(
        self,
        *,
        work_item_id: Optional[str] = None,
        include_inactive: bool = False,
    ):
        return self.resource_grants.list(
            work_item_id=work_item_id,
            include_inactive=include_inactive,
        )

    def list_work_item_actions(
        self,
        work_item_id: str,
        *,
        status: Optional[ActionStatus] = None,
        limit: int = 500,
    ):
        """列出任务所有主/子 Run 关联的动作提案。"""

        detail = self.work_items.detail(work_item_id)
        run_ids = {run.id for run in detail.runs}
        proposals = self.action_proposals.list(status=status, limit=limit)
        return [
            proposal
            for proposal in proposals
            if proposal.run_id in run_ids or proposal.execution_run_id in run_ids
        ]

    def execute_work_item(self, work_item_id: str):
        """通过主 ChatGraph 执行用户任务，并将文本结果固化为 Artifact。"""

        item = self.work_items.get(work_item_id)
        if item is None:
            raise KeyError(f"Unknown work item: {work_item_id}")
        conversation_id = item.conversation_id
        if not conversation_id:
            conversation = self.conversation_manager.create_conversation(title=item.title)
            conversation_id = conversation.conversation_id
            item = self.work_items.bind_conversation(item.id, conversation_id)
        elif self.storage.get_conversation(conversation_id) is None:
            self.storage.create_conversation(conversation_id, item.title)

        approved_plan = self.storage.get_latest_plan_revision(
            item.id,
            approved_only=True,
        )
        execution_request = self._work_item_execution_request(
            item.objective,
            approved_plan,
        )
        self.chat_core.send_message(
            conversation_id=conversation_id,
            message=execution_request,
            work_item_id=item.id,
            run_type=RunType.WORKFLOW,
        )
        self.work_items.reconcile()
        return self._materialize_work_item_result(item.id)

    @staticmethod
    def _work_item_execution_request(objective: str, approved_plan) -> str:
        if approved_plan is None:
            return objective
        steps = "\n".join(
            f"{step.position}. {step.title}" + (f"：{step.description}" if step.description else "")
            for step in approved_plan.steps
        )
        return (
            f"{objective}\n\n"
            f"已批准执行计划 v{approved_plan.version}（"
            f"{approved_plan.id}）：{approved_plan.summary}\n"
            f"{steps}\n\n"
            "按计划顺序执行；若事实变化导致计划不再适用，停止高风险动作并说明"
            "需要修订的步骤，不得自行扩大资源权限。"
        )

    def _materialize_work_item_result(self, work_item_id: str):
        detail = self.work_items.detail(work_item_id)
        latest = next(
            (run for run in detail.runs if run.id == detail.work_item.latest_run_id),
            None,
        )
        if latest and latest.status == RunStatus.COMPLETED and isinstance(latest.result, str):
            self.work_items.add_artifact(
                work_item_id,
                run_id=latest.id,
                kind=ArtifactKind.TEXT,
                name=f"{detail.work_item.title} - 结果",
                content=latest.result,
                content_preview=latest.result[:500],
                idempotency_key=f"{latest.id}:primary-result",
                metadata={"role": "primary_result"},
            )
            detail = self.work_items.detail(work_item_id)
        return detail

    def cancel_work_item(self, work_item_id: str):
        detail = self.work_items.detail(work_item_id)
        latest_run_id = detail.work_item.latest_run_id
        if not latest_run_id:
            raise ValueError(f"Work item {work_item_id} has no active run")
        for proposal in self.list_work_item_actions(
            work_item_id,
            status=ActionStatus.PENDING,
        ):
            self.reject_action(
                proposal.id,
                conversation_id=proposal.conversation_id,
            )
        current = self.run_manager.get(latest_run_id)
        if current is not None and not current.status.terminal:
            self.run_manager.request_cancel(
                current.id,
                reason=f"work_item:{work_item_id}",
                cascade=True,
            )
        self.work_items.reconcile()
        return self.work_items.detail(work_item_id)

    def _resumable_work_item_run(self, work_item_id: str):
        detail = self.work_items.detail(work_item_id)
        for run in detail.runs:
            if run.metadata.get("approval_kind"):
                continue
            if run.status == RunStatus.PAUSED and self.can_resume_run(run.id):
                return run
        return None

    def can_resume_work_item(self, work_item_id: str) -> bool:
        return self._resumable_work_item_run(work_item_id) is not None

    def resume_work_item(self, work_item_id: str):
        run = self._resumable_work_item_run(work_item_id)
        if run is None:
            raise ValueError(f"Work item {work_item_id} has no resumable run")
        self.resume_run(run.id, True)
        self.work_items.reconcile()
        return self._materialize_work_item_result(work_item_id)

    def _pausable_work_item_run(self, work_item_id: str):
        detail = self.work_items.detail(work_item_id)
        latest_run_id = detail.work_item.latest_run_id
        run = next(
            (candidate for candidate in detail.runs if candidate.id == latest_run_id),
            None,
        )
        if (
            run is not None
            and run.status == RunStatus.RUNNING
            and run.checkpoint is not None
            and run.metadata.get("run_handler") == "chat"
        ):
            return run
        return None

    def can_pause_work_item(self, work_item_id: str) -> bool:
        return self._pausable_work_item_run(work_item_id) is not None

    def pause_work_item(self, work_item_id: str):
        run = self._pausable_work_item_run(work_item_id)
        if run is None:
            raise ValueError(f"Work item {work_item_id} has no pausable run")
        self.run_manager.request_pause(
            run.id,
            reason=f"work_item:{work_item_id}",
            cascade=True,
        )
        self.work_items.reconcile()
        return self.work_items.detail(work_item_id)

    def can_retry_work_item(self, work_item_id: str) -> bool:
        item = self.work_items.get(work_item_id)
        return bool(item and item.latest_run_id and self.can_retry_run(item.latest_run_id))

    def retry_work_item(self, work_item_id: str):
        detail = self.work_items.detail(work_item_id)
        latest_run_id = detail.work_item.latest_run_id
        if not latest_run_id:
            raise ValueError(f"Work item {work_item_id} has no run to retry")
        self.retry_run(latest_run_id)
        self.work_items.reconcile()
        return self._materialize_work_item_result(work_item_id)

    def add_work_item_artifact(
        self,
        work_item_id: str,
        *,
        name: str,
        kind: ArtifactKind = ArtifactKind.OTHER,
        run_id: Optional[str] = None,
        uri: Optional[str] = None,
        content: Optional[str] = None,
        content_preview: Optional[str] = None,
        checksum: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        return self.work_items.add_artifact(
            work_item_id,
            name=name,
            kind=kind,
            run_id=run_id,
            uri=uri,
            content=content,
            content_preview=content_preview,
            checksum=checksum,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )

    def reject_action(
        self,
        proposal_id: str,
        *,
        conversation_id: Optional[str] = None,
    ) -> ActionProposal:
        """拒绝持久化动作并记录来源 Run 事件。"""

        current = self.action_proposals.get(proposal_id)
        if current is None:
            raise KeyError(f"Unknown action proposal: {proposal_id}")
        if current.execution_run_id:
            proposal = self._ensure_action_coordinator().reject(
                proposal_id,
                conversation_id=conversation_id,
            )
        else:
            proposal = self.action_proposals.reject(
                proposal_id,
                conversation_id=conversation_id,
            )
        if self.run_manager.get(proposal.run_id):
            self.run_manager.emit(
                proposal.run_id,
                "action.rejected",
                {"proposal_id": proposal.id},
            )
        return proposal

    def list_effects(
        self,
        *,
        status: Optional[EffectStatus] = None,
        limit: int = 500,
    ):
        return self.effect_reconciliation.list(status=status, limit=limit)

    def resolve_effect(
        self,
        effect_key: str,
        *,
        resolution: EffectResolution,
        note: str,
        result: Any = None,
    ):
        """记录人工副作用核对结论，并同步 Action/Run 状态。"""

        return self.effect_reconciliation.resolve(
            effect_key,
            resolution=resolution,
            note=note,
            result=result,
        )

    def prepare_action(self, proposal: ActionProposal) -> ActionProposal:
        """为待审批工具创建持久化 interrupt Run。"""

        return self._ensure_action_coordinator().prepare(proposal)

    def resume_run(self, run_id: str, value: Any = True):
        """恢复 GUI/CLI 选中的 durable Run。"""

        self._ensure_handler_for_run(run_id)
        return self.run_dispatcher.resume(run_id, value)

    def retry_run(self, run_id: str):
        self._ensure_handler_for_run(run_id)
        return self.run_dispatcher.retry(run_id)

    def replay_run(self, run_id: str):
        self._ensure_handler_for_run(run_id)
        return self.run_dispatcher.replay(run_id)

    def can_resume_run(self, run_id: str) -> bool:
        try:
            self._ensure_handler_for_run(run_id)
        except (KeyError, ValueError):
            return False
        return self.run_dispatcher.can_resume(run_id)

    def can_retry_run(self, run_id: str) -> bool:
        try:
            self._ensure_handler_for_run(run_id)
        except (KeyError, ValueError):
            return False
        return self.run_dispatcher.can_retry(run_id)

    def can_replay_run(self, run_id: str) -> bool:
        try:
            self._ensure_handler_for_run(run_id)
        except (KeyError, ValueError):
            return False
        return self.run_dispatcher.can_replay(run_id)

    def _ensure_handler_for_run(self, run_id: str) -> None:
        run = self.run_manager.get(run_id)
        if run is None:
            raise KeyError(f"Unknown run: {run_id}")
        if run.metadata.get("run_handler") == "action":
            self._ensure_action_coordinator()

    def _ensure_graph_infrastructure(self):
        with self._graph_lock:
            if self.graph_runtime is not None:
                return self.graph_runtime

            from llm_chat.runtime import GraphExecutionService, LangGraphRuntime

            graph_runtime = LangGraphRuntime(self.storage._db_path)
            graph_execution = GraphExecutionService(
                run_manager=self.run_manager,
                graph_runtime=graph_runtime,
            )
            self.graph_runtime = graph_runtime
            self.graph_execution = graph_execution
            if not hasattr(self, "run_handlers"):
                self.run_handlers = RunHandlerRegistry()
                self.run_dispatcher = RunDispatcher(
                    run_manager=self.run_manager,
                    registry=self.run_handlers,
                )
            self.run_handlers.register("graph", graph_execution, replace=True)
            return graph_runtime

    def _ensure_action_coordinator(self):
        with self._graph_lock:
            if self._action_coordinator is not None:
                return self._action_coordinator

            from llm_chat.runtime import (
                DurableActionCoordinator,
                build_tool_approval_graph,
            )

            graph_runtime = self._ensure_graph_infrastructure()
            coordinator = DurableActionCoordinator(
                proposals=self.action_proposals,
                execution_service=self.graph_execution,
                tool_registry=self.tool_registry,
                effect_outbox=getattr(self, "effect_outbox", None),
            )
            if not graph_runtime.has_graph(coordinator.GRAPH_NAME):
                graph_runtime.register_builder(
                    coordinator.GRAPH_NAME,
                    build_tool_approval_graph(coordinator.execute_approved),
                )
            self._action_coordinator = coordinator
            self.run_handlers.register("action", coordinator, replace=True)
            return coordinator

    def _init_role_presets(self):
        """Load custom agent roles and patterns from YAML config."""
        from ember_agent.agent.role import load_presets_from_yaml

        role_count = load_presets_from_yaml()
        from ember_agent.patterns import load_patterns_from_yaml

        pat_count = load_patterns_from_yaml()
        if role_count or pat_count:
            logger.info(
                f"Loaded {role_count} custom role(s) and "
                f"{pat_count} pattern(s) from config.yaml"
            )

    def _init_ghosts(self):
        """Preload Ghost templates from ~/.vermilion-bird/ghosts/."""
        try:
            from llm_chat.ghost.store import get_ghost_store

            store = get_ghost_store()
            count = len(store.all_cached())
            if count:
                logger.info(f"Loaded {count} ghost(s) from {store.directory}")
        except ImportError:
            pass

    def _init_client(self):
        if self._client_override is not None:
            return self._client_override
        return LLMClient(self.config, tool_registry=self.tool_registry)

    def _init_conversation_manager(self):
        memory_config = self._build_memory_config()
        knowledge_config = self._build_knowledge_config()
        default_model_params = self.config.llm.get_model_params()
        memory_manager = self._init_memory_manager()
        knowledge_manager = self._init_knowledge_manager()
        return ConversationManager(
            self.client,
            self.storage,
            memory_config=memory_config,
            knowledge_config=knowledge_config,
            context_config=self.config.context.model_dump(),
            default_model_params=default_model_params,
            memory_manager=memory_manager,
            knowledge_manager=knowledge_manager,
        )

    def _init_memory_manager(self):
        """创建共享 MemoryManager (可选，取决于 config.memory.enabled)。"""
        memory_config = self._build_memory_config()
        if not memory_config.get("enabled"):
            return None
        try:
            from llm_chat.memory import MemoryManager, MemoryStorage
            from llm_chat.memory.summarizer import LLMSummarizer

            memory_storage = MemoryStorage(
                memory_config.get("storage_dir", "~/.vermilion-bird/memory")
            )
            summarizer = LLMSummarizer(self.client)
            return MemoryManager(
                storage=memory_storage,
                db_storage=self.storage,
                llm_client=self.client,
                summarizer=summarizer,
                config=memory_config,
            )
        except Exception as e:
            logger.warning(f"共享记忆系统初始化失败: {e}")
            return None

    def _init_chat_core(self):
        chat_core = ChatCore(
            client=self.client,
            conversation_manager=self.conversation_manager,
            config=self.config,
            run_manager=self.run_manager,
            capability_policy=self.capability_policy,
            action_proposals=self.action_proposals,
            grant_authorizer=self._authorize_tool_with_grant,
            action_prepare=self.prepare_action,
            action_approve=self.approve_action,
            action_reject=self.reject_action,
            graph_runtime=self.graph_runtime,
        )
        logger.info("ChatCore initialized")
        return chat_core

    def _authorize_tool_with_grant(
        self,
        run_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        capabilities,
    ) -> bool:
        run = self.run_manager.get(run_id)
        if run is None or not run.work_item_id:
            return False
        item = self.work_items.get(run.work_item_id)
        if item is None:
            return False
        return self.resource_grants.authorizes_tool(
            work_item_id=item.id,
            workflow_id=item.workflow_id,
            tool_name=tool_name,
            arguments=arguments,
            capabilities=capabilities,
            workspace=item.workspace,
        )

    def _init_service_manager(self):
        return ServiceManager()

    def _bind_skill_runtime(self) -> None:
        skill = self.client.get_skill_manager().get_skill("task_delegator")
        configure = getattr(skill, "configure_runtime", None)
        if callable(configure):
            configure(
                run_manager=self.run_manager,
                capability_policy=self.capability_policy,
                run_handlers=self.run_handlers,
            )

    def _init_health_checker(self):
        hc = get_checker()
        hc.register_checker("database", create_database_checker(self.storage))
        hc.register_checker("services", create_service_manager_checker(self.service_manager))

        # 新增健康检查
        from llm_chat.health import create_llm_checker, create_disk_checker

        hc.register_checker("llm", create_llm_checker(self.client))
        hc.register_checker("disk", create_disk_checker())

        logger.info("HealthChecker initialized with database + services + llm + disk checks")
        return hc

    def _init_scheduler(self):
        if self.config.scheduler.enabled:
            logger.info("Initializing SchedulerService...")
            from llm_chat.scheduler import SchedulerService

            try:
                self.scheduler = SchedulerService(self.config.scheduler, self.storage, self)
                logger.info(f"SchedulerService created: {self.scheduler}")

                # 注册到服务管理器
                self.service_manager.register_service(self.scheduler)
                logger.info(f"SchedulerService registered with ServiceManager")

                skill_manager = self.get_skill_manager()
                skill_manager.reload_skill("scheduler", {"scheduler": self.scheduler})
                logger.info("Scheduler skill reloaded with scheduler instance")
            except Exception as e:
                logger.error(f"Failed to initialize scheduler: {e}")
                import traceback

                traceback.print_exc()
        else:
            logger.warning("Scheduler is disabled in config")

    def _build_memory_config(self) -> Dict[str, Any]:
        if not self.config.memory.enabled:
            return {"enabled": False}

        return {
            "enabled": True,
            "storage_dir": self.config.memory.storage_dir,
            "short_term": {"max_items": self.config.memory.short_term.max_items},
            "mid_term": {
                "max_days": self.config.memory.mid_term.max_days,
                "compress_after_days": self.config.memory.mid_term.compress_after_days,
            },
            "long_term": {
                "auto_evolve": self.config.memory.long_term.auto_evolve,
                "evolve_interval_days": self.config.memory.long_term.evolve_interval_days,
                "consolidate_min_facts": self.config.memory.long_term.consolidate_min_facts,
                "consolidate_interval_secs": self.config.memory.long_term.consolidate_interval_secs,
            },
            "exclude_patterns": self.config.memory.exclude_patterns,
            "extraction_interval": self.config.memory.extraction_interval,
            "extraction_time_interval": self.config.memory.extraction_time_interval,
            "short_term_max_entries": self.config.memory.short_term_max_entries,
            "max_memory_tokens": self.config.memory.max_memory_tokens,
            "heavy_op_min_interval_secs": self.config.memory.heavy_op_min_interval_secs,
        }

    def _build_knowledge_config(self) -> Dict[str, Any]:
        """构建领域知识系统配置字典。"""
        kc = self.config.knowledge
        if not kc.enabled:
            return {"enabled": False}
        return {
            "enabled": True,
            "storage_dir": kc.storage_dir,
            "max_knowledge_tokens": kc.max_knowledge_tokens,
            "extraction_interval": kc.extraction_interval,
            "consolidate_min_entries": kc.consolidate_min_entries,
            "refine_min_total": kc.refine_min_total,
            "semantic_enabled": kc.semantic_enabled,
            "semantic_threshold": kc.semantic_threshold,
        }

    def _init_knowledge_manager(self):
        """创建共享 KnowledgeManager (可选，取决于 config.knowledge.enabled)。"""
        knowledge_config = self._build_knowledge_config()
        if not knowledge_config.get("enabled"):
            return None
        try:
            from llm_chat.knowledge import KnowledgeManager, KnowledgeStorage
            from llm_chat.memory.summarizer import LLMSummarizer

            knowledge_storage = KnowledgeStorage(
                knowledge_config.get("storage_dir", "~/.vermilion-bird/knowledge")
            )
            # 注入共享存储实例到 skill 模块，确保 LLM 工具和 pipeline 使用同一实例
            try:
                from llm_chat.skills.knowledge_base.skill import set_storage

                set_storage(knowledge_storage)
            except Exception:
                pass  # skill 未加载时静默跳过
            summarizer = LLMSummarizer(self.client)
            return KnowledgeManager(
                storage=knowledge_storage,
                summarizer=summarizer,
                config=knowledge_config,
            )
        except Exception as e:
            logger.warning(f"领域知识系统初始化失败: {e}")
            return None

    def _init_prompt_skills(self):
        """发现并初始化 Prompt Skills (Agent Skills 标准)。

        搜索目录:
        1. ~/.vermilion-bird/skills/
        2. ~/.agents/skills/ (用户全局)
        3. .agents/skills/ (当前目录)
        4. config.yaml 中 prompt_skill_dirs 配置
        """
        from llm_chat.skills.prompt_skill import PromptSkill

        skill_manager = self.get_skill_manager()

        # 默认目录
        home = Path.home()
        default_dirs = [
            str(home / ".vermilion-bird" / "skills"),
            str(home / ".agents" / "skills"),
            str(Path.cwd() / ".agents" / "skills"),
        ]

        # 配置文件额外目录（prompt_skill_dirs 在 Config 上始终存在）
        extra = self.config.prompt_skill_dirs or []

        for d in default_dirs + extra:
            skill_manager.add_prompt_skill_dir(d)

        discovered = skill_manager.discover_prompt_skills()
        if discovered:
            # 注册 activate_skill 工具（Agent Skills 标准方案 B）
            skill_manager.register_activate_skill_tool()
            context = skill_manager.get_prompt_skills_for_context()
            self.chat_core.set_prompt_skills_context(context)
            logger.info(
                f"Prompt skills loaded: {len(discovered)} found, " f"context={len(context)} chars"
            )
        else:
            logger.debug("No prompt skills found")

    def get_skill_manager(self) -> SkillManager:
        return self.client.get_skill_manager()

    def refresh_client_config(self):
        """Refresh LLMClient protocol/session after model switch.

        Call after config.llm.model / base_url / api_key / protocol changes.
        """
        self.client.reconfigure()
        logger.info("Client config refreshed")

    def reload_skills_from_config(self):
        """Reload config from file and re-initialize all skills.

        Called after the skills dialog saves config.yaml changes.
        Unloads all skills, re-reads config, and loads skills per new config.
        Preserves MCP tools by re-enabling tools after skill reload.
        """
        new_config = Config.from_yaml()
        self.config = new_config
        self.client.config = new_config
        self.client.reconfigure()  # 重建 protocol 以使用新模型/base_url
        self.client._setup_skills()
        self._bind_skill_runtime()
        # Re-enable MCP tools (wiped by _setup_skills → tool_registry.clear())
        if self._tools_enabled:
            self._tools_enabled = False
            self.enable_tools()
        # Re-discover prompt skills (may have changed in config)
        self._init_prompt_skills()
        logger.info("Skills reloaded from config.yaml")

    def get_scheduler(self) -> Optional["SchedulerService"]:
        if self.scheduler is None and self.config.scheduler.enabled:
            self._init_scheduler()
        return self.scheduler

    def get_health(self) -> Dict[str, Any]:
        """获取系统健康状态"""
        return self._health_checker.get_summary()

    def _get_mcp_manager(self):
        if self._mcp_manager is None:
            from llm_chat.mcp import MCPManager

            self._mcp_manager = MCPManager()
            MCPManager.set_instance(self._mcp_manager)
            new_servers = []
            for server in self.config.mcp.servers:
                server_dict = server.model_dump()
                if server_dict.get("http_proxy") is None:
                    server_dict["http_proxy"] = self.config.llm.http_proxy
                if server_dict.get("https_proxy") is None:
                    server_dict["https_proxy"] = self.config.llm.https_proxy
                new_server = type(server)(**server_dict)
                new_servers.append(new_server)

            self.config.mcp.servers = new_servers
            self._mcp_manager.load_config(self.config.mcp)
        return self._mcp_manager

    # ------------------------------------------------------------------
    # ChatCore 便捷访问 (供前端直接使用)
    # ------------------------------------------------------------------

    def get_chat_core(self) -> ChatCore:
        """获取核心对话引擎。GUI/飞书等前端通过它进行 LLM 对话处理。"""
        return self.chat_core

    # ------------------------------------------------------------------
    # MCP 工具管理 (App 负责 MCP 连接; ChatCore 共享同一个 client)
    # ------------------------------------------------------------------

    def enable_tools(self, background: bool = True):
        """连接 MCP 服务器并注册工具。

        Args:
            background: 如果为 True，在后台线程中执行连接，避免阻塞 UI。
                       默认为 True。
        """
        if self._tools_enabled:
            return

        # 防止重复连接
        if getattr(self, "_mcp_connecting", False):
            logger.info("MCP connection already in progress, skipping")
            return
        self._mcp_connecting = True

        manager = self._get_mcp_manager()

        enabled_servers = self.config.mcp.get_enabled_servers()
        logger.info(f"准备连接 {len(enabled_servers)} 个 MCP 服务器: {[s.name for s in enabled_servers]}")

        if background:
            import threading

            thread = threading.Thread(
                target=self._connect_mcp_background,
                args=(manager,),
                name="mcp-connect",
                daemon=True,
            )
            thread.start()
            logger.info("MCP 连接已在后台线程启动")
        else:
            self._connect_mcp_sync(manager)

    def _connect_mcp_sync(self, manager):
        """同步连接 MCP 服务器并注册工具。"""
        try:
            future = manager.connect_all()
            results = future.result(timeout=120)
            logger.info(f"MCP 连接结果 (同步): {results}")
            self._register_mcp_tools(manager)
            self._register_mcp_health_check(manager)
        except Exception as e:
            logger.error(f"MCP 连接失败: {e}", exc_info=True)
        finally:
            self._tools_enabled = True
            self._mcp_connecting = False

    def _connect_mcp_background(self, manager):
        """后台线程中连接 MCP 并通知前端。"""
        try:
            future = manager.connect_all()
            results = future.result(timeout=120)
            logger.info(f"MCP 连接结果 (后台): {results}")
            self._register_mcp_tools(manager)
            self._register_mcp_health_check(manager)

            # 通知前端 MCP 工具已就绪
            if self.current_frontend:
                try:
                    tool_names = [t.name for t in manager.get_all_tools()]
                    self.current_frontend.display_info(
                        f"MCP 工具已就绪: {', '.join(tool_names) if tool_names else '无'}"
                    )
                except Exception:
                    logger.debug("display_info failed during MCP connect", exc_info=True)
        except Exception as e:
            logger.error(f"MCP 连接失败: {e}", exc_info=True)
            if self.current_frontend:
                try:
                    self.current_frontend.display_error(f"MCP 连接失败: {e}")
                except Exception:
                    logger.debug("display_error failed during MCP connect", exc_info=True)
        finally:
            self._tools_enabled = True
            self._mcp_connecting = False

    def _register_mcp_tools(self, manager):
        """将 MCP 工具注册到 ToolRegistry。"""
        from llm_chat.mcp.manager import MCPToolAdapter

        connected_tools = manager.get_tools_for_openai()
        logger.info(f"MCP 工具加载完成，共 {len(connected_tools)} 个工具")
        if connected_tools:
            logger.info(f"MCP 工具列表: {[t['function']['name'] for t in connected_tools]}")
            for mcp_tool in manager.get_all_tools():
                adapter = MCPToolAdapter(
                    tool_name=mcp_tool.name,
                    description=mcp_tool.description or "",
                    input_schema=mcp_tool.input_schema or {},
                    executor=lambda name, args, mgr=manager: mgr.call_tool(name, args),
                )
                self.tool_registry.register(adapter)
            logger.info(f"MCP 工具已注册到 ToolRegistry: " f"{[t.name for t in manager.get_all_tools()]}")

    def _register_mcp_health_check(self, manager):
        """注册 MCP 健康检查到 HealthChecker。"""
        from llm_chat.health import create_mcp_checker, get_checker

        hc = get_checker()
        hc.register_checker("mcp", create_mcp_checker(manager))
        logger.info("MCP health checker registered")

    def disable_tools(self):
        if not self._tools_enabled:
            return

        # 先从 ToolRegistry 移除 MCP 工具
        if self._mcp_manager:
            for mcp_tool in self._mcp_manager.get_all_tools():
                self.tool_registry.unregister(mcp_tool.name)

            future = self._mcp_manager.disconnect_all()
            try:
                future.result(timeout=10)
                logger.info("工具已禁用，MCP 连接已断开")
            except Exception as e:
                logger.warning(f"断开 MCP 连接时出错: {e}")

        self._tools_enabled = False

    def get_available_tools(self) -> List[Dict[str, Any]]:
        tools = []

        builtin_tools = self.client.get_builtin_tools()
        # MCP 工具已通过 MCPToolAdapter 注册到 ToolRegistry,
        # get_builtin_tools() 已包含 MCP 工具，无需重复添加
        tools.extend(builtin_tools)

        return tools

    def has_tools_available(self) -> bool:
        return self.client.has_builtin_tools() or self._tools_enabled

    def get_conversation(self, conversation_id: str) -> Conversation:
        return self.conversation_manager.get_conversation(conversation_id)

    def set_frontend(self, frontend: BaseFrontend):
        self.current_frontend = frontend

        # 注入依赖到前端
        if hasattr(frontend, "set_storage"):
            frontend.set_storage(self.storage)
        if hasattr(frontend, "set_config"):
            frontend.set_config(self.config)
        if hasattr(frontend, "set_app"):
            frontend.set_app(self)
        if hasattr(frontend, "set_chat_core"):
            frontend.set_chat_core(self.chat_core)

        frontend.set_conversation_callbacks(
            on_new=self._on_new_conversation,
            on_delete=self._on_delete_conversation,
            on_rename=self._on_rename_conversation,
            on_switch=self._on_switch_conversation,
            on_list=self._on_list_conversations,
        )

        # 统一的消息处理回调 — 委托给 ChatCore（CLI/简单前端使用此路径）
        def handle_message(message: Message, ctx: ConversationContext):
            try:

                def on_card(card):
                    frontend.display_card(card)

                response = self.chat_core.send_message(
                    conversation_id=ctx.conversation_id,
                    message=message.content,
                    on_card=on_card,
                )
                response_msg = Message(
                    content=response, role="assistant", msg_type=MessageType.TEXT
                )
                frontend.display_message(response_msg)
            except Exception as e:
                frontend.display_error(str(e))

        def handle_clear(ctx: ConversationContext):
            conversation = self.get_conversation(ctx.conversation_id)
            conversation.clear_history()
            frontend.display_info("对话历史已清空")

        def handle_exit():
            self.stop()

        frontend.set_on_message(handle_message)
        frontend.set_on_clear(handle_clear)
        frontend.set_on_exit(handle_exit)

    def _on_new_conversation(self):
        if self.current_frontend.is_current_conversation_empty():
            convs = self.conversation_manager.list_conversations()
            if convs:
                return

        conv = self.conversation_manager.create_conversation()
        self._current_conversation_id = conv.conversation_id
        self.current_frontend.set_current_conversation(conv.conversation_id, [])
        self.current_frontend.request_conversation_list_refresh()

    def _on_delete_conversation(self, conversation_id: str):
        if conversation_id == self._current_conversation_id:
            conversations = self.conversation_manager.list_conversations()
            if conversations:
                next_conv = conversations[0]
                self._current_conversation_id = next_conv.get("id")
                messages = self.storage.get_messages(self._current_conversation_id)
                self.current_frontend.set_current_conversation(
                    self._current_conversation_id, messages
                )
            else:
                self._on_new_conversation()
                return

        self.conversation_manager.delete_conversation(conversation_id)
        self.current_frontend.request_conversation_list_refresh()

    def _on_rename_conversation(self, conversation_id: str):
        conv = self.storage.get_conversation(conversation_id)
        current_title = conv.get("title", "") if conv else ""

        new_title = self.current_frontend.request_rename_input(conversation_id, current_title)

        if new_title:
            self.storage.update_conversation(conversation_id, title=new_title)
            self.current_frontend.request_conversation_list_refresh()

    def _on_switch_conversation(self, conversation_id: str):
        self._current_conversation_id = conversation_id
        messages = self.storage.get_messages(conversation_id)
        self.current_frontend.set_current_conversation(conversation_id, messages)

    def _on_list_conversations(self):
        conversations = self.conversation_manager.list_conversations()
        self.current_frontend.update_conversation_list(conversations)

    def run(self, frontend: BaseFrontend):
        import signal

        # 注册信号处理器：Ctrl+C / SIGTERM 强制退出
        def _force_exit(signum, frame):
            logger.warning(f"Received signal {signum}, forcing exit...")
            self.stop()
            import os as _os

            _os._exit(0)

        signal.signal(signal.SIGINT, _force_exit)
        signal.signal(signal.SIGTERM, _force_exit)

        self.set_frontend(frontend)

        # ── 快速初始化（在窗口显示前完成） ──
        self.storage.migrate_from_json()

        conversations = self.conversation_manager.list_conversations()
        if conversations:
            self._current_conversation_id = conversations[0].get("id")
            messages = self.storage.get_messages(self._current_conversation_id)
            frontend.set_current_conversation(self._current_conversation_id, messages)
        else:
            # 无对话时创建默认对话
            self._on_new_conversation()

        # ── 先显示窗口，后台初始化（MCP / Scheduler）延后执行 ──
        try:
            frontend.start(post_init=self._start_background_services)
        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            if self.current_frontend:
                self.current_frontend.display_error(str(e))
            raise

    def _start_background_services(self):
        """窗口显示后异步执行的后台初始化。"""
        logger.info("开始后台服务初始化...")
        # Scheduler 初始化（含 APScheduler 启动，~2s）
        if self.scheduler is None:
            self._init_scheduler()
        if self.config.enable_tools:
            if self.config.mcp.servers:
                self.enable_tools()
        # 异步启动 Docker 沙箱（不阻塞界面）
        self._start_docker_sandbox_async()
        self.service_manager.start_all()
        self.run_recovery.start_async()
        # 调度器启动后注册主动聊天任务（add_job 在 start 之后才能持久化到 apscheduler_jobs 表）
        self._register_proactive_chat_task()
        if self.current_frontend:
            self.current_frontend.display_info("服务就绪")
        logger.info("后台服务初始化完成")

    def _register_proactive_chat_task(self):
        """注册内置定时任务：每日新闻精选 + 每日话题。幂等：已存在则跳过。"""
        if not self.scheduler or not self.config.scheduler.enabled:
            return
        if not self.config.scheduler.proactive_enabled:
            logger.info("主动聊天已禁用")
            return

        from llm_chat.scheduler.models import Task, TaskType
        from datetime import datetime
        import uuid

        tasks_to_register = [
            {
                "job_id": "proactive-digest",
                "name": "每日新闻精选",
                "hour": 8,
                "minute": 50,
                "message": self._build_digest_prompt(),
            },
            {
                "job_id": "proactive-daily",
                "name": "每日话题",
                "hour": 9,
                "minute": 0,
                "message": self._build_discussion_prompt(),
            },
        ]

        for cfg in tasks_to_register:
            job_id = cfg["job_id"]
            name = cfg["name"]
            hour = cfg["hour"]
            minute = cfg["minute"]

            existing = [
                t for t in self._get_tasks_by_type("PROACTIVE_CHAT") if t.id.startswith(job_id)
            ]
            if not existing:
                existing = [
                    t for t in self._get_tasks_by_type("LLM_CHAT") if t.id.startswith(job_id)
                ]
            if existing:
                task = existing[0]
                try:
                    job = self.scheduler._scheduler.get_job(task.id)
                    if job:
                        logger.info(f"{name} 已存在: {task.id}")
                        if task.task_type == TaskType.LLM_CHAT:
                            task.task_type = TaskType.PROACTIVE_CHAT
                            self.storage.save_task(task)
                            logger.info(f"{name} 已升级为 PROACTIVE_CHAT")
                        continue
                    else:
                        logger.warning(f"{name} job 丢失，重新注册: {task.id}")
                        self.storage.delete_task(task.id)
                except Exception as e:
                    logger.warning(f"检查 {name} job 失败: {e}")

            task = Task(
                id=f"{job_id}-{uuid.uuid4().hex[:8]}",
                name=name,
                task_type=TaskType.PROACTIVE_CHAT,
                trigger_config={
                    "cron": f"{minute} {hour} * * *",
                    "timezone": "Asia/Shanghai",
                },
                params={"message": cfg["message"]},
                enabled=True,
                max_retries=1,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                notify_enabled=True,
            )
            self.scheduler.add_task(task)
            logger.info(f"已注册 {name} (每天 {hour:02d}:{minute:02d}): {task.id}")

    def _build_digest_prompt(self) -> str:
        """每日新闻精选 prompt — 搜新闻，输出精选文本（不用卡片）。"""
        return """你现在是新闻编辑。按以下步骤完成新闻精选：

1. 调用 fetch_rss 获取 RSS 订阅的最新文章
2. 按星期轮换主题，调用 web_search 搜索补充资讯：
   - 周一: 商业趋势、新兴行业、商业模式
   - 周二: 科学发现、太空探索、生物学突破
   - 周三: 艺术展览、设计趋势、文学新书
   - 周四: 社会现象分析、生活方式变化、教育改革
   - 周五: 效率方法论、认知升级、技能学习
   - 周六: 旅行目的地、美食文化、户外运动
   - 周日: 哲学思想、幸福感研究、AI伦理
   （每类主题搜 3 个关键词）
3. 同时搜索用户记忆中的兴趣领域最新进展
4. 从全部资讯中精选 8-12 条最有价值的

输出格式（严格用 Markdown）：

# 📰 今日精选 · X月X日

**1. 🔖 [标题](链接)**
> 来源：xxx · 摘要：xxx (≤50字)
> 💡 为什么选：xxx

**2. 🔖 [标题](链接)**
> ...

要求：
- 严格输出 **10 条**，宁多勿少，不得少于 8 条
- 标题用 Markdown 链接格式 [标题](URL)
- 每条用引用块（>）包裹
- 用数字加粗序号
- 不要输出 JSON，不要输出额外解释"""

    def _build_discussion_prompt(self) -> str:
        """每日话题 prompt — 读精选 + 记忆 → 生成话题卡片。"""
        return """你是一个消息灵通的AI伙伴。每天你会从今天的新闻精选中找出值得和用户讨论的话题。

注意：今天早些时候已生成「每日新闻精选」文本，你可以在对话历史中看到它。
如果不可用，调用 web_search 搜索今日热点。

步骤：
1. 回顾今日新闻精选（如果有的话）
2. 结合用户记忆中的兴趣和背景
3. 提取 2-3 个最值得讨论的方向
4. 使用 submit_decision_card 生成话题建议卡

卡片要求：
- title: 有新闻感的标题（含 emoji）
- context: 一句话说明为什么有意思
- options: 2-3 个方向，id 自动 A/B/C，description ≤30字

选题原则：
1. 借势资讯为主
2. 连接记忆
3. 出其不意
4. 言之有物

禁区：不要问"今天怎么样"，不要讲大道理。如果没找到合适的新闻就说一声。"""

    def _get_tasks_by_type(self, task_type: str) -> list:
        """按类型查询任务列表。"""
        try:
            from llm_chat.scheduler.models import TaskType

            all_tasks = self.storage.load_all_tasks()
            return [t for t in all_tasks if t.task_type.value == task_type]
        except Exception:
            return []

    def _start_docker_sandbox_async(self):
        """后台线程中异步启动 Docker 沙箱。"""
        try:
            skill_manager = self.get_skill_manager()
            shell_skill = skill_manager.get_skill("shell_exec")
            if shell_skill and hasattr(shell_skill, "start_sandbox_async"):
                shell_skill.start_sandbox_async()
        except Exception as e:
            logger.warning(f"异步启动 Docker 沙箱失败: {e}")

    def stop(self):
        self.work_items.close()
        # 使用服务管理器停止所有服务
        self.service_manager.stop_all()
        self.disable_tools()
        # 关闭 MCP 事件循环
        if self._mcp_manager:
            self._mcp_manager.shutdown()
        # 释放 HTTP 会话
        if self.client:
            self.client.close()
        if self.graph_runtime:
            self.graph_runtime.close()
            self.graph_runtime = None
            self.graph_execution = None
            self._action_coordinator = None
        if self.current_frontend:
            self.current_frontend.stop()
