import click
import logging
import sys
import uuid
from datetime import datetime
from llm_chat.config import Config
from llm_chat.app import App
from llm_chat.frontends import get_frontend
from llm_chat.frontends.feishu.server import FeishuServer
from llm_chat.scheduler.models import Task, TaskType
from llm_chat.cli import memory, skills, schedule
import signal
import threading

logger = logging.getLogger(__name__)


def setup_logging(level=logging.INFO, log_file: str = None):
    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )



# ===== 主 CLI 命令组 =====

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


@cli.command()
@click.option("--config-path", default=None, help="配置文件路径")
@click.option("--log-file", default=None, help="日志文件路径")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="日志级别",
)
def feishu(config_path, log_file, log_level):
    """启动 Feishu 服务（非阻塞，后台运行）"""
    setup_logging(getattr(logging, log_level), log_file)

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

    app = App(config=config)
    # 启用工具（包括 MCP）
    if config.enable_tools and config.mcp.servers:
        app.enable_tools()
    adapter = FeishuAdapter(
        app=app,
        app_id=feishu_cfg.app_id,
        app_secret=feishu_cfg.app_secret,
    )

    # 使用服务管理器启动所有服务
    logging.info("Starting all services...")
    app.service_manager.start_all()
    logging.info("All services started")

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
        # 使用服务管理器停止所有服务
        logging.info("Shutting down all services...")
        app.service_manager.stop_all()
        logging.info("All services shut down")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    click.echo("Feishu 服务器已启动。按 Ctrl+C 停止。")

    while not stop_event.is_set():
        stop_event.wait(timeout=1)

    click.echo("Feishu 服务器已停止。")
    sys.exit(0)


# ===== 注册子命令组 =====
cli.add_command(memory)
cli.add_command(skills)
cli.add_command(schedule)


# ===== keyring 命令 =====

@cli.group()
def keyring():
    """管理系统密钥环中的 API Key"""
    pass


@keyring.command("set")
@click.argument("username")
@click.option("--service", default="vermilion-bird", help="Keyring service name")
def keyring_set(username, service):
    """将 API Key 存储到系统密钥环"""
    from llm_chat.utils.secure_storage import store_api_key, is_keyring_available

    if not is_keyring_available():
        click.echo("错误: keyring 包未安装。请运行: pip install keyring", err=True)
        sys.exit(1)

    api_key = click.prompt("请输入 API Key", hide_input=True, confirmation_prompt=True)
    if store_api_key(username, api_key, service):
        click.echo(f"✓ API Key 已存入密钥环: {service}/{username}")
    else:
        click.echo("✗ 存储失败", err=True)
        sys.exit(1)


@keyring.command("delete")
@click.argument("username")
@click.option("--service", default="vermilion-bird", help="Keyring service name")
def keyring_delete(username, service):
    """从系统密钥环中删除 API Key"""
    from llm_chat.utils.secure_storage import delete_api_key, is_keyring_available

    if not is_keyring_available():
        click.echo("错误: keyring 包未安装。请运行: pip install keyring", err=True)
        sys.exit(1)

    if delete_api_key(username, service):
        click.echo(f"✓ API Key 已从密钥环删除: {service}/{username}")
    else:
        click.echo("✗ 删除失败（可能不存在）", err=True)
        sys.exit(1)


@keyring.command("list")
def keyring_list():
    """列出 keyring 配置说明"""
    from llm_chat.utils.secure_storage import is_keyring_available

    click.echo("Keyring API Key 管理")
    click.echo("=" * 40)
    click.echo(f"Keyring 可用: {'是' if is_keyring_available() else '否 (pip install keyring)'}")
    click.echo()
    click.echo("使用方法:")
    click.echo("  1. 存储: vermilion-bird keyring set openai")
    click.echo("  2. 在 config.yaml 中设置:")
    click.echo("     llm:")
    click.echo('       api_key: "keyring:vermilion-bird/openai"')
    click.echo("  3. 删除: vermilion-bird keyring delete openai")
    click.echo()
    click.echo("系统密钥环:")
    click.echo("  - macOS: Keychain")
    click.echo("  - Linux: Secret Service / KWallet")
    click.echo("  - Windows: Credential Manager")


# ===== 全局搜索命令

@cli.command()
@click.argument("query")
@click.option("--limit", type=int, default=10, help="返回结果数量")
@click.option("--conversation-id", default=None, help="限定对话 ID")
def search(query, limit, conversation_id):
    """全文搜索历史对话"""
    setup_logging(logging.INFO)

    config = Config.from_yaml()
    app = App(config)

    results = app.conversation_manager.search_messages(
        query, conversation_id=conversation_id, limit=limit
    )

    if not results:
        click.echo("未找到相关对话。")
        return

    click.echo(f"\n找到 {len(results)} 条相关消息:\n")
    for i, r in enumerate(results, 1):
        role = r.get("role", "unknown")
        content = r.get("content", "")[:200]
        conv_id = r.get("conversation_id", "")
        created = r.get("created_at", "")
        click.echo(f"{i}. [{role}] ({conv_id[:8]}... | {created})")
        click.echo(f"   {content}")
        click.echo()


# ===== 入口 =====

def main():
    """主入口 - 默认启动对话"""
    import sys

    if len(sys.argv) == 1:
        sys.argv.append("chat")
    cli()


if __name__ == "__main__":
    main()
