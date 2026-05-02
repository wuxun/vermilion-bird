"""CLI 记忆管理命令"""

import click
import logging
import re
from llm_chat.memory import MemoryStorage

logger = logging.getLogger(__name__)


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

    pattern = rf"(## {re.escape(section)}\n)(.*?)(?=\n##|\Z)"
    match = re.search(pattern, soul, re.DOTALL)

    if match:
        updated = soul[:match.start(2)] + content + soul[match.end(2):]
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
