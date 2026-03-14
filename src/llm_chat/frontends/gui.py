import sys
import threading
from typing import Optional, TYPE_CHECKING
from llm_chat.frontends.base import BaseFrontend, Message, ConversationContext, MessageType

if TYPE_CHECKING:
    from llm_chat.frontends.cli import CLIFrontend

class GUIFrontend(BaseFrontend):
    """GUI 图形界面前端
    
    使用 tkinter 实现，支持跨平台。
    如果 tkinter 不可用，会抛出 ImportError 并提示安装方法。
    """
    
    def __init__(self, conversation_id: str = "default", title: str = "Vermilion Bird"):
        super().__init__("gui")
        self.conversation_id = conversation_id
        self.title = title
        self._root: Optional[object] = None
        self._chat_display: Optional[object] = None
        self._input_field: Optional[object] = None
        self._send_button: Optional[object] = None
        self._clear_button: Optional[object] = None
        self._tk = None
        self._ttk = None
        self._scrolledtext = None
    
    def _check_tkinter(self) -> bool:
        try:
            import tkinter as tk
            from tkinter import ttk, scrolledtext
            self._tk = tk
            self._ttk = ttk
            self._scrolledtext = scrolledtext
            return True
        except ImportError:
            return False
    
    def start(self):
        """启动 GUI"""
        if not self._check_tkinter():
            raise ImportError(
                "tkinter 未安装。GUI 前端需要 tkinter。\n"
                "在 macOS 上: tkinter 通常随 Python 一起安装。\n"
                "在 Linux 上: 请运行: sudo apt-get install python3-tk\n"
                "在 Windows 上: tkinter 通常已包含在 Python 安装中。"
            )
        
        self._root = self._tk.Tk()
        self._root.title(self.title)
        self._root.geometry("800x600")
        self._root.minsize(600, 400)
        
        self._setup_ui()
        self._setup_styles()
        
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.mainloop()
    
    def _setup_styles(self):
        """设置样式"""
        style = self._ttk.Style()
        style.configure("Send.TButton", padding=5)
        style.configure("Clear.TButton", padding=5)
    
    def _setup_ui(self):
        """设置 UI 组件"""
        main_frame = self._ttk.Frame(self._root, padding="10")
        main_frame.pack(fill=self._tk.BOTH, expand=True)
        
        header_frame = self._ttk.Frame(main_frame)
        header_frame.pack(fill=self._tk.X, pady=(0, 10))
        
        title_label = self._ttk.Label(
            header_frame, 
            text="Vermilion Bird", 
            font=("Arial", 16, "bold")
        )
        title_label.pack(side=self._tk.LEFT)
        
        self._clear_button = self._ttk.Button(
            header_frame, 
            text="Clear", 
            command=self._on_clear,
            style="Clear.TButton"
        )
        self._clear_button.pack(side=self._tk.RIGHT, padx=5)
        
        chat_frame = self._ttk.LabelFrame(main_frame, text="Chat", padding="5")
        chat_frame.pack(fill=self._tk.BOTH, expand=True, pady=(0, 10))
        
        self._chat_display = self._scrolledtext.ScrolledText(
            chat_frame,
            wrap=self._tk.WORD,
            state=self._tk.DISABLED,
            font=("Arial", 11),
            padx=10,
            pady=10
        )
        self._chat_display.pack(fill=self._tk.BOTH, expand=True)
        self._chat_display.tag_configure("user", foreground="#2196F3", font=("Arial", 11, "bold"))
        self._chat_display.tag_configure("assistant", foreground="#4CAF50", font=("Arial", 11, "bold"))
        self._chat_display.tag_configure("system", foreground="#9E9E9E", font=("Arial", 10, "italic"))
        self._chat_display.tag_configure("error", foreground="#F44336", font=("Arial", 11))
        
        input_frame = self._ttk.Frame(main_frame)
        input_frame.pack(fill=self._tk.X)
        
        input_label = self._ttk.Label(input_frame, text="Message:")
        input_label.pack(anchor=self._tk.W)
        
        input_container = self._ttk.Frame(input_frame)
        input_container.pack(fill=self._tk.X, pady=(5, 0))
        
        self._input_field = self._tk.Text(
            input_container,
            height=3,
            font=("Arial", 11),
            wrap=self._tk.WORD,
            padx=5,
            pady=5
        )
        self._input_field.pack(side=self._tk.LEFT, fill=self._tk.BOTH, expand=True)
        self._input_field.bind("<Control-Return>", lambda e: self._on_send())
        
        button_frame = self._ttk.Frame(input_container)
        button_frame.pack(side=self._tk.RIGHT, fill=self._tk.Y, padx=(10, 0))
        
        self._send_button = self._ttk.Button(
            button_frame,
            text="Send",
            command=self._on_send,
            style="Send.TButton"
        )
        self._send_button.pack(fill=self._tk.X, pady=(0, 5))
        
        exit_button = self._ttk.Button(
            button_frame,
            text="Exit",
            command=self._on_close,
            style="Clear.TButton"
        )
        exit_button.pack(fill=self._tk.X)
        
        self.display_info("Welcome to Vermilion Bird!")
        self.display_info("Press Ctrl+Enter to send message")
    
    def _on_send(self):
        """Send message"""
        if self._input_field is None:
            return
        
        content = self._input_field.get("1.0", self._tk.END).strip()
        if not content:
            return
        
        self._input_field.delete("1.0", self._tk.END)
        
        message = Message(
            content=content,
            role="user",
            msg_type=MessageType.TEXT
        )
        ctx = ConversationContext(conversation_id=self.conversation_id)
        
        self.display_message(message)
        self._set_input_state(False)
        
        def send_and_display():
            self._handle_message(message, ctx)
            self._root.after(0, lambda: self._set_input_state(True))
        
        thread = threading.Thread(target=send_and_display, daemon=True)
        thread.start()
    
    def _on_clear(self):
        """Clear conversation"""
        ctx = ConversationContext(conversation_id=self.conversation_id)
        self._handle_clear(ctx)
        
        if self._chat_display:
            self._chat_display.config(state=self._tk.NORMAL)
            self._chat_display.delete("1.0", self._tk.END)
            self._chat_display.config(state=self._tk.DISABLED)
        
        self.display_info("Conversation cleared")
    
    def _on_close(self):
        """Close window"""
        self._handle_exit()
        if self._root:
            self._root.destroy()
    
    def _set_input_state(self, enabled: bool):
        """Set input state"""
        if self._send_button:
            self._send_button.config(state=self._tk.NORMAL if enabled else self._tk.DISABLED)
        if self._input_field:
            self._input_field.config(state=self._tk.NORMAL if enabled else self._tk.DISABLED)
    
    def stop(self):
        """Stop GUI"""
        if self._root:
            self._root.quit()
    
    def display_message(self, message: Message):
        """Display message"""
        if self._chat_display is None:
            return
        
        self._chat_display.config(state=self._tk.NORMAL)
        
        if message.role == "user":
            self._chat_display.insert(self._tk.END, "\nYou: ", "user")
            self._chat_display.insert(self._tk.END, f"{message.content}\n")
        elif message.role == "assistant":
            self._chat_display.insert(self._tk.END, "\nAI: ", "assistant")
            self._chat_display.insert(self._tk.END, f"{message.content}\n")
            self._chat_display.insert(self._tk.END, "-" * 40 + "\n", "system")
        
        self._chat_display.see(self._tk.END)
        self._chat_display.config(state=self._tk.DISABLED)
    
    def display_error(self, error: str):
        """Display error"""
        if self._chat_display is None:
            return
        
        self._chat_display.config(state=self._tk.NORMAL)
        self._chat_display.insert(self._tk.END, f"\nError: {error}\n", "error")
        self._chat_display.see(self._tk.END)
        self._chat_display.config(state=self._tk.DISABLED)
    
    def display_info(self, info: str):
        """Display info"""
        if self._chat_display is None:
            return
        
        self._chat_display.config(state=self._tk.NORMAL)
        self._chat_display.insert(self._tk.END, f"[{info}]\n", "system")
        self._chat_display.see(self._tk.END)
        self._chat_display.config(state=self._tk.DISABLED)
