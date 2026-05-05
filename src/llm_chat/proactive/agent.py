"""ProactiveAgent — 自主主动聊天代理。

每日定时触发，基于记忆自主生成话题并推送到用户前端。
"""

import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from llm_chat.app import App
    from llm_chat.config import Config

logger = logging.getLogger(__name__)

# 开场白风格预设，LLM 自行选择或混搭
STYLE_HINTS = """
- 求知型：提问 + 抛出信息差（"我最近看到..."）
- 辩论型：对用户之前的观点提出不同角度
- 关联型：从记忆中串联两个不相关的话题
- 复盘型：回顾近期的讨论，提出迭代想法
- 突发灵感型：分享对某个问题的新思路
"""

SYSTEM_PROMPT = """你是一个主动思考的AI伙伴。每天你会有一次机会主动找用户聊天。

你的目标是：
1. **让对话有价值** — 不要问"今天怎么样"，要说点有信息量的
2. **利用记忆** — 参考你知道的用户背景、项目、偏好
3. **真诚的求知欲** — 如果你真的想知道用户的看法，就问
4. **可辩论** — 可以抛出一个有争议的观点，让用户反驳你
5. **简洁有力** — 控制在 50-150 字，一句话开场"""


class ProactiveAgent:
    """自主主动聊天代理。"""

    def __init__(self, app: "App", config: "Config"):
        self._app = app
        self._config = config
        self._last_opener: Optional[str] = None

    def generate_and_push(self) -> str:
        """生成开场白并推送到所有前端。"""
        opener = self._generate_opener()
        if not opener:
            return ""

        self._last_opener = opener
        logger.info(f"主动消息: {opener[:80]}...")

        # 推送
        self._push_to_feishu(opener)
        self._push_to_gui(opener)

        return opener

    def _build_context(self) -> dict:
        """收集上下文：记忆 + 近期对话 + 时间。"""
        context = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M (%A)"),
            "memory": "",
            "recent_topics": "",
            "current_project": "",
        }

        # 月份/季节/时段信息
        now = datetime.now()
        day_info = f"{now.year}年{now.month}月{now.day}日"
        if now.hour < 6:
            day_info += "，凌晨"
        elif now.hour < 12:
            day_info += "，上午"
        elif now.hour < 14:
            day_info += "，中午"
        elif now.hour < 18:
            day_info += "，下午"
        else:
            day_info += "，晚上"
        context["time"] = day_info

        try:
            # 记忆
            from llm_chat.memory import MemoryStorage
            storage = MemoryStorage()
            content = storage.load_long_term()
            if content:
                context["memory"] = content[:1500]

            # 近期对话主题 - 从中期记忆提取
            mem_mgr = getattr(self._app, "_memory_manager", None)
            if mem_mgr is None:
                # 从 conversation_manager 找
                conv_mgr = getattr(self._app, "conversation_manager", None)
                if conv_mgr:
                    mem_mgr = getattr(conv_mgr, "_memory_manager", None)

            if mem_mgr:
                mid = storage.load_mid_term()
                if mid:
                    context["recent_topics"] = mid[:800]

            # 当前项目 - 从长期记忆提取
            project_match = __import__("re").search(
                r'\[项目\].*?(?=\n|\Z)', content, re.DOTALL
            ) if content else None
            if project_match:
                context["current_project"] = project_match.group(0)[:200]

        except Exception as e:
            logger.warning(f"构建上下文失败: {e}")

        return context

    def _generate_opener(self) -> Optional[str]:
        """LLM 基于上下文生成开场白。"""
        ctx = self._build_context()

        # 检查是否有足够的信息
        has_info = bool(ctx["memory"].strip())
        if not has_info:
            logger.warning("无记忆信息，跳过主动聊天")
            return None

        prompt = f"""{SYSTEM_PROMPT}

## 背景信息

当前时间：{ctx['time']}

### 你了解的用户
{ctx['memory']}

### 近期讨论
{ctx['recent_topics']}

{"### 当前项目" if ctx['current_project'] else ""}
{ctx['current_project']}

---

根据以上信息，生成一段开场白。

{STYLE_HINTS}

只输出开场白本身，不要解释。直接以你想对用户说的话开头："""

        try:
            response = self._app.client.generate(prompt, max_tokens=300)
            opener = response.strip().strip('"').strip("'").strip('"')
            if len(opener) < 10:
                logger.warning(f"开场白过短: {opener}")
                return None
            return opener[:300]
        except Exception as e:
            logger.error(f"生成开场白失败: {e}")
            return None

    def _push_to_feishu(self, message: str):
        """通过飞书推送。"""
        if not self._config.feishu.enabled:
            logger.debug("飞书未启用，跳过推送")
            return

        try:
            from llm_chat.frontends.feishu.push import PushService
            adapter = getattr(self._app, "_feishu_adapter", None)
            if not adapter:
                logger.warning("飞书适配器未初始化，跳过推送")
                return

            push = PushService(adapter)

            # 推送到所有活跃会话
            push.broadcast(f"💡 {message}")
            logger.info("飞书推送成功")
        except Exception as e:
            logger.warning(f"飞书推送失败: {e}")

    def _push_to_gui(self, message: str):
        """推送 GUI 通知。"""
        try:
            frontend = getattr(self._app, "current_frontend", None)
            if frontend and frontend.name == "gui":
                from PyQt6.QtWidgets import QApplication
                app = QApplication.instance()
                if app:
                    # 原生 macOS 通知
                    app.alert(None, 0)
                    frontend.display_info(f"💡 {message}")
                    logger.info("GUI 推送成功")
        except Exception as e:
            logger.warning(f"GUI 推送失败: {e}")

    def get_last_opener(self) -> Optional[str]:
        """获取最近一次生成的开场白。"""
        return self._last_opener
