"""Storage - SQLite 持久化 (单例)

通过 mixin 组合实现，各模块职责：
- _core.py         StorageCore              单例/连接/schema/_row_to_dict
- _conversation.py StorageConversationMixin 对话/消息 CRUD
- _task.py         StorageTaskMixin         任务/执行 CRUD
- _feishu.py       StorageFeishuMixin       飞书对话追踪
"""

from llm_chat.storage._core import StorageCore
from llm_chat.storage._conversation import StorageConversationMixin
from llm_chat.storage._task import StorageTaskMixin
from llm_chat.storage._feishu import StorageFeishuMixin


class Storage(
    StorageConversationMixin,
    StorageTaskMixin,
    StorageFeishuMixin,
    StorageCore,
):
    """SQLite 持久化存储 (单例)

    管理 7 张表：
    - conversations / messages           对话和消息
    - tasks / task_executions            定时任务和执行记录
    - recent_feishu_chat                 飞书对话追踪
    - context_cache                      上下文缓存
    - messages_fts                       全文搜索索引
    """
