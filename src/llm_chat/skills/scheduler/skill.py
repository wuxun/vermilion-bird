"""定时任务管理技能
提供通过工具调用创建、查询、删除定时任务的能力
"""

from typing import Dict, Any, List, Optional
import logging
from datetime import datetime
from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool
from llm_chat.scheduler import TaskType, SchedulerService

logger = logging.getLogger(__name__)


class CreateScheduledTaskTool(BaseTool):
    @property
    def name(self) -> str:
        return "create_scheduled_task"

    @property
    def description(self) -> str:
        return "创建定时任务。支持Cron表达式和一次性任务，可定时执行LLM对话、技能调用或系统维护任务。创建前需要先向用户确认任务参数。"

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "任务名称，简洁明了描述任务内容",
                },
                "task_type": {
                    "type": "string",
                    "enum": ["llm_chat", "skill_execution", "system_maintenance"],
                    "description": "任务类型：llm_chat=定时调用LLM对话，skill_execution=定时执行技能/工具，system_maintenance=系统维护任务",
                },
                "trigger_type": {
                    "type": "string",
                    "enum": ["cron", "date"],
                    "description": "触发类型：cron=Cron表达式定时，date=一次性执行时间",
                },
                "trigger_value": {
                    "type": "string",
                    "description": "触发值：Cron表达式（如 '0 9 * * 1' 表示每周一早上9点），或ISO格式的时间字符串（如 '2024-01-01T10:00:00'）",
                },
                "parameters": {
                    "type": "object",
                    "description": "任务参数，根据任务类型不同而不同：\n"
                    "- llm_chat: 需要包含 'message'（对话消息）、可选 'model'（模型名称）、'model_params'（模型参数）\n"
                    "- skill_execution: 需要包含 'skill_name'（技能名称）、'tool_name'（工具名称）、'arguments'（工具参数）\n"
                    "- system_maintenance: 需要包含 'action'（维护操作：cleanup_memory/archive_sessions等）",
                },
                "description": {
                    "type": "string",
                    "description": "任务详细描述，可选",
                },
            },
            "required": [
                "name",
                "task_type",
                "trigger_type",
                "trigger_value",
                "parameters",
            ],
        }

    def __init__(self, scheduler: Optional[SchedulerService] = None):
        self._scheduler = scheduler

    def execute(
        self,
        name: str,
        task_type: str,
        trigger_type: str,
        trigger_value: str,
        parameters: Dict[str, Any],
        description: str = "",
    ) -> str:
        if self._scheduler is None:
            return "错误：调度器未初始化，无法创建定时任务"

        try:
            # 转换任务类型
            task_type_enum = TaskType(task_type)

            # 创建任务
            task = self._scheduler.add_task(
                name=name,
                task_type=task_type_enum,
                trigger_type=trigger_type,
                trigger_value=trigger_value,
                parameters=parameters,
                description=description,
            )

            return (
                f"✅ 定时任务创建成功！\n"
                f"任务ID: {task.id}\n"
                f"任务名称: {task.name}\n"
                f"任务类型: {task_type}\n"
                f"触发方式: {trigger_type} = {trigger_value}\n"
                f"下次执行: {task.next_run_time or '未安排'}"
            )

        except ValueError as e:
            return f"参数错误: {str(e)}"
        except Exception as e:
            return f"创建任务失败: {str(e)}"


class ListScheduledTasksTool(BaseTool):
    @property
    def name(self) -> str:
        return "list_scheduled_tasks"

    @property
    def description(self) -> str:
        return "查询所有定时任务列表，显示任务状态、下次执行时间等信息"

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filter_status": {
                    "type": "string",
                    "enum": ["all", "active", "paused"],
                    "description": "按状态过滤任务，默认all",
                    "default": "all",
                }
            },
        }

    def __init__(self, scheduler: Optional[SchedulerService] = None):
        self._scheduler = scheduler

    def execute(self, filter_status: str = "all") -> str:
        if self._scheduler is None:
            return "错误：调度器未初始化，无法查询任务"

        try:
            tasks = self._scheduler.get_all_tasks()

            if filter_status == "active":
                tasks = [t for t in tasks if t.status == "active"]
            elif filter_status == "paused":
                tasks = [t for t in tasks if t.status == "paused"]

            if not tasks:
                return "暂无定时任务"

            result = "📋 定时任务列表:\n"
            for i, task in enumerate(tasks, 1):
                status_icon = "✅" if task.status == "active" else "⏸️"
                next_run = (
                    task.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
                    if task.next_run_time
                    else "未安排"
                )
                result += f"\n{i}. {status_icon} {task.name} (ID: {task.id[:8]}...)\n"
                result += f"   类型: {task.task_type.value}\n"
                result += f"   下次执行: {next_run}\n"
                result += f"   状态: {task.status}\n"

            return result

        except Exception as e:
            return f"查询任务失败: {str(e)}"


class DeleteScheduledTaskTool(BaseTool):
    @property
    def name(self) -> str:
        return "delete_scheduled_task"

    @property
    def description(self) -> str:
        return "删除指定ID的定时任务"

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "要删除的任务ID",
                }
            },
            "required": ["task_id"],
        }

    def __init__(self, scheduler: Optional[SchedulerService] = None):
        self._scheduler = scheduler

    def execute(self, task_id: str) -> str:
        if self._scheduler is None:
            return "错误：调度器未初始化，无法删除任务"

        try:
            self._scheduler.delete_task(task_id)
            return f"✅ 任务 {task_id} 已删除"
        except ValueError as e:
            return f"任务不存在: {str(e)}"
        except Exception as e:
            return f"删除任务失败: {str(e)}"


class SchedulerSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "scheduler"

    @property
    def description(self) -> str:
        return "定时任务管理能力，支持创建、查询、删除定时任务，可通过自然语言配置定时执行LLM对话、技能调用和系统维护任务"

    @property
    def version(self) -> str:
        return "1.0.0"

    def __init__(self):
        super().__init__()
        self._scheduler: Optional[SchedulerService] = None

    def get_tools(self) -> List[BaseTool]:
        return [
            CreateScheduledTaskTool(self._scheduler),
            ListScheduledTasksTool(self._scheduler),
            DeleteScheduledTaskTool(self._scheduler),
        ]

    def on_load(self, config: Dict[str, Any]) -> None:
        """加载时从配置中获取scheduler实例"""
        self._scheduler = config.get("scheduler")
        self.logger.info(
            f"SchedulerSkill loaded, scheduler: {'available' if self._scheduler else 'unavailable'}"
        )
