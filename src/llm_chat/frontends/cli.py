from llm_chat.frontends.base import BaseFrontend, Message, ConversationContext, MessageType


class CLIFrontend(BaseFrontend):
    """命令行前端"""
    
    def __init__(self, conversation_id: str = "default"):
        super().__init__("cli")
        self.conversation_id = conversation_id
        self._running = False
    
    def start(self):
        """启动命令行界面"""
        self._running = True
        
        print("Vermilion Bird - 大模型对话工具")
        print("输入 'exit' 退出，输入 'clear' 清空对话历史")
        print("=" * 50)
        
        while self._running:
            try:
                user_input = input("你: ")
                
                if not user_input.strip():
                    continue
                
                if user_input.lower() == 'exit':
                    self._handle_exit()
                    break
                elif user_input.lower() == 'clear':
                    ctx = ConversationContext(conversation_id=self.conversation_id)
                    self._handle_clear(ctx)
                    continue
                
                message = Message(
                    content=user_input,
                    role="user",
                    msg_type=MessageType.TEXT
                )
                ctx = ConversationContext(conversation_id=self.conversation_id)
                
                print("AI: ", end="", flush=True)
                self._handle_message(message, ctx)
                
            except KeyboardInterrupt:
                print("\n再见！")
                break
            except EOFError:
                break
    
    def stop(self):
        """停止命令行界面"""
        self._running = False
        print("再见！")
    
    def display_message(self, message: Message):
        """显示消息"""
        if message.role == "assistant":
            print(message.content)
            print("=" * 50)
    
    def display_error(self, error: str):
        """显示错误"""
        print(f"错误: {error}")
        print("=" * 50)
    
    def display_info(self, info: str):
        """显示信息"""
        print(info)
