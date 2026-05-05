"""ProactiveAgent — 自主主动聊天代理。

每日定时触发，基于记忆 + 网络信息自主生成话题并推送到用户前端。
"""

import logging
import re
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from llm_chat.app import App
    from llm_chat.config import Config

logger = logging.getLogger(__name__)

# 开场白风格预设
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
3. **结合时事** — 如果有网络搜索结果，结合相关资讯提出话题
4. **真诚的求知欲** — 如果你真的想知道用户的看法，就问
5. **可辩论** — 可以抛出一个有争议的观点，让用户反驳你
6. **简洁有力** — 控制在 50-150 字，一句话开场"""


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

        self._push_to_feishu(opener)
        self._push_to_gui(opener)

        return opener

    # ----------------------------------------------------------------
    # 上下文构建
    # ----------------------------------------------------------------

    def _build_context(self) -> dict:
        """收集上下文：记忆 + 近期对话 + 时间 + 网络资讯。"""
        ctx = {
            "time": self._format_time(),
            "memory": "",
            "recent_topics": "",
            "current_project": "",
            "user_interests": [],
            "web_news": "",
        }

        try:
            storage = self._get_storage()
            content = storage.load_long_term() if storage else ""

            if content:
                ctx["memory"] = content[:1500]
                ctx["user_interests"] = self._extract_interests(content)

            ctx["current_project"] = self._extract_project(content)
            ctx["recent_topics"] = self._load_recent_topics(storage)
            ctx["web_news"] = self._fetch_web_context(ctx["user_interests"])

        except Exception as e:
            logger.warning(f"构建上下文失败: {e}")

        return ctx

    def _format_time(self) -> str:
        now = datetime.now()
        parts = [f"{now.year}年{now.month}月{now.day}日"]
        if now.hour < 6:
            parts.append("凌晨")
        elif now.hour < 12:
            parts.append("上午")
        elif now.hour < 14:
            parts.append("中午")
        elif now.hour < 18:
            parts.append("下午")
        else:
            parts.append("晚上")
        return "，".join(parts)

    def _get_storage(self):
        from llm_chat.memory import MemoryStorage
        return MemoryStorage()

    def _extract_interests(self, content: str) -> List[str]:
        """从长期记忆中提取用户兴趣关键词，用于搜索。"""
        interests = []

        # 提取项目和技术栈相关
        for label in ["[项目]", "[技能]", "[偏好]"]:
            matches = re.findall(rf'{re.escape(label)}\s*(.*?)$', content, re.MULTILINE)
            for m in matches:
                # 取前 40 字作为搜索关键词
                clean = m.strip()[:40]
                if clean and clean not in interests:
                    interests.append(clean)

        # 取前 3 个最相关的兴趣
        return interests[:3]

    def _extract_project(self, content: str) -> str:
        match = re.search(r'\[项目\].*?(?=\n|\Z)', content, re.DOTALL)
        return match.group(0)[:200] if match else ""

    def _load_recent_topics(self, storage) -> str:
        try:
            mid = storage.load_mid_term()
            return mid[:800] if mid else ""
        except Exception:
            return ""

    # ----------------------------------------------------------------
    # 网络资讯获取
    # ----------------------------------------------------------------

    def _fetch_web_context(self, interests: List[str]) -> str:
        """搜索网络资讯，返回格式化结果。"""
        results = []

        # 1. 通用科技资讯速览
        general_queries = [
            "科技趋势 2026",
            "AI 大模型 最新进展",
            "开源项目 热门",
        ]
        for q in general_queries:
            text = self._search(q, max_results=2)
            if text:
                results.append(f"【资讯】{text[:200]}")

        # 2. 基于用户兴趣的定向搜索
        for interest in interests:
            query = f"{interest} 2026 最新"
            text = self._search(query, max_results=2)
            if text:
                results.append(f"【{interest[:20]}相关】{text[:200]}")

        if not results:
            return ""

        return "\n\n".join(results)

    def _search(self, query: str, max_results: int = 3) -> Optional[str]:
        """使用 DuckDuckGo 搜索，返回摘要文本。"""
        try:
            from ddgs import DDGS
            ddgs = DDGS(timeout=10)
            items = list(ddgs.text(query, max_results=max_results))
            if not items:
                return None

            snippets = []
            for item in items:
                title = item.get("title", "")
                body = item.get("body", "")
                if title or body:
                    snippets.append(f"{title}: {body[:150]}")

            return " | ".join(snippets[:max_results]) if snippets else None

        except Exception as e:
            logger.debug(f"搜索失败 [{query}]: {e}")
            return None

    # ----------------------------------------------------------------
    # 开场白生成
    # ----------------------------------------------------------------

    def _generate_opener(self) -> Optional[str]:
        """LLM 基于上下文 + 网络资讯生成开场白。"""
        ctx = self._build_context()

        if not ctx["memory"].strip() and not ctx["web_news"].strip():
            logger.warning("无记忆和资讯信息，跳过主动聊天")
            return None

        # 构建 prompt 的各段
        sections = [SYSTEM_PROMPT, "", "## 背景信息", f"当前时间：{ctx['time']}"]

        if ctx["memory"].strip():
            sections.append("\n### 你了解的用户")
            sections.append(ctx["memory"])

        if ctx["recent_topics"].strip():
            sections.append("\n### 近期讨论")
            sections.append(ctx["recent_topics"])

        if ctx["current_project"]:
            sections.append(f"\n### 当前项目\n{ctx['current_project']}")

        if ctx["web_news"].strip():
            sections.append("\n### 网络资讯（可作为话题素材）")
            sections.append(ctx["web_news"])

        sections.extend([
            "",
            "---",
            "根据以上信息，生成一段开场白。",
            "可以从网络资讯切入，也可以结合记忆深度提问，也可以两者结合。",
            STYLE_HINTS,
            "",
            "只输出开场白本身，不要解释。直接以你想对用户说的话开头：",
        ])

        prompt = "\n".join(sections)

        try:
            response = self._app.client.chat(
                message=prompt,
                max_tokens=300,
                temperature=0.8,
            )
            opener = response.strip().strip('"').strip("'").strip('"')
            if len(opener) < 10:
                logger.warning(f"开场白过短: {opener}")
                return None
            return opener[:300]
        except Exception as e:
            logger.error(f"生成开场白失败: {e}")
            return None

    # ----------------------------------------------------------------
    # 推送
    # ----------------------------------------------------------------

    def _push_to_feishu(self, message: str):
        if not self._config.feishu.enabled:
            return
        try:
            from llm_chat.frontends.feishu.push import PushService
            adapter = getattr(self._app, "_feishu_adapter", None)
            if not adapter:
                logger.warning("飞书适配器未初始化，跳过推送")
                return
            push = PushService(adapter)
            push.broadcast(f"💡 {message}")
        except Exception as e:
            logger.warning(f"飞书推送失败: {e}")

    def _push_to_gui(self, message: str):
        """通过信号发射开场白，由 GUI 主线程处理创建对话。"""
        try:
            frontend = getattr(self._app, "current_frontend", None)
            if not frontend or frontend.name != "gui":
                return

            # 通过 pyqtSignal 跨线程安全通知 GUI 主线程
            signals = getattr(frontend, "_proactive_signals", None)
            if signals:
                signals.opener_ready.emit(message)
            else:
                logger.warning("GUI 未初始化 proactive_signals")
        except Exception as e:
            logger.warning(f"GUI 推送失败: {e}")

    def get_last_opener(self) -> Optional[str]:
        return self._last_opener
