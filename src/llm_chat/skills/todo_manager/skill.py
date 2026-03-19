import json
import logging
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool

logger = logging.getLogger(__name__)


class CreateTaskPlanTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
        self._tasks_file = self._base_dir / ".todo_tasks.json"
    
    @property
    def name(self) -> str:
        return "create_task_plan"
    
    @property
    def description(self) -> str:
        return "创建长周期任务计划，将任务分解为多个步骤。每个步骤包含描述、预期输出和依赖关系。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_name": {
                    "type": "string",
                    "description": "任务名称，简短描述任务目标"
                },
                "task_description": {
                    "type": "string",
                    "description": "任务详细描述，说明最终要达成的目标"
                },
                "steps": {
                    "type": "array",
                    "description": "任务步骤列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step_id": {
                                "type": "string",
                                "description": "步骤唯一标识，如 'step1', 'step2'"
                            },
                            "description": {
                                "type": "string",
                                "description": "步骤描述"
                            },
                            "expected_output": {
                                "type": "string",
                                "description": "预期输出或完成标准"
                            },
                            "dependencies": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "依赖的步骤ID列表，空数组表示无依赖"
                            }
                        },
                        "required": ["step_id", "description", "expected_output"]
                    }
                }
            },
            "required": ["task_name", "task_description", "steps"]
        }
    
    def execute(self, task_name: str, task_description: str, steps: List[Dict[str, Any]]) -> str:
        try:
            task_data = self._load_tasks()
            
            task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            formatted_steps = []
            for step in steps:
                formatted_steps.append({
                    "step_id": step.get("step_id", f"step_{len(formatted_steps)+1}"),
                    "description": step.get("description", ""),
                    "expected_output": step.get("expected_output", ""),
                    "dependencies": step.get("dependencies", []),
                    "status": "pending",
                    "progress": 0,
                    "notes": [],
                    "started_at": None,
                    "completed_at": None
                })
            
            task = {
                "task_id": task_id,
                "task_name": task_name,
                "task_description": task_description,
                "steps": formatted_steps,
                "current_step": None,
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "completed_at": None
            }
            
            task_data["tasks"].append(task)
            task_data["active_task_id"] = task_id
            self._save_tasks(task_data)
            
            logger.info(f"创建任务计划: {task_id} - {task_name}, 共 {len(steps)} 个步骤")
            
            result = f"✅ 任务计划创建成功\n\n"
            result += f"任务ID: {task_id}\n"
            result += f"任务名称: {task_name}\n"
            result += f"任务描述: {task_description}\n\n"
            result += f"步骤列表 ({len(steps)} 个步骤):\n"
            for i, step in enumerate(formatted_steps, 1):
                deps = step.get("dependencies", [])
                deps_str = f" (依赖: {', '.join(deps)})" if deps else ""
                result += f"  {i}. [{step['step_id']}] {step['description']}{deps_str}\n"
            
            return result
            
        except Exception as e:
            logger.error(f"创建任务计划失败: {e}")
            return f"❌ 创建任务计划失败: {str(e)}"
    
    def _load_tasks(self) -> Dict[str, Any]:
        if self._tasks_file.exists():
            try:
                with open(self._tasks_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return {"tasks": [], "active_task_id": None}
    
    def _save_tasks(self, data: Dict[str, Any]) -> None:
        with open(self._tasks_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


class UpdateStepProgressTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
        self._tasks_file = self._base_dir / ".todo_tasks.json"
    
    @property
    def name(self) -> str:
        return "update_step_progress"
    
    @property
    def description(self) -> str:
        return "更新任务步骤的进展，记录完成情况和备注信息。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "step_id": {
                    "type": "string",
                    "description": "要更新的步骤ID"
                },
                "progress": {
                    "type": "integer",
                    "description": "进度百分比 (0-100)",
                    "minimum": 0,
                    "maximum": 100
                },
                "note": {
                    "type": "string",
                    "description": "进展备注，记录当前工作内容或发现的问题"
                },
                "status": {
                    "type": "string",
                    "description": "步骤状态",
                    "enum": ["pending", "in_progress", "completed", "blocked"],
                    "default": "in_progress"
                }
            },
            "required": ["step_id", "progress"]
        }
    
    def execute(self, step_id: str, progress: int, note: str = "", status: str = "in_progress") -> str:
        try:
            task_data = self._load_tasks()
            
            if not task_data.get("active_task_id"):
                return "❌ 没有活动的任务，请先创建任务计划"
            
            active_task = None
            for task in task_data["tasks"]:
                if task["task_id"] == task_data["active_task_id"]:
                    active_task = task
                    break
            
            if not active_task:
                return "❌ 找不到活动任务"
            
            target_step = None
            for step in active_task["steps"]:
                if step["step_id"] == step_id:
                    target_step = step
                    break
            
            if not target_step:
                return f"❌ 找不到步骤: {step_id}"
            
            old_status = target_step["status"]
            target_step["status"] = status
            target_step["progress"] = min(100, max(0, progress))
            
            if note:
                target_step["notes"].append({
                    "time": datetime.now().isoformat(),
                    "content": note
                })
            
            if status == "in_progress" and old_status == "pending":
                target_step["started_at"] = datetime.now().isoformat()
            
            if status == "completed":
                target_step["progress"] = 100
                target_step["completed_at"] = datetime.now().isoformat()
            
            active_task["updated_at"] = datetime.now().isoformat()
            active_task["current_step"] = step_id
            
            self._save_tasks(task_data)
            
            logger.info(f"更新步骤进展: {step_id}, 进度: {progress}%, 状态: {status}")
            
            result = f"✅ 步骤进展已更新\n\n"
            result += f"步骤ID: {step_id}\n"
            result += f"状态: {status}\n"
            result += f"进度: {progress}%\n"
            if note:
                result += f"备注: {note}\n"
            
            return result
            
        except Exception as e:
            logger.error(f"更新步骤进展失败: {e}")
            return f"❌ 更新步骤进展失败: {str(e)}"
    
    def _load_tasks(self) -> Dict[str, Any]:
        if self._tasks_file.exists():
            try:
                with open(self._tasks_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return {"tasks": [], "active_task_id": None}
    
    def _save_tasks(self, data: Dict[str, Any]) -> None:
        with open(self._tasks_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


class GetTaskStatusTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
        self._tasks_file = self._base_dir / ".todo_tasks.json"
    
    @property
    def name(self) -> str:
        return "get_task_status"
    
    @property
    def description(self) -> str:
        return "获取当前任务或指定任务的完整状态，包括所有步骤的进展情况。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "任务ID，不指定则获取当前活动任务"
                }
            },
            "required": []
        }
    
    def execute(self, task_id: str = "") -> str:
        try:
            task_data = self._load_tasks()
            
            target_task_id = task_id or task_data.get("active_task_id")
            
            if not target_task_id:
                return "📋 当前没有任务\n\n使用 create_task_plan 创建新任务"
            
            target_task = None
            for task in task_data["tasks"]:
                if task["task_id"] == target_task_id:
                    target_task = task
                    break
            
            if not target_task:
                return f"❌ 找不到任务: {target_task_id}"
            
            completed_steps = sum(1 for s in target_task["steps"] if s["status"] == "completed")
            total_steps = len(target_task["steps"])
            overall_progress = sum(s["progress"] for s in target_task["steps"]) // total_steps if total_steps > 0 else 0
            
            status_emoji = {
                "pending": "⏳",
                "in_progress": "🔄",
                "completed": "✅",
                "blocked": "🚫"
            }
            
            result = f"📋 任务状态报告\n\n"
            result += f"任务ID: {target_task['task_id']}\n"
            result += f"任务名称: {target_task['task_name']}\n"
            result += f"任务描述: {target_task['task_description']}\n"
            result += f"创建时间: {target_task['created_at']}\n"
            result += f"更新时间: {target_task['updated_at']}\n\n"
            result += f"总体进度: {overall_progress}% ({completed_steps}/{total_steps} 步骤完成)\n\n"
            result += f"步骤详情:\n"
            result += "-" * 50 + "\n"
            
            for step in target_task["steps"]:
                emoji = status_emoji.get(step["status"], "❓")
                progress_bar = self._progress_bar(step["progress"])
                result += f"\n{emoji} [{step['step_id']}] {step['description']}\n"
                result += f"   进度: {progress_bar} {step['progress']}%\n"
                result += f"   状态: {step['status']}\n"
                result += f"   预期输出: {step['expected_output']}\n"
                
                if step.get("dependencies"):
                    result += f"   依赖: {', '.join(step['dependencies'])}\n"
                
                if step.get("notes"):
                    result += f"   备注:\n"
                    for n in step["notes"][-3:]:
                        result += f"     - [{n['time'][:16]}] {n['content'][:100]}\n"
            
            return result
            
        except Exception as e:
            logger.error(f"获取任务状态失败: {e}")
            return f"❌ 获取任务状态失败: {str(e)}"
    
    def _progress_bar(self, progress: int, width: int = 10) -> str:
        filled = int(width * progress / 100)
        return "█" * filled + "░" * (width - filled)
    
    def _load_tasks(self) -> Dict[str, Any]:
        if self._tasks_file.exists():
            try:
                with open(self._tasks_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return {"tasks": [], "active_task_id": None}


class GetNextStepTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
        self._tasks_file = self._base_dir / ".todo_tasks.json"
    
    @property
    def name(self) -> str:
        return "get_next_step"
    
    @property
    def description(self) -> str:
        return "获取下一步应该执行的步骤，自动检查依赖关系和当前进展。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }
    
    def execute(self) -> str:
        try:
            task_data = self._load_tasks()
            
            if not task_data.get("active_task_id"):
                return "📋 当前没有活动任务\n\n使用 create_task_plan 创建新任务"
            
            active_task = None
            for task in task_data["tasks"]:
                if task["task_id"] == task_data["active_task_id"]:
                    active_task = task
                    break
            
            if not active_task:
                return "❌ 找不到活动任务"
            
            completed_step_ids = set()
            for step in active_task["steps"]:
                if step["status"] == "completed":
                    completed_step_ids.add(step["step_id"])
            
            in_progress_steps = []
            ready_steps = []
            blocked_steps = []
            
            for step in active_task["steps"]:
                if step["status"] == "completed":
                    continue
                
                dependencies = step.get("dependencies", [])
                deps_met = all(dep in completed_step_ids for dep in dependencies)
                
                if step["status"] == "in_progress":
                    in_progress_steps.append(step)
                elif deps_met:
                    ready_steps.append(step)
                else:
                    unmet_deps = [d for d in dependencies if d not in completed_step_ids]
                    blocked_steps.append((step, unmet_deps))
            
            result = f"🔍 下一步工作分析\n\n"
            result += f"任务: {active_task['task_name']}\n\n"
            
            if active_task.get("current_step"):
                result += f"当前正在进行的步骤: {active_task['current_step']}\n\n"
            
            if in_progress_steps:
                result += f"🔄 正在进行中的步骤:\n"
                for step in in_progress_steps:
                    result += f"  - [{step['step_id']}] {step['description']} ({step['progress']}%)\n"
                result += "\n"
            
            if ready_steps:
                result += f"✅ 可以开始的步骤:\n"
                for step in ready_steps:
                    result += f"  - [{step['step_id']}] {step['description']}\n"
                    result += f"    预期输出: {step['expected_output']}\n"
                result += "\n"
                
                next_step = ready_steps[0]
                result += f"👉 建议下一步:\n"
                result += f"  步骤ID: {next_step['step_id']}\n"
                result += f"  描述: {next_step['description']}\n"
                result += f"  预期输出: {next_step['expected_output']}\n"
            
            if blocked_steps:
                result += f"\n🚫 等待依赖的步骤:\n"
                for step, unmet_deps in blocked_steps:
                    result += f"  - [{step['step_id']}] 等待: {', '.join(unmet_deps)}\n"
            
            all_completed = all(s["status"] == "completed" for s in active_task["steps"])
            if all_completed:
                result += f"\n🎉 所有步骤已完成！任务可以结束了。\n"
                result += f"使用 complete_task 标记任务完成。\n"
            
            return result
            
        except Exception as e:
            logger.error(f"获取下一步工作失败: {e}")
            return f"❌ 获取下一步工作失败: {str(e)}"
    
    def _load_tasks(self) -> Dict[str, Any]:
        if self._tasks_file.exists():
            try:
                with open(self._tasks_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return {"tasks": [], "active_task_id": None}


class CompleteStepTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
        self._tasks_file = self._base_dir / ".todo_tasks.json"
    
    @property
    def name(self) -> str:
        return "complete_step"
    
    @property
    def description(self) -> str:
        return "标记步骤为已完成，并记录完成备注。自动更新任务进度。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "step_id": {
                    "type": "string",
                    "description": "要完成的步骤ID"
                },
                "completion_note": {
                    "type": "string",
                    "description": "完成备注，记录实际产出或遇到的问题"
                },
                "actual_output": {
                    "type": "string",
                    "description": "实际输出或产出描述"
                }
            },
            "required": ["step_id"]
        }
    
    def execute(self, step_id: str, completion_note: str = "", actual_output: str = "") -> str:
        try:
            task_data = self._load_tasks()
            
            if not task_data.get("active_task_id"):
                return "❌ 没有活动的任务"
            
            active_task = None
            for task in task_data["tasks"]:
                if task["task_id"] == task_data["active_task_id"]:
                    active_task = task
                    break
            
            if not active_task:
                return "❌ 找不到活动任务"
            
            target_step = None
            for step in active_task["steps"]:
                if step["step_id"] == step_id:
                    target_step = step
                    break
            
            if not target_step:
                return f"❌ 找不到步骤: {step_id}"
            
            if target_step["status"] == "completed":
                return f"⚠️ 步骤 {step_id} 已经是完成状态"
            
            dependencies = target_step.get("dependencies", [])
            completed_step_ids = set(s["step_id"] for s in active_task["steps"] if s["status"] == "completed")
            
            unmet_deps = [d for d in dependencies if d not in completed_step_ids]
            if unmet_deps:
                return f"❌ 无法完成步骤 {step_id}，以下依赖步骤尚未完成: {', '.join(unmet_deps)}"
            
            target_step["status"] = "completed"
            target_step["progress"] = 100
            target_step["completed_at"] = datetime.now().isoformat()
            
            note_content = completion_note
            if actual_output:
                note_content = f"{completion_note}\n实际产出: {actual_output}" if note_content else f"实际产出: {actual_output}"
            
            if note_content:
                target_step["notes"].append({
                    "time": datetime.now().isoformat(),
                    "content": f"[完成] {note_content}"
                })
            
            active_task["updated_at"] = datetime.now().isoformat()
            
            completed_count = sum(1 for s in active_task["steps"] if s["status"] == "completed")
            total_count = len(active_task["steps"])
            
            if completed_count == total_count:
                active_task["status"] = "completed"
                active_task["completed_at"] = datetime.now().isoformat()
            
            self._save_tasks(task_data)
            
            logger.info(f"步骤完成: {step_id}, 任务进度: {completed_count}/{total_count}")
            
            result = f"✅ 步骤已完成\n\n"
            result += f"步骤ID: {step_id}\n"
            result += f"描述: {target_step['description']}\n"
            if completion_note:
                result += f"完成备注: {completion_note}\n"
            if actual_output:
                result += f"实际产出: {actual_output}\n"
            result += f"\n任务进度: {completed_count}/{total_count} 步骤完成\n"
            
            if completed_count == total_count:
                result += f"\n🎉 恭喜！所有步骤已完成，任务可以结束了！\n"
            else:
                remaining = total_count - completed_count
                result += f"\n还有 {remaining} 个步骤待完成，使用 get_next_step 查看下一步工作。\n"
            
            return result
            
        except Exception as e:
            logger.error(f"完成步骤失败: {e}")
            return f"❌ 完成步骤失败: {str(e)}"
    
    def _load_tasks(self) -> Dict[str, Any]:
        if self._tasks_file.exists():
            try:
                with open(self._tasks_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return {"tasks": [], "active_task_id": None}
    
    def _save_tasks(self, data: Dict[str, Any]) -> None:
        with open(self._tasks_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


class ListTasksTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
        self._tasks_file = self._base_dir / ".todo_tasks.json"
    
    @property
    def name(self) -> str:
        return "list_tasks"
    
    @property
    def description(self) -> str:
        return "列出所有任务，包括已完成和进行中的任务。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_completed": {
                    "type": "boolean",
                    "description": "是否包含已完成的任务",
                    "default": True
                }
            },
            "required": []
        }
    
    def execute(self, include_completed: bool = True) -> str:
        try:
            task_data = self._load_tasks()
            
            tasks = task_data.get("tasks", [])
            
            if not tasks:
                return "📋 暂无任务\n\n使用 create_task_plan 创建新任务"
            
            status_emoji = {
                "pending": "⏳",
                "in_progress": "🔄",
                "completed": "✅"
            }
            
            active_id = task_data.get("active_task_id")
            
            result = f"📋 任务列表 (共 {len(tasks)} 个)\n\n"
            
            for task in tasks:
                if not include_completed and task["status"] == "completed":
                    continue
                
                emoji = status_emoji.get(task["status"], "❓")
                is_active = " [当前活动]" if task["task_id"] == active_id else ""
                
                completed_steps = sum(1 for s in task["steps"] if s["status"] == "completed")
                total_steps = len(task["steps"])
                
                result += f"{emoji} {task['task_name']}{is_active}\n"
                result += f"   ID: {task['task_id']}\n"
                result += f"   进度: {completed_steps}/{total_steps} 步骤\n"
                result += f"   创建: {task['created_at'][:10]}\n\n"
            
            return result
            
        except Exception as e:
            logger.error(f"列出任务失败: {e}")
            return f"❌ 列出任务失败: {str(e)}"
    
    def _load_tasks(self) -> Dict[str, Any]:
        if self._tasks_file.exists():
            try:
                with open(self._tasks_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return {"tasks": [], "active_task_id": None}


class SwitchTaskTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
        self._tasks_file = self._base_dir / ".todo_tasks.json"
    
    @property
    def name(self) -> str:
        return "switch_task"
    
    @property
    def description(self) -> str:
        return "切换当前活动任务，用于处理多个并行任务时切换上下文。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "要切换到的任务ID"
                }
            },
            "required": ["task_id"]
        }
    
    def execute(self, task_id: str) -> str:
        try:
            task_data = self._load_tasks()
            
            target_task = None
            for task in task_data["tasks"]:
                if task["task_id"] == task_id:
                    target_task = task
                    break
            
            if not target_task:
                return f"❌ 找不到任务: {task_id}"
            
            old_active_id = task_data.get("active_task_id")
            task_data["active_task_id"] = task_id
            self._save_tasks(task_data)
            
            logger.info(f"切换活动任务: {old_active_id} -> {task_id}")
            
            result = f"✅ 已切换到任务\n\n"
            result += f"任务ID: {task_id}\n"
            result += f"任务名称: {target_task['task_name']}\n"
            result += f"状态: {target_task['status']}\n"
            
            return result
            
        except Exception as e:
            logger.error(f"切换任务失败: {e}")
            return f"❌ 切换任务失败: {str(e)}"
    
    def _load_tasks(self) -> Dict[str, Any]:
        if self._tasks_file.exists():
            try:
                with open(self._tasks_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return {"tasks": [], "active_task_id": None}
    
    def _save_tasks(self, data: Dict[str, Any]) -> None:
        with open(self._tasks_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


class TodoManagerSkill(BaseSkill):
    def __init__(self, base_dir: str = "."):
        self._base_dir = base_dir
    
    @property
    def name(self) -> str:
        return "todo_manager"
    
    @property
    def description(self) -> str:
        return "长周期任务管理能力，用于任务分解、进度跟踪和步骤管理。支持创建任务计划、更新进展、查看状态和获取下一步工作建议。"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    def get_tools(self) -> List[BaseTool]:
        return [
            CreateTaskPlanTool(self._base_dir),
            UpdateStepProgressTool(self._base_dir),
            GetTaskStatusTool(self._base_dir),
            GetNextStepTool(self._base_dir),
            CompleteStepTool(self._base_dir),
            ListTasksTool(self._base_dir),
            SwitchTaskTool(self._base_dir)
        ]
    
    def on_load(self, config: Dict[str, Any]) -> None:
        if config.get("base_dir"):
            self._base_dir = config["base_dir"]
        self.logger.info(f"TodoManagerSkill loaded with base_dir: {self._base_dir}")
