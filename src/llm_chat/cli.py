import click
from llm_chat.config import Config
from llm_chat.client import LLMClient
from llm_chat.conversation import Conversation


@click.command()
@click.option('--base-url', help='模型 API 基础 URL')
@click.option('--model', help='模型名称')
@click.option('--api-key', help='API 密钥')
@click.option('--conversation-id', help='对话 ID')
@click.option('--timeout', type=int, help='请求超时时间（秒）')
@click.option('--max-retries', type=int, help='最大重试次数')
def main(base_url, model, api_key, conversation_id, timeout, max_retries):
    """大模型对话命令行工具"""
    # 加载配置
    config = Config()
    
    # 覆盖配置
    if base_url:
        config.llm.base_url = base_url
    if model:
        config.llm.model = model
    if api_key:
        config.llm.api_key = api_key
    if timeout:
        config.llm.timeout = timeout
    if max_retries:
        config.llm.max_retries = max_retries
    
    # 创建客户端和对话
    client = LLMClient(config)
    conversation = Conversation(client, conversation_id)
    
    # 打印欢迎信息
    print("大模型对话工具")
    print("输入 'exit' 退出，输入 'clear' 清空对话历史")
    print("=" * 50)
    
    # 交互式聊天
    while True:
        try:
            # 获取用户输入
            user_input = input("你: ")
            
            # 处理特殊命令
            if user_input.lower() == 'exit':
                print("再见！")
                break
            elif user_input.lower() == 'clear':
                conversation.clear_history()
                print("对话历史已清空")
                continue
            elif not user_input.strip():
                continue
            
            # 发送消息并获取回复
            print("AI: ", end="")
            response = conversation.send_message(user_input)
            print(response)
            print("=" * 50)
            
        except KeyboardInterrupt:
            print("\n再见！")
            break
        except Exception as e:
            print(f"错误: {e}")
            print("=" * 50)


if __name__ == '__main__':
    main()
