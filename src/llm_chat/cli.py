import click
from llm_chat.config import Config
from llm_chat.app import App
from llm_chat.frontends import get_frontend


@click.command()
@click.option('--base-url', help='模型 API 基础 URL')
@click.option('--model', help='模型名称')
@click.option('--api-key', help='API 密钥')
@click.option('--protocol', type=click.Choice(['openai', 'anthropic', 'gemini']), help='API 协议类型')
@click.option('--frontend', type=click.Choice(['cli', 'gui']), default='cli', help='前端类型 (cli 或 gui)')
@click.option('--conversation-id', help='对话 ID')
@click.option('--timeout', type=int, help='请求超时时间（秒）')
@click.option('--max-retries', type=int, help='最大重试次数')
def main(base_url, model, api_key, protocol, frontend, conversation_id, timeout, max_retries):
    """Vermilion Bird - 大模型对话工具"""
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
    
    app = App(config)
    
    print(f"协议: {config.llm.protocol}")
    print(f"模型: {config.llm.model}")
    print(f"API URL: {config.llm.base_url}")
    print(f"前端: {frontend}")
    print("=" * 50)
    
    frontend_instance = get_frontend(
        frontend,
        conversation_id=conversation_id or "default"
    )
    
    app.run(frontend_instance)


if __name__ == '__main__':
    main()
