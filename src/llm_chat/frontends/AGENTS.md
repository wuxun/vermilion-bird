# 前端适配器

## 概述

用户界面层，支持 CLI（终端）和 GUI（PyQt6）两种前端。

## 结构

```
frontends/
├── __init__.py        # FRONTEND_MAP 注册表
├── base.py            # BaseFrontend 基类
├── cli.py             # 终端前端（富文本/Markdown）
├── gui.py             # PyQt6 图形界面
├── mcp_dialog.py      # MCP 配置对话框
└── skills_dialog.py   # 技能配置对话框
```

## 快速定位

| 任务 | 文件 | 说明 |
|------|------|------|
| 添加新前端 | `__init__.py` | 注册到 FRONTEND_MAP |
| 修改 CLI 输出 | `cli.py` | CLIFrontend |
| 修改 GUI 布局 | `gui.py` | GUIFrontend |
| MCP 配置 UI | `mcp_dialog.py` | MCPDialog |

## 核心接口

### BaseFrontend

```python
class BaseFrontend(ABC):
    def __init__(self, conversation_id: str)
    
    @abstractmethod
    def start(self, 
              on_message: Callable[[Message], None],
              on_clear: Callable[[], None],
              on_exit: Callable[[], None]):
        """启动前端事件循环"""
    
    @abstractmethod
    def display_response(self, message: Message):
        """显示 AI 响应"""
    
    @abstractmethod
    def display_error(self, error: str):
        """显示错误"""
```

### Message 类型

```python
class MessageType(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"

@dataclass
class Message:
    type: MessageType
    content: str
    timestamp: datetime
```

## CLI 前端

- 使用 `rich` 库进行 Markdown 渲染
- 支持代码高亮
- 流式输出实时显示
- 交互命令：`exit`（退出）、`clear`（清空历史）

## GUI 前端

- PyQt6 实现
- 功能：
  - 对话界面（发送/接收消息）
  - MCP Tools 按钮（配置 MCP 服务器）
  - 会话管理（切换/重命名/删除）
  - Clear 按钮（清空对话）

## 扩展新前端

1. 在 `frontends/` 下创建 `{frontend}.py`
2. 继承 `BaseFrontend` 并实现所有抽象方法
3. 在 `__init__.py` 的 `FRONTEND_MAP` 中注册：

```python
FRONTEND_MAP = {
    "cli": CLIFrontend,
    "gui": GUIFrontend,
    "your_frontend": YourFrontend,  # 添加
}
```

## 约定

- 前端通过回调函数与 `App` 通信
- `on_message` 处理用户输入
- `on_clear` 处理清空请求
- `on_exit` 处理退出请求

## 使用示例

```python
from llm_chat.frontends import get_frontend

# 获取 CLI 前端
frontend = get_frontend("cli", conversation_id="default")

# 获取 GUI 前端
frontend = get_frontend("gui", conversation_id="default")
```

## 注意事项

- GUI 需要 PyQt6 依赖
- CLI 使用终端特性，在非交互环境可能受限
- 对话框（mcp_dialog/skills_dialog）仅 GUI 模式可用
