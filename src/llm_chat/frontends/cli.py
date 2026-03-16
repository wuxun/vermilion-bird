from typing import Dict, Any, Optional
from llm_chat.frontends.base import BaseFrontend, Message, ConversationContext, MessageType


class CLIFrontend(BaseFrontend):
    """命令行前端"""
    
    def __init__(self, conversation_id: str = "default"):
        super().__init__("cli")
        self.conversation_id = conversation_id
        self._running = False
        self._conversation: Optional[Any] = None
        self._model_params: Dict[str, Any] = {}
    
    def set_conversation(self, conversation):
        """设置当前会话对象"""
        self._conversation = conversation
    
    def start(self):
        """启动命令行界面"""
        self._running = True
        
        print("Vermilion Bird - 大模型对话工具")
        print("输入 'exit' 退出，输入 'clear' 清空对话历史")
        print("输入 '/help' 查看更多命令")
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
                elif user_input.startswith('/'):
                    self._handle_command(user_input)
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
    
    def _handle_command(self, command: str):
        """处理斜杠命令"""
        parts = command[1:].split(maxsplit=2)
        if not parts:
            return
        
        cmd = parts[0].lower()
        
        if cmd == 'help':
            self._show_help()
        elif cmd == 'set':
            if len(parts) < 2:
                print("用法: /set <参数名> <值>")
                print("可用参数: temperature, max_tokens, top_p, reasoning")
                return
            self._handle_set_command(parts[1:])
        elif cmd == 'params':
            self._show_params()
        elif cmd == 'reset':
            self._reset_params()
        else:
            print(f"未知命令: {cmd}")
            print("输入 '/help' 查看可用命令")
    
    def _show_help(self):
        """显示帮助信息"""
        print("\n可用命令:")
        print("  /help              显示帮助信息")
        print("  /set <参数> <值>   设置模型参数")
        print("  /params            显示当前参数")
        print("  /reset             重置参数为默认值")
        print("\n可用参数:")
        print("  temperature    温度 (0-2)，控制输出随机性")
        print("  max_tokens     最大输出token数")
        print("  top_p          Top-p采样参数")
        print("  reasoning      推理深度 (low/medium/high)")
        print("")
    
    def _handle_set_command(self, parts):
        """处理 /set 命令"""
        if len(parts) < 2:
            print("用法: /set <参数名> <值>")
            return
        
        param_name = parts[0].lower()
        value_str = parts[1]
        
        try:
            if param_name == 'temperature':
                value = float(value_str)
                if not 0 <= value <= 2:
                    print("temperature 必须在 0-2 之间")
                    return
                self._model_params['temperature'] = value
                print(f"温度已设置为: {value}")
            
            elif param_name == 'max_tokens':
                value = int(value_str)
                if value <= 0:
                    print("max_tokens 必须大于 0")
                    return
                self._model_params['max_tokens'] = value
                print(f"最大token数已设置为: {value}")
            
            elif param_name == 'top_p':
                value = float(value_str)
                if not 0 <= value <= 1:
                    print("top_p 必须在 0-1 之间")
                    return
                self._model_params['top_p'] = value
                print(f"Top-p已设置为: {value}")
            
            elif param_name == 'reasoning':
                if value_str.lower() not in ['low', 'medium', 'high', 'off']:
                    print("reasoning 必须是: low, medium, high, off")
                    return
                if value_str.lower() == 'off':
                    self._model_params.pop('reasoning_effort', None)
                    print("推理模式已关闭")
                else:
                    self._model_params['reasoning_effort'] = value_str.lower()
                    print(f"推理深度已设置为: {value_str.lower()}")
            
            else:
                print(f"未知参数: {param_name}")
                print("可用参数: temperature, max_tokens, top_p, reasoning")
                return
            
            if self._conversation:
                self._conversation.set_model_params(self._model_params)
        
        except ValueError as e:
            print(f"参数值错误: {e}")
    
    def _show_params(self):
        """显示当前参数"""
        print("\n当前模型参数:")
        if self._model_params:
            for key, value in self._model_params.items():
                print(f"  {key}: {value}")
        else:
            print("  (使用默认值)")
        print("")
    
    def _reset_params(self):
        """重置参数"""
        self._model_params = {}
        if self._conversation:
            self._conversation.clear_model_params()
        print("参数已重置为默认值")
    
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
