import click
import logging
import sys
from llm_chat.config import Config
from llm_chat.app import App
from llm_chat.frontends import get_frontend
from llm_chat.memory import MemoryStorage


def setup_logging(level=logging.INFO, log_file: str = None):
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
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
    
    for name, info in stats['files'].items():
        if info['exists']:
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
@click.argument('content')
def set_soul(content):
    """设置人格设定（完整内容）"""
    storage = MemoryStorage()
    storage.save_soul(content)
    click.echo("人格设定已更新")


@memory.command()
@click.argument('section')
@click.argument('content')
def set_soul_section(section, content):
    """设置人格设定的特定章节
    
    SECTION: 章节名称 (核心特质/行为准则/沟通风格/专业能力)
    CONTENT: 章节内容
    """
    storage = MemoryStorage()
    soul = storage.load_soul()
    
    import re
    pattern = rf'(## {re.escape(section)}\n)(.*?)(?=\n##|\Z)'
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
    if click.confirm('确定要清空所有记忆吗？此操作不可恢复！'):
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
@click.option('--base-url', help='模型 API 基础 URL')
@click.option('--model', help='模型名称')
@click.option('--api-key', help='API 密钥')
@click.option('--protocol', type=click.Choice(['openai', 'anthropic', 'gemini']), help='API 协议类型')
@click.option('--frontend', type=click.Choice(['cli', 'gui']), default='cli', help='前端类型 (cli 或 gui)')
@click.option('--gui', is_flag=True, help='启动 GUI 界面 (等同于 --frontend gui)')
@click.option('--conversation-id', help='对话 ID')
@click.option('--timeout', type=int, help='请求超时时间（秒）')
@click.option('--max-retries', type=int, help='最大重试次数')
@click.option('--no-tools', is_flag=True, help='禁用工具调用')
@click.option('--log-file', default=None, help='日志文件路径')
@click.option('--log-level', type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR']), default='INFO', help='日志级别')
def chat(base_url, model, api_key, protocol, frontend, gui, conversation_id, timeout, max_retries, no_tools, log_file, log_level):
    """启动对话"""
    setup_logging(getattr(logging, log_level), log_file)
    
    config = Config()
    
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
        frontend = 'gui'
    
    app = App(config)
    
    if frontend == 'cli':
        click.echo(f"协议: {config.llm.protocol}")
        click.echo(f"模型: {config.llm.model}")
        click.echo(f"API URL: {config.llm.base_url}")
        click.echo(f"工具调用: {'启用' if config.enable_tools else '禁用'}")
        click.echo("=" * 50)
    
    frontend_instance = get_frontend(
        frontend,
        conversation_id=conversation_id or "default"
    )
    
    app.run(frontend_instance)


cli.add_command(memory)


def main():
    """主入口 - 默认启动对话"""
    import sys
    if len(sys.argv) == 1:
        sys.argv.append('chat')
    cli()


if __name__ == '__main__':
    main()
