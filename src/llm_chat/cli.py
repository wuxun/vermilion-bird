import click
import logging
import sys
from llm_chat.config import Config
from llm_chat.app import App
from llm_chat.frontends import get_frontend


def setup_logging(level=logging.INFO, log_file: str = None):
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )


@click.command()
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
def main(base_url, model, api_key, protocol, frontend, gui, conversation_id, timeout, max_retries, no_tools, log_file, log_level):
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
        print(f"协议: {config.llm.protocol}")
        print(f"模型: {config.llm.model}")
        print(f"API URL: {config.llm.base_url}")
        print(f"工具调用: {'启用' if config.enable_tools else '禁用'}")
        print("=" * 50)
    
    frontend_instance = get_frontend(
        frontend,
        conversation_id=conversation_id or "default"
    )
    
    app.run(frontend_instance)


if __name__ == '__main__':
    main()
