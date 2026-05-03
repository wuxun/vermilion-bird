"""CLI 调度任务管理命令"""

import click
import logging
import sys
import uuid
import json
from datetime import datetime
from llm_chat.config import Config
from llm_chat.app import App
from llm_chat.scheduler.models import Task, TaskType

logger = logging.getLogger(__name__)


@click.group()
def schedule():
    """调度任务管理"""
    pass


def _get_scheduler_or_exit():
    """获取调度器实例，如果不可用则退出"""
    config = Config.from_yaml()
    if not config.scheduler.enabled:
        click.echo("调度器未启用。请在配置中设置 scheduler.enabled = true")
        sys.exit(1)

    app = App(config)
    scheduler = app.get_scheduler()
    if not scheduler:
        click.echo("无法初始化调度器")
        sys.exit(1)

    return scheduler


@schedule.command()
@click.option("--name", required=True, help="任务名称")
@click.option("--cron", help="Cron 表达式 (例如: '0 0 * * *')")
@click.option("--interval", type=int, help="间隔秒数 (例如: 3600)")
@click.option("--date", help="一次性执行时间 (格式: 'YYYY-MM-DD HH:MM:SS')")
@click.option(
    "--type",
    "task_type",
    type=click.Choice(["LLM_CHAT", "SKILL_EXECUTION", "SYSTEM_MAINTENANCE"]),
    default="LLM_CHAT",
    help="任务类型",
)
@click.option("--message", help="LLM_CHAT 类型的消息内容")
@click.option("--skill", help="SKILL_EXECUTION 类型的技能名称")
@click.option("--action", help="SYSTEM_MAINTENANCE 类型的操作名称")
@click.option("--params", help="额外参数 (JSON 格式)")
@click.option(
    "--webhook-secret",
    help="WEBHOOK 类型的密钥 (X-Webhook-Secret header 校验)",
)
def create(
    name, cron, interval, date, task_type, message, skill,
    action, params, webhook_secret,
):
    """创建调度任务

    示例:
      vermilion-bird schedule create --name "每日问候" --cron "0 9 * * *" --message "早上好！"
      vermilion-bird schedule create --name "每小时检查" --interval 3600 --message "检查系统状态"
      vermilion-bird schedule create --name "Code Review" --task-type WEBHOOK --webhook-secret my-secret \\
          --message "Review the latest git diff, check for bugs and security issues"
    """
    scheduler = _get_scheduler_or_exit()

    trigger_config = {}
    if task_type == "WEBHOOK":
        trigger_config["type"] = "webhook"
        if webhook_secret:
            trigger_config["secret"] = webhook_secret
    elif cron:
        trigger_config["cron"] = cron
    elif interval:
        trigger_config["interval"] = interval
    elif date:
        trigger_config["date"] = date
    else:
        click.echo("必须指定 --cron, --interval, --date 或使用 --task-type WEBHOOK")
        sys.exit(1)

    task_params = {}
    if task_type == "LLM_CHAT":
        if not message:
            click.echo("LLM_CHAT 类型需要 --message 参数")
            sys.exit(1)
        task_params["message"] = message
        if params:
            task_params.update(json.loads(params))
    elif task_type == "SKILL_EXECUTION":
        if not skill:
            click.echo("SKILL_EXECUTION 类型需要 --skill 参数")
            sys.exit(1)
        task_params["skill_name"] = skill
        if params:
            task_params["params"] = json.loads(params)
    elif task_type == "SYSTEM_MAINTENANCE":
        if not action:
            click.echo("SYSTEM_MAINTENANCE 类型需要 --action 参数")
            sys.exit(1)
        task_params["action"] = action
        if params:
            task_params.update(json.loads(params))
    elif task_type == "WEBHOOK":
        if not message:
            click.echo("WEBHOOK 类型需要 --message 参数 (LLM 提示词)")
            sys.exit(1)
        task_params["message"] = message
        if params:
            task_params.update(json.loads(params))

    now = datetime.now()
    task = Task(
        id=str(uuid.uuid4()),
        name=name,
        task_type=TaskType(task_type),
        trigger_config=trigger_config,
        params=task_params,
        enabled=True,
        created_at=now,
        updated_at=now,
    )

    try:
        task_id = scheduler.add_task(task)
        click.echo(f"任务已创建: {task_id}")
        click.echo(f"  名称: {name}")
        click.echo(f"  类型: {task_type}")
        click.echo(f"  触发器: {trigger_config}")
    except Exception as e:
        click.echo(f"创建任务失败: {e}")
        sys.exit(1)


@schedule.command(name="list")
def list_tasks():
    """列出所有调度任务"""
    scheduler = _get_scheduler_or_exit()

    tasks = scheduler.get_all_tasks()

    if not tasks:
        click.echo("暂无调度任务")
        return

    click.echo("=" * 70)
    click.echo("调度任务列表")
    click.echo("=" * 70)

    for task in tasks:
        status = "✓ 启用" if task.enabled else "○ 禁用"
        trigger = task.trigger_config
        trigger_str = ""
        if "cron" in trigger:
            trigger_str = f"cron: {trigger['cron']}"
        elif "interval" in trigger:
            trigger_str = f"interval: {trigger['interval']}s"
        elif "date" in trigger:
            trigger_str = f"date: {trigger['date']}"
        elif trigger.get("type") == "webhook":
            trigger_str = f"webhook (/hooks/{task.id})"

        click.echo(f"\n{status} {task.id}")
        click.echo(f"  名称: {task.name}")
        click.echo(f"  类型: {task.task_type.value}")
        click.echo(f"  触发器: {trigger_str}")
        click.echo(f"  创建: {task.created_at.strftime('%Y-%m-%d %H:%M:%S')}")

    click.echo("\n" + "=" * 70)


@schedule.command()
@click.argument("task_id")
@click.option("--yes", is_flag=True, help="跳过确认提示")
def delete(task_id, yes):
    """删除调度任务

    TASK_ID: 任务 ID
    """
    scheduler = _get_scheduler_or_exit()

    if yes or click.confirm(f"确定要删除任务 {task_id} 吗？"):
        if scheduler.remove_task(task_id):
            click.echo(f"任务已删除: {task_id}")
        else:
            click.echo(f"删除任务失败: {task_id}")


@schedule.command()
@click.argument("task_id")
def pause(task_id):
    """暂停调度任务

    TASK_ID: 任务 ID
    """
    scheduler = _get_scheduler_or_exit()

    if scheduler.pause_task(task_id):
        click.echo(f"任务已暂停: {task_id}")
    else:
        click.echo(f"暂停任务失败: {task_id}")


@schedule.command()
@click.argument("task_id")
def resume(task_id):
    """恢复调度任务

    TASK_ID: 任务 ID
    """
    scheduler = _get_scheduler_or_exit()

    if scheduler.resume_task(task_id):
        click.echo(f"任务已恢复: {task_id}")
    else:
        click.echo(f"恢复任务失败: {task_id}")


@schedule.command()
@click.argument("task_id")
def trigger(task_id):
    """手动触发任务立即执行

    TASK_ID: 任务 ID
    """
    scheduler = _get_scheduler_or_exit()

    if scheduler.trigger_task(task_id):
        click.echo(f"任务已触发: {task_id}")
    else:
        click.echo(f"触发任务失败: {task_id}")


@schedule.command(name="info")
@click.argument("task_id")
def task_info(task_id):
    """查看任务详细信息

    TASK_ID: 任务 ID
    """
    scheduler = _get_scheduler_or_exit()

    task = scheduler.get_task(task_id)
    if not task:
        click.echo(f"未找到任务: {task_id}")
        return

    click.echo("=" * 60)
    click.echo(f"任务: {task.name}")
    click.echo("=" * 60)
    click.echo(f"ID: {task.id}")
    click.echo(f"类型: {task.task_type.value}")
    click.echo(f"状态: {'启用' if task.enabled else '禁用'}")
    click.echo(f"最大重试次数: {task.max_retries}")

    trigger = task.trigger_config
    if trigger.get("type") == "webhook":
        click.echo(f"触发器: Webhook")
        # 获取 webhook 服务器信息
        webhook_info = scheduler.get_webhook_info()
        if webhook_info and webhook_info.get("running"):
            port = webhook_info.get("port", 9100)
            click.echo(f"URL: http://localhost:{port}/hooks/{task.id}")
            if trigger.get("secret"):
                click.echo(f"密钥: {'*' * len(trigger['secret'])}")
        else:
            click.echo(f"URL: (webhook 服务器未启动) /hooks/{task.id}")
    elif "cron" in trigger:
        click.echo(f"触发器: cron ({trigger['cron']})")
    elif "interval" in trigger:
        click.echo(f"触发器: interval ({trigger['interval']} 秒)")
    elif "date" in trigger:
        click.echo(f"触发器: date ({trigger['date']})")

    click.echo(f"\n参数:")
    click.echo(json.dumps(task.params, indent=2, ensure_ascii=False))

    click.echo(f"\n创建时间: {task.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    click.echo(f"更新时间: {task.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")

    click.echo("=" * 60)
