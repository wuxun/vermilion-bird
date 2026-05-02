"""CLI 技能管理命令"""

import click
import logging
from llm_chat.config import Config
from llm_chat.skills.manager import SkillManager
from llm_chat.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@click.group()
def skills():
    """技能管理"""
    pass


@skills.command(name="list")
def list_skills():
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
