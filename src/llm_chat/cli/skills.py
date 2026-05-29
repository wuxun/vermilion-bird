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


@skills.command(name="install")
@click.argument("source")
@click.option("--type", "skill_type", type=click.Choice(["prompt", "code", "auto"]), default="auto",
              help="技能类型: prompt (SKILL.md), code (skill.py), auto (自动检测)")
def install_skill(source: str, skill_type: str):
    """从 URL 或 GitHub 仓库安装技能

    SOURCE: GitHub 仓库 (owner/repo) 或完整 URL

    支持两种技能类型：
      - Prompt Skill: SKILL.md 文件，注入 system prompt
      - Code Skill:   skill.py (BaseSkill 子类)，提供工具调用

    示例:
      vermilion-bird skills install myorg/my-skill
      vermilion-bird skills install https://raw.githubusercontent.com/.../SKILL.md
      vermilion-bird skills install https://github.com/user/code-skill.git --type code
      vermilion-bird skills install ./local-skill/
    """
    from llm_chat.skills.prompt_skill import install_skill as do_install_prompt
    from llm_chat.skills.prompt_skill import install_code_skill
    import re

    # 代码 Skill: git clone
    if skill_type == "code" or (
        skill_type == "auto" and (source.endswith(".git") or "github.com" in source)
    ):
        # Convert owner/repo shorthand to full URL
        if re.match(r'^[\w.-]+/[\w.-]+$', source) and not source.startswith('http'):
            source = f"https://github.com/{source}.git"
        click.echo(f"正在安装代码 skill (git clone): {source} ...")
        result = install_code_skill(source)
        if result:
            click.echo(f"✓ 安装成功: {result}")
            click.echo(f"  路径: ~/.vermilion-bird/skills/code/{result}")
            click.echo(f"\n重启对话后生效。")
        else:
            click.echo(f"✗ 安装失败: {source}")
            click.echo("提示: 确保已安装 git，且 URL 是有效的 Git 仓库")
        return

    # Prompt Skill: 下载 SKILL.md
    click.echo(f"正在安装 prompt skill: {source} ...")
    result = do_install_prompt(source)
    if result:
        click.echo(f"✓ 安装成功: {result.name}")
        click.echo(f"  描述: {result.description}")
        click.echo(f"  路径: {result.path}")
        click.echo(f"\n重启对话后生效。")
    else:
        click.echo(f"✗ 安装失败: {source}")


@skills.command(name="uninstall")
@click.argument("skill_name")
def uninstall_skill_cmd(skill_name: str):
    """卸载已安装的技能

    SKILL_NAME: 技能名称

    示例:
      vermilion-bird skills uninstall my-skill
    """
    from llm_chat.skills.prompt_skill import uninstall_skill as do_uninstall

    click.echo(f"正在卸载: {skill_name} ...")
    if do_uninstall(skill_name):
        click.echo(f"✓ 已卸载: {skill_name}")
    else:
        click.echo(f"✗ 未找到技能: {skill_name}")


@skills.command(name="search")
@click.argument("query")
@click.option("--page", type=int, default=1, help="页码")
def search_skills_cmd(query: str, page: int):
    """搜索技能市场 (GitHub agentskills topic)

    QUERY: 搜索关键词

    示例:
      vermilion-bird skills search pdf
      vermilion-bird skills search "code review" --page 2
    """
    import json
    import urllib.request
    import urllib.parse

    # GitHub search: repos with topic "agentskills" matching query
    q = f"{query} topic:agentskills"
    params = urllib.parse.urlencode({"q": q, "sort": "stars", "order": "desc", "per_page": 10, "page": page})
    url = f"https://api.github.com/search/repositories?{params}"

    click.echo(f"搜索 GitHub agentskills: {query} (第 {page} 页)...")

    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "vermilion-bird"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            click.echo("✗ GitHub API 频率限制。请稍后再试，或设置 GITHUB_TOKEN 环境变量。")
        else:
            click.echo(f"✗ 搜索失败: HTTP {e.code}")
        return
    except Exception as e:
        click.echo(f"✗ 搜索失败: {e}")
        return

    items = data.get("items", [])
    if not items:
        click.echo("未找到匹配的技能。")
        click.echo(f"也可以浏览: https://github.com/topics/agentskills")
        return

    click.echo("=" * 60)
    for i, repo in enumerate(items, 1):
        name = repo.get("name", "?")
        desc = (repo.get("description") or "")[:100]
        stars = repo.get("stargazers_count", 0)
        owner = repo.get("owner", {}).get("login", "")
        full_name = repo.get("full_name", "")
        click.echo(f"\n{i}. {full_name}  ⭐ {stars}")
        click.echo(f"   描述: {desc}")
        click.echo(f"   安装: vermilion-bird skills install {full_name}")

    click.echo("\n" + "=" * 60)
    total = data.get("total_count", 0)
    click.echo(f"共 {total} 个结果。使用 --page N 翻页。")
    click.echo(f"浏览全部: https://github.com/topics/agentskills")


@skills.command(name="update")
@click.argument("skill_name")
def update_skill_cmd(skill_name: str):
    """更新已安装的技能

    SKILL_NAME: 技能名称

    Prompt Skill: 重新读取 SKILL.md
    Code Skill:   git pull 拉取最新版本

    示例:
      vermilion-bird skills update my-skill
    """
    from pathlib import Path
    import subprocess
    from llm_chat.skills.prompt_skill import list_installed_skills

    # 1. 尝试 Prompt Skill: 重新加载 SKILL.md
    installed = list_installed_skills()
    skill = next((s for s in installed if s.name == skill_name), None)

    if skill is not None:
        skill.load()  # re-read SKILL.md
        version = skill.manifest.version if skill.manifest else "?"
        click.echo(f"✓ Prompt skill 已刷新: {skill.name} v{version}")
        return

    # 2. 尝试 Code Skill: git pull
    code_dir = Path.home() / ".vermilion-bird" / "skills" / "code" / skill_name
    if code_dir.exists() and (code_dir / ".git").exists():
        click.echo(f"正在 git pull: {skill_name} ...")
        try:
            result = subprocess.run(
                ["git", "pull"], cwd=code_dir,
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                click.echo(f"✓ 已更新: {skill_name}")
                if result.stdout.strip():
                    click.echo(result.stdout.strip())
            else:
                click.echo(f"✗ 更新失败: {result.stderr}")
        except FileNotFoundError:
            click.echo("✗ git 未安装")
        except subprocess.TimeoutExpired:
            click.echo("✗ git pull 超时")
        return

    click.echo(f"✗ 未找到已安装的技能: {skill_name}")
