from typing import Optional, Dict
from llm_chat.client import LLMClient
from llm_chat.config import Config
from llm_chat.conversation import Conversation
from llm_chat.frontends.base import BaseFrontend, Message, ConversationContext, MessageType


class App:
    """应用核心类
    
    协调前端和 LLM 客户端之间的交互。
    支持多种前端（CLI、GUI、Web、机器人等）。
    """
    
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.client = LLMClient(self.config)
        self.conversations: Dict[str, Conversation] = {}
        self.current_frontend: Optional[BaseFrontend] = None
    
    def get_conversation(self, conversation_id: str) -> Conversation:
        """获取或创建对话"""
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = Conversation(self.client, conversation_id)
        return self.conversations[conversation_id]
    
    def set_frontend(self, frontend: BaseFrontend):
        """设置前端并绑定回调"""
        self.current_frontend = frontend
        
        def handle_message(message: Message, ctx: ConversationContext):
            conversation = self.get_conversation(ctx.conversation_id)
            try:
                response = conversation.send_message(message.content)
                response_msg = Message(
                    content=response,
                    role="assistant",
                    msg_type=MessageType.TEXT
                )
                frontend.display_message(response_msg)
            except Exception as e:
                frontend.display_error(str(e))
        
        def handle_clear(ctx: ConversationContext):
            conversation = self.get_conversation(ctx.conversation_id)
            conversation.clear_history()
            frontend.display_info("对话历史已清空")
        
        def handle_exit():
            self.stop()
        
        frontend.set_on_message(handle_message)
        frontend.set_on_clear(handle_clear)
        frontend.set_on_exit(handle_exit)
    
    def run(self, frontend: BaseFrontend):
        """运行应用"""
        self.set_frontend(frontend)
        try:
            frontend.start()
        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            if self.current_frontend:
                self.current_frontend.display_error(str(e))
            raise
    
    def stop(self):
        """停止应用"""
        if self.current_frontend:
            self.current_frontend.stop()
