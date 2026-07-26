"""CLI commands for managing Ghost profiles."""

import os
import shlex
import sys
import click
import logging

logger = logging.getLogger(__name__)


@click.group(name="ghost")
def ghost_group():
    """管理 Ghost 智能体模板

    Ghost 是可复用的 Agent 配置文件 (YAML)。
    定义好 Ghost 后，在对话中通过 spawn_subagent(ghost="name") 引用。
    """
    pass


@ghost_group.command("list")
def ghost_list():
    """列出所有 Ghost 模板"""
    from llm_chat.ghost.store import get_ghost_store

    store = get_ghost_store()
    keys = store.list_all()

    if not keys:
        click.echo("暂无 Ghost 模板。")
        click.echo(f"模板目录: {store.directory}")
        click.echo("\n创建方法: vermilion-bird ghost create <name>")
        return

    click.echo(f"Ghost 模板 ({len(keys)} 个):")
    click.echo("=" * 60)
    for key in keys:
        ghost = store.get_cached(key)
        if ghost:
            tools_str = ", ".join(ghost.tools) if ghost.tools else "无"
            model_str = ghost.model or "默认"
            desc = ghost.description[:60] if ghost.description else "(无描述)"
            click.echo(f"  {key}")
            click.echo(f"    名称: {ghost.name}")
            click.echo(f"    描述: {desc}")
            click.echo(f"    模型: {model_str}")
            click.echo(f"    工具: {tools_str}")
            click.echo()


@ghost_group.command("show")
@click.argument("name")
def ghost_show(name):
    """查看指定 Ghost 的完整内容"""
    from llm_chat.ghost.store import get_ghost_store

    store = get_ghost_store()
    ghost = store.load(name)

    if not ghost:
        click.echo(f"错误: Ghost '{name}' 不存在", err=True)
        click.echo(f"可用: {', '.join(store.list_all()) or '(无)'}")
        sys.exit(1)

    click.echo(f"Ghost: {name}")
    click.echo("=" * 60)
    click.echo(f"名称:        {ghost.name}")
    click.echo(f"描述:        {ghost.description or '(无)'}")
    click.echo(f"模型:        {ghost.model or '默认'}")
    click.echo(f"复杂度:      {ghost.complexity or '默认'}")
    click.echo(f"工具:        {', '.join(ghost.tools) if ghost.tools else '(无)'}")
    click.echo(f"技能:        {', '.join(ghost.skills) if ghost.skills else '(无)'}")
    if ghost.metadata:
        click.echo(f"元数据:      {ghost.metadata}")
    click.echo()
    click.echo("--- system_prompt ---")
    click.echo(ghost.system_prompt)


@ghost_group.command("create")
@click.argument("name")
@click.option("--display-name", default=None, help="显示名称（默认使用 filename）")
@click.option("--description", default=None, help="简要描述")
@click.option("--model", default=None, help="默认模型")
@click.option("--tools", default=None, help="工具列表，逗号分隔，如 'web_search,web_fetch,file_writer'")
@click.option("--skills", default=None, help="技能列表，逗号分隔")
@click.option(
    "--complexity", type=click.Choice(["simple", "moderate", "complex"]), default=None, help="复杂度"
)
@click.option("--prompt-file", default=None, help="从文件读取 system_prompt")
@click.option("--editor", is_flag=True, help="使用 $EDITOR 编辑 system_prompt")
def ghost_create(
    name, display_name, description, model, tools, skills, complexity, prompt_file, editor
):
    """创建新的 Ghost 模板

    \b
    示例:
      vermilion-bird ghost create researcher --description "深度研究员" --tools "web_search,web_fetch"

    如果不指定 --prompt-file 或 --editor，将从 stdin 读取 system_prompt。
    """
    from llm_chat.ghost.schema import GhostConfig
    from llm_chat.ghost.store import get_ghost_store

    store = get_ghost_store()

    if store.load(name):
        click.echo(f"错误: Ghost '{name}' 已存在。使用 'ghost edit {name}' 修改", err=True)
        sys.exit(1)

    # Get system_prompt
    if prompt_file:
        with open(prompt_file, "r", encoding="utf-8") as f:
            system_prompt = f.read()
    elif editor:
        system_prompt = _edit_in_editor("")
    else:
        click.echo("请输入 system_prompt (Ctrl+D 结束):")
        lines = []
        try:
            while True:
                line = input()
                lines.append(line)
        except EOFError:
            pass
        system_prompt = "\n".join(lines)

    if not system_prompt.strip():
        click.echo("错误: system_prompt 不能为空", err=True)
        sys.exit(1)

    ghost = GhostConfig(
        name=display_name or name,
        description=description or "",
        system_prompt=system_prompt,
        tools=[t.strip() for t in tools.split(",") if t.strip()] if tools else [],
        model=model,
        skills=[s.strip() for s in skills.split(",") if s.strip()] if skills else [],
        complexity=complexity,
    )

    filepath = store.save(name, ghost)
    click.echo(f"✓ Ghost '{name}' 已创建: {filepath}")


@ghost_group.command("edit")
@click.argument("name")
@click.option("--editor", is_flag=True, default=True, help="使用 $EDITOR 编辑 YAML")
def ghost_edit(name, editor):
    """编辑 Ghost 的 YAML 文件"""
    from llm_chat.ghost.store import get_ghost_store

    store = get_ghost_store()
    ghost = store.load(name)

    if not ghost:
        click.echo(f"错误: Ghost '{name}' 不存在", err=True)
        sys.exit(1)

    filepath = store.directory / f"{name}.yaml"

    if editor:
        _edit_in_editor(str(filepath))
        # Reload cache
        store.load(name)
        click.echo(f"✓ Ghost '{name}' 已更新")
    else:
        click.echo(f"文件: {filepath}")
        click.echo("使用 --editor 在编辑器中打开，或直接编辑 YAML 文件")


@ghost_group.command("delete")
@click.argument("name")
@click.option("--yes", is_flag=True, help="跳过确认")
def ghost_delete(name, yes):
    """删除 Ghost 模板"""
    from llm_chat.ghost.store import get_ghost_store

    store = get_ghost_store()

    if not store.load(name):
        click.echo(f"错误: Ghost '{name}' 不存在", err=True)
        sys.exit(1)

    if not yes:
        click.confirm(f"确认删除 Ghost '{name}'?", abort=True)

    store.delete(name)
    click.echo(f"✓ Ghost '{name}' 已删除")


@ghost_group.command("import")
@click.argument("filepath", type=click.Path(exists=True))
@click.option("--name", default=None, help="Ghost 名称（默认使用文件名）")
def ghost_import(filepath, name):
    """从 YAML 文件导入 Ghost"""
    import yaml
    from llm_chat.ghost.schema import GhostConfig
    from llm_chat.ghost.store import get_ghost_store
    from pathlib import Path

    store = get_ghost_store()

    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not name:
        name = Path(filepath).stem

    if store.load(name):
        click.echo(f"错误: Ghost '{name}' 已存在", err=True)
        sys.exit(1)

    try:
        ghost = GhostConfig.from_yaml_dict(data)
    except Exception as e:
        click.echo(f"错误: YAML 格式无效 - {e}", err=True)
        sys.exit(1)

    filepath_out = store.save(name, ghost)
    click.echo(f"✓ Ghost '{name}' 已从 {filepath} 导入: {filepath_out}")


@ghost_group.command("export")
@click.argument("name")
@click.option("--output", "-o", default=None, help="输出文件路径")
def ghost_export(name, output):
    """导出 Ghost 为 YAML 文件"""
    import yaml
    from llm_chat.ghost.store import get_ghost_store

    store = get_ghost_store()
    ghost = store.load(name)

    if not ghost:
        click.echo(f"错误: Ghost '{name}' 不存在", err=True)
        sys.exit(1)

    output_path = output or f"{name}.yaml"
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(
            ghost.to_yaml_dict(),
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )

    click.echo(f"✓ Ghost '{name}' 已导出到 {output_path}")


# ── Helpers ───────────────────────────────────────────────────────


def _edit_in_editor(content_or_path: str) -> str:
    """Open content in $EDITOR (or vim/nano/notepad).

    If content_or_path is an existing file path, edit it in-place.
    Otherwise treat it as initial content for a temp file.
    """
    import tempfile
    import subprocess

    editor = shlex.split(os.environ.get("EDITOR", os.environ.get("VISUAL", "vim")))

    is_file = os.path.isfile(content_or_path)

    if is_file:
        subprocess.call([*editor, content_or_path])
        return ""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(content_or_path)
        tmp_path = f.name

    try:
        subprocess.call([*editor, tmp_path])
        with open(tmp_path, "r", encoding="utf-8") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)
