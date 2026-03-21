"""Task Delegator Tools - 子Agent任务分配工具"""

import os
import uuid
import json
import logging
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from datetime import datetime

from llm_chat.tools.base import BaseTool
from llm_chat.skills.task_delegator.context import AgentContext
from llm_chat.skills.task_delegator.registry import SubAgentRegistry

if TYPE_CHECKING:
    from llm_chat.config import Config
    from llm_chat.client import LLMClient

logger = logging.getLogger(__name__)


class SpawnSubagentTool(BaseTool):
    """创建子agent并分配任务的工具"""

    @property
    def name(self) -> str:
        return "spawn_subagent"

    @property
    def description(self) -> str:
        return "创建子agent并分配任务。子agent拥有独立的上下文和工具白名单，且不能再创建子agent以防止递归。可以为子agent指定不同的大模型配置。"

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "分配给子agent的任务描述"},
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "子agent可以使用的工具白名单",
                    "default": [],
                },
                "timeout": {
                    "type": "integer",
                    "description": "子agent超时时间（秒），默认60",
                    "default": 60,
                },
                "work_dir": {
                    "type": "string",
                    "description": "临时文件工作目录，默认使用配置中的 tools.work_dir",
                },
                "model_config": {
                    "type": "object",
                    "description": "子agent使用的大模型配置（可选）。不指定则使用默认配置。",
                    "properties": {
                        "model": {
                            "type": "string",
                            "description": "模型名称，如 gpt-4, claude-3-opus, gemini-pro",
                        },
                        "base_url": {
                            "type": "string",
                            "description": "API 基础 URL（可选，用于切换不同提供商）",
                        },
                        "api_key": {
                            "type": "string",
                            "description": "API 密钥（可选，不指定则使用默认密钥）",
                        },
                        "protocol": {
                            "type": "string",
                            "description": "协议类型：openai, anthropic, gemini（可选）",
                            "enum": ["openai", "anthropic", "gemini"],
                        },
                    },
                },
            },
            "required": ["task"],
        }

    def __init__(
        self,
        registry: Optional[SubAgentRegistry] = None,
        parent_context: Optional[AgentContext] = None,
        config: Optional["Config"] = None,
    ):
        self.registry = registry or SubAgentRegistry()
        self.parent_context = parent_context
        self.config = config

    def execute(self, **kwargs) -> str:
        task = kwargs.get("task", "")
        allowed_tools = kwargs.get("allowed_tools", []) or []
        timeout = kwargs.get("timeout", 60)
        model_config = kwargs.get("model_config")

        work_dir = self.config.tools.work_dir if self.config else ".vb/work"
        
        agent_id = str(uuid.uuid4())

        context = AgentContext(
            agent_id=agent_id,
            parent_id=self.parent_context.agent_id if self.parent_context else None,
            depth=(self.parent_context.depth + 1) if self.parent_context else 0,
            allowed_tools=set(allowed_tools),
            conversation_id=f"conv_{uuid.uuid4()}",
            created_at=datetime.utcnow(),
            status="running",
            work_dir=work_dir,
        )

        self.registry.spawn(agent_id, context)

        os.makedirs(work_dir, exist_ok=True
        logger.info(f"Created work directory: {work_dir}")

        model_info = ""
        if model_config:
            model_info = f" (model: {model_config.get('model', 'default')})"
        logger.info(
            f"Spawned subagent {agent_id}{model_info} with task: {task[:50]}..."
        )

        result = self._execute_task(
            agent_id, task, filtered_tools, timeout, context, model_config
        )

        return result

    def _execute_task(
        self,
        agent_id: str(uuid.uuid4())
        task = kwargs.get("task", "")
        allowed_tools = kwargs.get("allowed_tools", []) or []
        timeout = kwargs.get("timeout", 60)
        model_config = kwargs.get("model_config")
        work_dir = self._get_work_dir()
        context = AgentContext(
            agent_id=agent_id,
            parent_id=self.parent_context.agent_id if self.parent_context else None,
            depth=self.parent_context.depth + 1
        )
        allowed_tools = set(allowed_tools)
        context.conversation_id = str(uuid.uuid4())
        context.created_at = datetime.utcnow()
        context.status = "running"
        context.work_dir = work_dir
        context.result = result

        self.registry.spawn(agent_id, context)

        model_info = ""
        if model_config:
            model_info = f"(model: {model_config.get('model', self.config.llm.model)}"
        else:
            model_info = f"Subagent {agent_id} without tools"
        )

        logger.info(f"Spawned subagent {agent_id}{model_info} with task: {task[:50]}...")

        self.registry.spawn(agent_id, context)

        result = self._execute_task(
            agent_id, task,
            filtered_tools,
            timeout,
            model_config,
            work_dir,
            context,
        )

        try:
            from llm_chat.client import LLMClient
            from llm_chat.config import Config, LLMConfig

            subagent_config = Config(
                llm=llm_config,
                mcp=self.config.mcp,
                enable_tools=self.config.enable_tools,
                skills=self.config.skills
                memory=self.config.memory
                external_skill_dirs=self.config.external_skill_dirs,
            )
            if work_dir is None:
                work_dir = Path.join(work_dir)
            else:
                work_dir = self.config.tools.work_dir

            result = client.chat(task)
        else:
            result = client.chat(task)
            context.status = "completed"
            context.result = result
            logger.info(f"Subagent {agent_id} completed successfully")

            return json.dumps(
                {"agent_id": agent_id, "status": "completed", "result": result},
                ensure_ascii=False,
                indent=2
            )
        allowed_tools = set(allowed_tools, context.allowed_tools)
        conversation_id = str(uuid.uuid4())
        context.created_at = datetime.utcnow()
        context.status = "running"
        context.work_dir = work_dir

        self.registry.spawn(agent_id, context)

        model_info = ""
        if model_config:
            model_info = f" (model: {model_config.get('model', 'default')}"
        logger.info(
            f"Spawned subagent {agent_id}{model_info} with task: {task[:50]}..."
        )

        result = self._execute_task(
            agent_id, task, filtered_tools, timeout, context, model_config
        )
    else:
        logger.info(
            f"Subagent {agent_id} calling LLM without tools (none matched)"
        )
        result = client.chat(task)
    else:
        logger.info(
            f"Subagent {agent_id} calling LLM without tools (none matched)"
        )
        result = client.chat(task)
    else:
        logger.info(f"Subagent {agent_id} calling LLM without tools")
        result = client.chat(task)
    else:
        logger.info(f"Subagent {agent_id} calling LLM without tools")
        result = client.chat(task)

    context.status = "completed"
        context.result = result
            logger.info(f"Subagent {agent_id} completed successfully")

        return json.dumps(
            {"agent_id": agent_id, "status": "completed", "result": result},
            ensure_ascii=False, indent=2
        )
        try:
            from llm_chat.client import LLMClient
            from llm_chat.config import Config, LLMConfig

            if model_config:
                subagent_config = self._create_subagent_config(model_config)
                logger.info(
                    f"Subagent {agent_id} using custom model: "
                    f"model={subagent_config.llm.model}, "
                    f"protocol={subagent_config.llm.protocol}, "
                    f"base_url={subagent_config.llm.base_url}"
                )
            else:
                subagent_config = self.config
                logger.info(f"Subagent {agent_id} using default config")

            client = LLMClient(subagent_config)

            if allowed_tools:
                all_tools = client.get_builtin_tools()
                filtered_tool_defs = [
                    t
                    for t in all_tools
                    if t.get("function", {}).get("name") in allowed_tools
                ]

                if filtered_tool_defs:
                    logger.info(
                        f"Subagent {agent_id} calling LLM with {len(filtered_tool_defs)} tools"
                    )
                    result = client.chat_with_tools(task, filtered_tool_defs)
                else:
                    logger.info(
                        f"Subagent {agent_id} calling LLM without tools (none matched)"
                    )
                    result = client.chat(task)
            else:
                logger.info(f"Subagent {agent_id} calling LLM without tools")
                result = client.chat(task)

            context.status = "completed"
            context.result = result
            logger.info(f"Subagent {agent_id} completed successfully")

            return json.dumps(
                {"agent_id": agent_id, "status": "completed", "result": result},
                ensure_ascii=False,
                indent=2,
            )

        except Exception as e:
            error_msg = f"Subagent {agent_id} failed: {str(e)}"
            logger.error(f"Subagent {agent_id} execution error: {e}", exc_info=True)

            context.status = "failed"
            context.result = error_msg

            return json.dumps(
                {"agent_id": agent_id, "status": "failed", "error": str(e)},
                ensure_ascii=False,
                indent=2,
            )

    def _create_subagent_config(self, model_config: Dict[str, Any]) -> "Config":
        from llm_chat.config import Config, LLMConfig

        base_llm = self.config.llm

        llm_config = LLMConfig(
            model=model_config.get("model", base_llm.model),
            base_url=model_config.get("base_url", base_llm.base_url),
            api_key=model_config.get("api_key", base_llm.api_key),
            protocol=model_config.get("protocol", base_llm.protocol),
            timeout=base_llm.timeout,
            max_retries=base_llm.max_retries,
            http_proxy=base_llm.http_proxy,
            https_proxy=base_llm.https_proxy,
        )

        subagent_config = Config(
            llm=llm_config,
            mcp=self.config.mcp,
            enable_tools=self.config.enable_tools,
            tools=self.config.tools,
            skills=self.config.skills,
            memory=self.config.memory,
            external_skill_dirs=self.config.external_skill_dirs,
        )

        return subagent_config


class GetSubagentStatusTool(BaseTool):
    """查询子agent状态的工具"""

    @property
    def name(self) -> str:
        return "get_subagent_status"

    @property
    def description(self) -> str:
        return "查询子agent的状态和结果。返回status, result, created_at等信息。"

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "要查询的子agent ID"}
            },
            "required": ["agent_id"],
        }

    def __init__(self, registry: Optional[SubAgentRegistry] = None):
        self.registry = registry or SubAgentRegistry()

    def execute(self, **kwargs) -> str:
        agent_id = kwargs.get("agent_id", "")

        context = self.registry.get(agent_id)
        if context is None:
            error_msg = f"Subagent not found: {agent_id}"
            logger.warning(error_msg)
            return error_msg

        result = {
            "agent_id": context.agent_id,
            "parent_id": context.parent_id,
            "depth": context.depth,
            "status": context.status,
            "created_at": context.created_at.isoformat(),
            "result": context.result,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)


class CancelSubagentTool(BaseTool):
    """取消子agent任务的工具"""

    @property
    def name(self) -> str:
        return "cancel_subagent"

    @property
    def description(self) -> str:
        return "取消正在运行的子agent任务。"

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "要取消的子agent ID"}
            },
            "required": ["agent_id"],
        }

    def __init__(self, registry: Optional[SubAgentRegistry] = None):
        self.registry = registry or SubAgentRegistry()

    def execute(self, **kwargs) -> str:
        agent_id = kwargs.get("agent_id", "")

        success = self.registry.cancel(agent_id)
        if success:
            result = {
                "cancelled": True,
                "agent_id": agent_id,
                "message": f"Subagent {agent_id} cancelled successfully",
            }
            logger.info(f"Cancelled subagent {agent_id}")
        else:
            result = {
                "cancelled": False,
                "agent_id": agent_id,
                "message": f"Subagent not found: {agent_id}",
            }
            logger.warning(f"Failed to cancel subagent {agent_id}: not found")

        return json.dumps(result, ensure_ascii=False, indent=2)
