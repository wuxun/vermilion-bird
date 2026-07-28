"""Storage - SQLite 持久化 (单例)

通过 mixin 组合实现，各模块职责：
- _core.py         StorageCore              单例/连接/schema/_row_to_dict
- _conversation.py StorageConversationMixin 对话/消息 CRUD
- _task.py         StorageTaskMixin         任务/执行 CRUD
- _feishu.py       StorageFeishuMixin       飞书对话追踪
- _runtime.py      StorageRuntimeMixin      运行记录/动作审批
- _work.py         StorageWorkMixin         用户任务/交付物
"""

from llm_chat.storage._core import StorageCore
from llm_chat.storage._conversation import StorageConversationMixin
from llm_chat.storage._task import StorageTaskMixin
from llm_chat.storage._digest import StorageDigestMixin
from llm_chat.storage._feishu import StorageFeishuMixin
from llm_chat.storage._runtime import StorageRuntimeMixin
from llm_chat.storage._work import StorageWorkMixin
from llm_chat.storage._workflow import StorageWorkflowMixin


class Storage(
    StorageConversationMixin,
    StorageTaskMixin,
    StorageDigestMixin,
    StorageFeishuMixin,
    StorageRuntimeMixin,
    StorageWorkMixin,
    StorageWorkflowMixin,
    StorageCore,
):
    """SQLite 持久化存储 (单例)

    管理运行所需的业务表：
    - conversations / messages           对话和消息
    - tasks / task_executions            定时任务和执行记录
    - recent_feishu_chat                 飞书对话追踪
    - context_cache                      上下文缓存
    - messages_fts                       全文搜索索引
    - runs / run_events                  可审计运行与事件
    - action_proposals                   高风险动作审批
    - work_items / artifacts             用户任务和交付物
    """
