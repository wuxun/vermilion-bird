"""协作式 Run 控制信号与安全边界异常。"""

from __future__ import annotations

import threading
from typing import Optional


class ExecutionControlRequested(RuntimeError):
    """执行器到达安全边界后用于退出当前调用栈。"""


class ExecutionCancelRequested(ExecutionControlRequested):
    pass


class ExecutionPauseRequested(ExecutionControlRequested):
    pass


def check_control(
    *,
    cancel_event: Optional[threading.Event] = None,
    pause_event: Optional[threading.Event] = None,
) -> None:
    """在副作用前后和图节点边界检查控制请求。"""

    if cancel_event is not None and cancel_event.is_set():
        raise ExecutionCancelRequested("run cancellation requested")
    if pause_event is not None and pause_event.is_set():
        raise ExecutionPauseRequested("run pause requested")
