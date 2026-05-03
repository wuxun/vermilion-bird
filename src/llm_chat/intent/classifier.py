"""意图识别分类器 — 三层路由。

Layer 0: / 前缀快捷指令 (正则)
Layer 1: 关键词/模式匹配 (无需 LLM)
Layer 2: 模型路由建议 (意图→模型大小)

设计目标：拦截 80%+ 请求避免不必要的 LLM 调用。
"""

from __future__ import annotations

import logging
import re
from typing import Optional, List

from .types import Intent, RoutingDecision

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# Layer 0: 快捷指令模式
# ═══════════════════════════════════════════════════════════════════

_SHORTCUT_PATTERNS: list[tuple[re.Pattern, Intent, str]] = [
    (re.compile(r"^/search\s+(.+)", re.IGNORECASE), Intent.SEARCH, "搜索"),
    (re.compile(r"^/file\s+(.+)", re.IGNORECASE), Intent.FILE_OP, "文件操作"),
    (re.compile(r"^/read\s+(.+)", re.IGNORECASE), Intent.FILE_OP, "文件读取"),
    (re.compile(r"^/write\s+(.+)", re.IGNORECASE), Intent.FILE_OP, "文件写入"),
    (re.compile(r"^/code\s+(.+)", re.IGNORECASE), Intent.CODE, "代码"),
    (re.compile(r"^/memory\b", re.IGNORECASE), Intent.MEMORY, "记忆"),
    (re.compile(r"^/schedule\b", re.IGNORECASE), Intent.SCHEDULE, "定时任务"),
    (re.compile(r"^/summary?\b", re.IGNORECASE), Intent.SUMMARIZE, "摘要"),
    # 清空对话 — 直接返回
    (re.compile(r"^/(?:clear|reset|清空|重置)\b", re.IGNORECASE), Intent.SHORTCUT, ""),
    # 帮助
    (re.compile(r"^/(?:help|帮助|\\?)\b", re.IGNORECASE), Intent.SHORTCUT, ""),
]


# ═══════════════════════════════════════════════════════════════════
# Layer 1: 模式匹配
# ═══════════════════════════════════════════════════════════════════

# 问候 → 直接回复
_GREETING_PATTERNS = re.compile(
    r"^(你好|hi|hey|hello|嗨|早上好|晚上好|下午好|"
    r"在吗|在不在|hello there|good morning|good evening)[\s!！。.~～]*$",
    re.IGNORECASE,
)

# 感谢 → 直接回复
_THANKS_PATTERNS = re.compile(
    r"^(谢谢|感谢|多谢|thanks|thank you|thx|3q)[\s!！。.~～]*$",
    re.IGNORECASE,
)

# 简单确认
_CONFIRM_PATTERNS = re.compile(
    r"^[好行对可不嗯哦是](?:的|吧|啊|呀|呢)?[\s!！。.~～]*$",
)

# 再见
_BYE_PATTERNS = re.compile(
    r"^(再见|拜拜|bye|byebye|88|晚安|回头见)[\s!！。.~～]*$",
    re.IGNORECASE,
)

# 搜索意图关键词
_SEARCH_KEYWORDS = re.compile(
    r"(搜索|查一下|帮我查|搜一下|查找|检索|网上查|"
    r"百度一下|谷歌|bing|search|look up|find online)",
    re.IGNORECASE,
)

# 代码意图关键词
_CODE_KEYWORDS = re.compile(
    r"(写.*代码|编写.*代码|生成.*代码|实现.*功能|"
    r"debug|调试|修复.*bug|修复.*错误|优化.*代码|重构|"
    r"code|implement|write a function|"
    r"class|function|def |import |"
    r"怎么写|怎么实现|帮我写|帮我改)",
    re.IGNORECASE,
)

# 摘要关键词
_SUMMARIZE_KEYWORDS = re.compile(
    r"(总结|摘要|概括|归纳|概述|梳理|"
    r"summarize|summary|tldr|recap)",
    re.IGNORECASE,
)

# 文件操作关键词
_FILE_KEYWORDS = re.compile(
    r"(读取|打开|查看|编辑|修改|创建|新建|删除|写入|保存|"
    r"文件|read file|open file|edit file|create file|write file)",
    re.IGNORECASE,
)

# 简单事实问答 (谁、什么、何时、哪里)
_SIMPLE_QA_PATTERNS = re.compile(
    r"^(谁|什么|何时|哪里|哪儿|多少|怎么|如何|为什么|"
    r"what|who|when|where|how|why|which|"
    r"几点|几时|什么时间|在哪里)",
    re.IGNORECASE,
)

# 定时任务关键词
_SCHEDULE_KEYWORDS = re.compile(
    r"(定时|计划|预约|周期|每天|每周|每月|定时器|"
    r"schedule|cron|remind|提醒)",
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════════
# Layer 2: 模型路由建议 (意图 → 模型大小)
# ═══════════════════════════════════════════════════════════════════

_INTENT_MODEL_HINTS: dict[Intent, str] = {
    Intent.SIMPLE_QA: "small",      # 使用配置中的小模型
    Intent.GREETING: "small",
    Intent.SEARCH: "small",         # 搜索结果摘要用小模型
    Intent.SUMMARIZE: "medium",
    Intent.FILE_OP: "medium",
    Intent.SCHEDULE: "medium",
    Intent.MEMORY: "medium",
    Intent.CODE: "large",           # 代码生成需要强模型
    Intent.CHAT: "large",           # 复杂对话用大模型
}

# 需要强制使用推理模型 (reasoning) 的意图
_REASONING_INTENTS: set[Intent] = {
    Intent.CODE,
}


# ═══════════════════════════════════════════════════════════════════
# 预设回复模板
# ═══════════════════════════════════════════════════════════════════

_GREETING_RESPONSES = [
    "你好！我是 🐦 Vermilion Bird，有什么可以帮你的？",
    "嗨！今天想聊点什么？需要我帮你搜索、写代码还是处理文件？",
    "你好呀！随时可以问我问题，或者试试 `/search`、`/code` 等快捷指令~",
]

_THANKS_RESPONSES = [
    "不客气！还有什么需要帮忙的吗？",
    "随时为你服务~ 😊",
]

_BYE_RESPONSES = [
    "再见！下次聊~ 👋",
    "拜拜，有需要随时找我！",
]

_CONFIRM_RESPONSES = [
    "好的，我在听。有什么想聊的？",
    "嗯？有什么我可以帮你的吗？",
]

_HELP_TEXT = """🐦 **Vermilion Bird 快捷指令**

| 指令 | 说明 |
|------|------|
| `/search <关键词>` | 搜索网页 |
| `/file <路径>` | 读取/操作文件 |
| `/code <描述>` | 写代码 |
| `/memory` | 查看/管理记忆 |
| `/schedule` | 管理定时任务 |
| `/summary` | 总结对话 |
| `/clear` | 清空对话 |
| `/help` | 显示此帮助 |

也可以直接聊 — 我会自动理解你的意图 😊"""


import random


class IntentClassifier:
    """意图分类器 — 三层路由管道。

    Layer 0: / 前缀指令 → 直接分流
    Layer 1: 关键词/模式匹配 → 确定性意图
    Layer 2: 模型大小建议 (给上层使用)
    """

    def __init__(self, enable_layer1: bool = True):
        self._enable_layer1 = enable_layer1
        logger.info(
            "IntentClassifier initialized (layer1=%s)", enable_layer1
        )

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def classify(self, message: str) -> RoutingDecision:
        """对用户消息进行意图分类。

        Args:
            message: 用户输入文本

        Returns:
            RoutingDecision 路由决策
        """
        if not message or not message.strip():
            return RoutingDecision.passthrough()

        msg = message.strip()

        # Layer 0: 快捷指令
        decision = self._classify_shortcut(msg)
        if decision is not None:
            return decision

        # Layer 1: 模式匹配
        if self._enable_layer1:
            decision = self._classify_pattern(msg)
            if decision is not None:
                return decision

        # 默认走完整 LLM 管道
        return RoutingDecision(
            intent=Intent.CHAT,
            confidence=0.5,
            suggested_model=_INTENT_MODEL_HINTS.get(Intent.CHAT),
            force_reasoning=False,
        )

    # ------------------------------------------------------------------
    # Layer 0: / 前缀快捷指令
    # ------------------------------------------------------------------

    def _classify_shortcut(self, msg: str) -> Optional[RoutingDecision]:
        """匹配 / 前缀快捷指令。

        返回 None 表示未匹配，交给下一层。
        """
        for pattern, intent, label in _SHORTCUT_PATTERNS:
            m = pattern.match(msg)
            if m:
                if intent == Intent.SHORTCUT:
                    # /clear /reset /help → 直接回复
                    if "clear" in pattern.pattern or "reset" in pattern.pattern or "清空" in pattern.pattern or "重置" in pattern.pattern:
                        return RoutingDecision.bypass(
                            Intent.SHORTCUT,
                            "对话已清空。开始新的对话吧！",
                        )
                    elif "help" in pattern.pattern or "帮助" in pattern.pattern:
                        return RoutingDecision.bypass(
                            Intent.SHORTCUT,
                            _HELP_TEXT,
                        )
                    return RoutingDecision.passthrough()

                # /search /file /code 等 → 提取内容，路由到对应意图
                content = m.group(1).strip() if m.lastindex else msg
                decision = RoutingDecision(
                    intent=intent,
                    confidence=0.9,
                    override_message=content if content != msg else None,
                )
                decision.suggested_model = _INTENT_MODEL_HINTS.get(intent)
                decision.force_reasoning = intent in _REASONING_INTENTS
                if intent == Intent.SEARCH:
                    decision.suggested_tools = ["web_search"]
                elif intent == Intent.FILE_OP:
                    decision.suggested_tools = [
                        "file_reader", "file_writer", "file_editor"
                    ]
                elif intent == Intent.CODE:
                    decision.suggested_tools = ["shell_exec", "file_writer"]
                elif intent == Intent.SCHEDULE:
                    decision.suggested_tools = [
                        "create_task", "list_tasks", "delete_task",
                        "pause_task", "resume_task",
                    ]
                elif intent == Intent.MEMORY:
                    decision.suggested_tools = ["memory_status", "memory_soul"]
                return decision

        return None

    # ------------------------------------------------------------------
    # Layer 1: 关键词/模式匹配
    # ------------------------------------------------------------------

    def _classify_pattern(self, msg: str) -> Optional[RoutingDecision]:
        """基于关键词和正则模式匹配意图。

        返回 None 表示未匹配，走默认管道。
        """
        # 1. 问候
        if _GREETING_PATTERNS.match(msg):
            return RoutingDecision.bypass(
                Intent.GREETING, random.choice(_GREETING_RESPONSES)
            )

        # 2. 感谢
        if _THANKS_PATTERNS.match(msg):
            return RoutingDecision.bypass(
                Intent.GREETING, random.choice(_THANKS_RESPONSES)
            )

        # 3. 再见
        if _BYE_PATTERNS.match(msg):
            return RoutingDecision.bypass(
                Intent.GREETING, random.choice(_BYE_RESPONSES)
            )

        # 4. 确认 (仅当消息很短时)
        if len(msg) <= 3 and _CONFIRM_PATTERNS.match(msg):
            return RoutingDecision.bypass(
                Intent.GREETING, random.choice(_CONFIRM_RESPONSES)
            )

        # 5. 搜索意图
        if _SEARCH_KEYWORDS.search(msg):
            return RoutingDecision(
                intent=Intent.SEARCH,
                confidence=0.8,
                suggested_tools=["web_search"],
                suggested_model=_INTENT_MODEL_HINTS[Intent.SEARCH],
            )

        # 6. 代码意图
        if _CODE_KEYWORDS.search(msg):
            return RoutingDecision(
                intent=Intent.CODE,
                confidence=0.85,
                suggested_tools=["shell_exec", "file_writer"],
                suggested_model=_INTENT_MODEL_HINTS[Intent.CODE],
                force_reasoning=True,
            )

        # 7. 摘要意图
        if _SUMMARIZE_KEYWORDS.search(msg):
            return RoutingDecision(
                intent=Intent.SUMMARIZE,
                confidence=0.8,
                suggested_model=_INTENT_MODEL_HINTS[Intent.SUMMARIZE],
            )

        # 8. 文件操作
        if _FILE_KEYWORDS.search(msg):
            return RoutingDecision(
                intent=Intent.FILE_OP,
                confidence=0.75,
                suggested_tools=["file_reader", "file_writer", "file_editor"],
                suggested_model=_INTENT_MODEL_HINTS[Intent.FILE_OP],
            )

        # 9. 定时任务
        if _SCHEDULE_KEYWORDS.search(msg):
            return RoutingDecision(
                intent=Intent.SCHEDULE,
                confidence=0.7,
                suggested_tools=[
                    "create_task", "list_tasks", "delete_task",
                    "pause_task", "resume_task",
                ],
                suggested_model=_INTENT_MODEL_HINTS[Intent.SCHEDULE],
            )

        # 10. 简单事实问答 (消息较短 + 以疑问词开头)
        if len(msg) < 50 and _SIMPLE_QA_PATTERNS.match(msg):
            return RoutingDecision(
                intent=Intent.SIMPLE_QA,
                confidence=0.6,
                suggested_model=_INTENT_MODEL_HINTS[Intent.SIMPLE_QA],
            )

        return None

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def get_model_hint(intent: Intent) -> Optional[str]:
        """获取意图对应的模型大小建议。"""
        return _INTENT_MODEL_HINTS.get(intent)

    @staticmethod
    def list_shortcuts() -> list[tuple[str, str]]:
        """获取所有快捷指令列表。"""
        shortcuts = []
        seen = set()
        for pattern, intent, label in _SHORTCUT_PATTERNS:
            cmd = pattern.pattern.lstrip("^").replace("\\b", "").replace("\\s+", " ")
            if cmd not in seen and label:
                seen.add(cmd)
                shortcuts.append((cmd, label))
        return shortcuts
