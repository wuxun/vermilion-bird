import click
import logging
import sys
import uuid
from datetime import datetime
from llm_chat.config import Config
from llm_chat.app import App
from llm_chat.frontends import get_frontend
from llm_chat.memory import MemoryStorage
from llm_chat.skills.manager import SkillManager
from llm_chat.tools.registry import ToolRegistry
from llm_chat.frontends.feishu.server import FeishuServer
from llm_chat.scheduler.models import Task, TaskType
import signal
import threading


def setup_logging(level=logging.INFO, log_file: str = None):
    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


@click.group()
def memory():
    """记忆管理系统"""
    pass


@memory.command()
def status():
    """查看记忆状态"""
    storage = MemoryStorage()
    stats = storage.get_memory_stats()

    click.echo("=" * 50)
    click.echo("记忆系统状态")
    click.echo("=" * 50)
    click.echo(f"存储目录: {stats['memory_dir']}")
    click.echo("")

    for name, info in stats["files"].items():
        if info["exists"]:
            click.echo(f"【{name}】")
            click.echo(f"  大小: {info['size_bytes']} bytes")
            click.echo(f"  行数: {info['line_count']}")
            click.echo(f"  修改: {info['modified']}")
            click.echo("")
        else:
            click.echo(f"【{name}】: 未创建")
            click.echo("")


@memory.command()
def soul():
    """查看人格设定"""
    storage = MemoryStorage()
    soul = storage.load_soul()

    if soul:
        click.echo(soul)
    else:
        click.echo("人格设定文件不存在")


@memory.command()
@click.argument("content")
def set_soul(content):
    """设置人格设定（完整内容）"""
    storage = MemoryStorage()
    storage.save_soul(content)
    click.echo("人格设定已更新")


@memory.command()
@click.argument("section")
@click.argument("content")
def set_soul_section(section, content):
    """设置人格设定的特定章节

    SECTION: 章节名称 (核心特质/行为准则/沟通风格/专业能力)
    CONTENT: 章节内容
    """
    storage = MemoryStorage()
    soul = storage.load_soul()

    import re

    pattern = rf"(## {re.escape(section)}\n)(.*?)(?=\n##|\Z)"
    match = re.search(pattern, soul, re.DOTALL)

    if match:
        updated = soul[: match.start(2)] + content + soul[match.end(2) :]
        storage.save_soul(updated)
        click.echo(f"已更新章节: {section}")
    else:
        click.echo(f"未找到章节: {section}")


@memory.command()
def short_term():
    """查看短期记忆"""
    storage = MemoryStorage()
    content = storage.load_short_term()
    click.echo(content)


@memory.command()
def mid_term():
    """查看中期记忆"""
    storage = MemoryStorage()
    content = storage.load_mid_term()
    click.echo(content)


@memory.command()
def long_term():
    """查看长期记忆"""
    storage = MemoryStorage()
    content = storage.load_long_term()
    click.echo(content)


@memory.command()
def clear():
    """清空所有记忆（危险操作）"""
    if click.confirm("确定要清空所有记忆吗？此操作不可恢复！"):
        storage = MemoryStorage()
        storage.clear_short_term()
        storage.save_mid_term("")
        storage.save_long_term("")
        click.echo("所有记忆已清空")


@memory.command()
def backup():
    """备份记忆"""
    storage = MemoryStorage()
    backup_path = storage.backup_memory()
    click.echo(f"记忆已备份到: {backup_path}")


@click.group()
def cli():
    """Vermilion Bird - 智能助手"""
    pass


@cli.command()
@click.option("--base-url", help="模型 API 基础 URL")
@click.option("--model", help="模型名称")
@click.option("--api-key", help="API 密钥")
@click.option(
    "--protocol",
    type=click.Choice(["openai", "anthropic", "gemini"]),
    help="API 协议类型",
)
@click.option(
    "--frontend",
    type=click.Choice(["cli", "gui"]),
    default="cli",
    help="前端类型 (cli 或 gui)",
)
@click.option("--gui", is_flag=True, help="启动 GUI 界面 (等同于 --frontend gui)")
@click.option("--conversation-id", help="对话 ID")
@click.option("--timeout", type=int, help="请求超时时间（秒）")
@click.option("--max-retries", type=int, help="最大重试次数")
@click.option("--no-tools", is_flag=True, help="禁用工具调用")
@click.option("--log-file", default=None, help="日志文件路径")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="日志级别",
)
def chat(
    base_url,
    model,
    api_key,
    protocol,
    frontend,
    gui,
    conversation_id,
    timeout,
    max_retries,
    no_tools,
    log_file,
    log_level,
):
    """启动对话"""
    setup_logging(getattr(logging, log_level), log_file)

    config = Config.from_yaml()

    if base_url:
        config.llm.base_url = base_url
    if model:
        config.llm.model = model
    if api_key:
        config.llm.api_key = api_key
    if protocol:
        config.llm.protocol = protocol
    if timeout:
        config.llm.timeout = timeout
    if max_retries:
        config.llm.max_retries = max_retries
    if no_tools:
        config.enable_tools = False

    if gui:
        frontend = "gui"

    app = App(config)

    if frontend == "cli":
        click.echo(f"协议: {config.llm.protocol}")
        click.echo(f"模型: {config.llm.model}")
        click.echo(f"API URL: {config.llm.base_url}")
        click.echo(f"工具调用: {'启用' if config.enable_tools else '禁用'}")
        click.echo("=" * 50)

    frontend_instance = get_frontend(
        frontend, conversation_id=conversation_id or "default"
    )

    app.run(frontend_instance)


cli.add_command(memory)


@cli.command()
@click.option("--config", "config_path", default=None, help="Feishu 配置文件路径")
def feishu(config_path=None):
    """启动 Feishu 服务（非阻塞，后台运行）"""
    import logging
    import time

    # Load Feishu configuration
    try:
        config = Config.from_yaml(config_path)
    except Exception as e:
        click.echo(f"加载 Feishu 配置失败: {e}")
        return

    feishu_cfg = getattr(config, "feishu", None)
    if not feishu_cfg or not feishu_cfg.enabled:
        click.echo(
            "Feishu 集成未开启，请在配置中开启 Feishu 并提供所需凭证（app_id/app_secret）"
        )
        return
    if not feishu_cfg.app_id or not feishu_cfg.app_secret:
        click.echo("Feishu 集成需要 app_id 与 app_secret，请在配置中设置")
        return

    # Create and start the Feishu server
    from llm_chat.frontends.feishu.adapter import FeishuAdapter
    from llm_chat.app import App

    # Create App and FeishuAdapter
    app = App(config=config)
    adapter = FeishuAdapter(
        app=app,
        app_id=feishu_cfg.app_id,
        app_secret=feishu_cfg.app_secret,
    )

    server = FeishuServer(
        app_id=feishu_cfg.app_id,
        app_secret=feishu_cfg.app_secret,
        adapter=adapter,
        tenant_key=feishu_cfg.tenant_key,
        encrypt_key=feishu_cfg.encrypt_key or "",
        verification_token=feishu_cfg.verification_token,
    )
    try:
        server.start()
    except Exception as e:
        click.echo(f"无法启动 Feishu 服务器: {e}")
        return

    stop_event = threading.Event()

    def _shutdown(signum, frame):
        logging.info("Received signal %s, shutting down FeishuServer", signum)
        stop_event.set()
        try:
            server.stop()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    click.echo("Feishu 服务器已启动。按 Ctrl+C 停止。")

    while not stop_event.is_set():
        stop_event.wait(timeout=1)

    click.echo("Feishu 服务器已停止。")
    sys.exit(0)


@click.group()
def skills():
    """技能管理"""
    pass


@skills.command()
def list():
    """列出所有可用技能"""
    from llm_chat.skills.web_search.skill import WebSearchSkill
    from llm_chat.skills.calculator.skill import CalculatorSkill
    from llm_chat.skills.web_fetch.skill import WebFetchSkill

    config = Config()
    manager = SkillManager()

    manager.register_skill_class(WebSearchSkill)
    manager.register_skill_class(CalculatorSkill)
    manager.register_skill_class(WebFetchSkill)

    if config.external_skill_dirs:
        manager.discover_skills(config.external_skill_dirs)

    click.echo("=" * 60)
    click.echo("可用技能列表")
    click.echo("=" * 60)

    all_skills = manager.get_all_skill_classes()
    loaded_skills = manager.get_loaded_skills()

    for name, skill_class in all_skills.items():
        status = "✓ 已加载" if name in loaded_skills else "○ 未加载"
        desc = (
            skill_class().description[:50]
            if len(skill_class().description) > 50
            else skill_class().description
        )
        click.echo(f"\n{status} {name}")
        click.echo(f"  描述: {desc}")
        click.echo(f"  版本: {skill_class().version}")

        tools = skill_class().get_tools()
        tool_names = [t.name for t in tools]
        click.echo(f"  工具: {', '.join(tool_names)}")

    click.echo("\n" + "=" * 60)


@skills.command()
@click.argument("skill_name")
def info(skill_name):
    """查看技能详细信息

    SKILL_NAME: 技能名称
    """
    from llm_chat.skills.web_search.skill import WebSearchSkill
    from llm_chat.skills.calculator.skill import CalculatorSkill
    from llm_chat.skills.web_fetch.skill import WebFetchSkill

    manager = SkillManager()
    manager.register_skill_class(WebSearchSkill)
    manager.register_skill_class(CalculatorSkill)
    manager.register_skill_class(WebFetchSkill)

    skill_class = manager.get_skill_class(skill_name)
    if not skill_class:
        click.echo(f"未找到技能: {skill_name}")
        return

    skill = skill_class()

    click.echo("=" * 60)
    click.echo(f"技能: {skill.name}")
    click.echo("=" * 60)
    click.echo(f"版本: {skill.version}")
    click.echo(f"描述: {skill.description}")
    click.echo(f"依赖: {', '.join(skill.dependencies) if skill.dependencies else '无'}")

    click.echo("\n工具列表:")
    for tool in skill.get_tools():
        click.echo(f"\n  【{tool.name}】")
        click.echo(f"  描述: {tool.description}")
        params = tool.get_parameters_schema()
        if params.get("properties"):
            click.echo("  参数:")
            for prop, schema in params["properties"].items():
                required = prop in params.get("required", [])
                req_mark = "*" if required else ""
                desc = schema.get("description", "")
                default = schema.get("default", "无")
                click.echo(f"    - {prop}{req_mark}: {desc} (默认: {default})")


@skills.command()
@click.argument("skill_name")
def enable(skill_name):
    """启用技能

    SKILL_NAME: 技能名称
    """
    config = Config()

    if not hasattr(config.skills, skill_name):
        click.echo(f"未知技能: {skill_name}")
        click.echo("使用 'skills list' 查看可用技能")
        return

    setattr(config.skills, skill_name, type(config.skills.__class__.__bases__[0])())
    click.echo(f"技能 {skill_name} 已启用")


@skills.command()
@click.argument("skill_name")
def disable(skill_name):
    """禁用技能

    SKILL_NAME: 技能名称
    """
    config = Config()

    if not hasattr(config.skills, skill_name):
        click.echo(f"未知技能: {skill_name}")
        click.echo("使用 'skills list' 查看可用技能")
        return

    skill_config = getattr(config.skills, skill_name)
    skill_config.enabled = False
    click.echo(f"技能 {skill_name} 已禁用")


@skills.command()
def tools():
    """列出所有已注册的工具"""
    registry = ToolRegistry()

    click.echo("=" * 60)
    click.echo("已注册工具列表")
    click.echo("=" * 60)

    all_tools = registry.get_all_tools()
    if not all_tools:
        click.echo("\n暂无已注册的工具")
        click.echo("启动对话后工具会自动加载")
    else:
        for tool in all_tools:
            click.echo(f"\n【{tool.name}】")
            click.echo(f"  描述: {tool.description[:60]}...")

    click.echo("\n" + "=" * 60)


cli.add_command(skills)


# ===== Schedule 命令组 =====
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
def create(name, cron, interval, date, task_type, message, skill, action, params):
    """创建调度任务

    示例:
      vermilion-bird schedule create --name "每日问候" --cron "0 9 * * *" --message "早上好！"
      vermilion-bird schedule create --name "每小时检查" --interval 3600 --message "检查系统状态"
    """
    scheduler = _get_scheduler_or_exit()

    trigger_config = {}
    if cron:
        trigger_config["cron"] = cron
    elif interval:
        trigger_config["interval"] = interval
    elif date:
        trigger_config["date"] = date
    else:
        click.echo("必须指定 --cron, --interval 或 --date 其中之一")
        sys.exit(1)

    task_params = {}
    if task_type == "LLM_CHAT":
        if not message:
            click.echo("LLM_CHAT 类型需要 --message 参数")
            sys.exit(1)
        task_params["message"] = message
        if params:
            import json

            task_params.update(json.loads(params))
    elif task_type == "SKILL_EXECUTION":
        if not skill:
            click.echo("SKILL_EXECUTION 类型需要 --skill 参数")
            sys.exit(1)
        task_params["skill_name"] = skill
        if params:
            import json

            task_params["params"] = json.loads(params)
    elif task_type == "SYSTEM_MAINTENANCE":
        if not action:
            click.echo("SYSTEM_MAINTENANCE 类型需要 --action 参数")
            sys.exit(1)
        task_params["action"] = action
        if params:
            import json

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


@schedule.command("list")
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


@schedule.command("info")
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
    if "cron" in trigger:
        click.echo(f"触发器: cron ({trigger['cron']})")
    elif "interval" in trigger:
        click.echo(f"触发器: interval ({trigger['interval']} 秒)")
    elif "date" in trigger:
        click.echo(f"触发器: date ({trigger['date']})")

    click.echo(f"\n参数:")
    import json

    click.echo(json.dumps(task.params, indent=2, ensure_ascii=False))

    click.echo(f"\n创建时间: {task.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    click.echo(f"更新时间: {task.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")

    click.echo("=" * 60)


cli.add_command(schedule)


def main():
    """主入口 - 默认启动对话"""
    import sys

    if len(sys.argv) == 1:
        sys.argv.append("chat")
    cli()


if __name__ == "__main__":
    main()
