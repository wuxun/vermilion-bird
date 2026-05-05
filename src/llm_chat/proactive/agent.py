"""ProactiveAgent — 自主主动聊天代理。

每日定时触发，基于记忆 + 网络信息生成决策卡片，推送到用户前端。
用户从卡片选项中选择感兴趣的话题，开启对话。
"""

import logging
import re
from datetime import datetime
from typing import Optional, List

from llm_chat.decision.schema import DecisionCard
from llm_chat.decision.submit_tool import get_pending_card

logger = logging.getLogger(__name__)

# ── Prompt 模板 ──────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是一个主动思考的AI伙伴。每天你会有一次机会主动找用户聊天。

你的目标是生成一张「话题建议卡」，给用户 2-3 个可选的讨论方向。

## 提交方式
使用 submit_decision_card 工具提交卡片。不要输出 JSON 文本。

## 卡片内容要求
- title: 吸引人的主题（含 emoji）
- context: 一句话背景 — 为什么今天聊这个
- options: 2-3 个选项
  - id: A, B, C
  - label: 方向名称
  - description: 30字以内的简要说明
  - expected_effect: 聊这个话题能带来什么
  - risk: 可能的争议点
  - confidence: 0.0~1.0
- sources: 来源引用

## 要求
1. 提供 2-3 个选项，id 依次为 A, B, C
2. 每个选项的 confidence 为 0.0~1.0 之间
3. 选项之间要有区分度
4. 可以基于网络资讯，也可以基于记忆，也可以两者结合
5. title 用 emoji 开头增加感染力
6. 每个选项的 description 控制在 30 字以内

## 注意事项
- 不要问"今天怎么样"这种空泛的问题
- 不要提用户没法回答的技术问题
- 选项应该是：这个方向有趣、值得讨论"""


class ProactiveAgent:
    """自主主动聊天代理。"""

    def __init__(self, app: "App", config: "Config"):
        self._app = app
        self._config = config
        self._last_card: Optional[DecisionCard] = None

    def generate_and_push(self):
        """生成话题建议卡并推送到所有前端。"""
        card = self._generate_card()
        if not card:
            logger.warning("生成卡片失败，跳过推送")
            return

        self._last_card = card
        logger.info(f"话题卡片: {card.title} ({len(card.options)} 个选项)")

        self._push_to_feishu(card)
        self._push_to_gui(card)

    # ----------------------------------------------------------------
    # 上下文构建（与之前相同）
    # ----------------------------------------------------------------

    def _build_context(self) -> dict:
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
        interests = []
        for label in ["[项目]", "[技能]", "[偏好]"]:
            matches = re.findall(
                rf'{re.escape(label)}\s*(.*?)$', content, re.MULTILINE
            )
            for m in matches:
                clean = m.strip()[:40]
                if clean and clean not in interests:
                    interests.append(clean)
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
        results = []

        general_queries = [
            "科技趋势 2026",
            "AI 大模型 最新进展",
            "开源项目 热门",
        ]
        for q in general_queries:
            text = self._search(q, max_results=2)
            if text:
                results.append(f"【资讯】{text[:200]}")

        for interest in interests:
            query = f"{interest} 2026 最新"
            text = self._search(query, max_results=2)
            if text:
                results.append(f"【{interest[:20]}相关】{text[:200]}")

        if not results:
            return ""
        return "\n\n".join(results)

    def _search(self, query: str, max_results: int = 3) -> Optional[str]:
        try:
            from ddgs import DDGS

            proxy = self._config.llm.http_proxy
            ddgs_kwargs = {"timeout": 10}
            if proxy:
                ddgs_kwargs["proxy"] = proxy

            ddgs = DDGS(**ddgs_kwargs)
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
    # 卡片生成
    # ----------------------------------------------------------------

    def _generate_card(self) -> Optional[DecisionCard]:
        """通过 tool-call 路径生成话题建议卡。

        LLM 使用 submit_decision_card 工具提交卡片，与 ChatCore 保持一致。
        """
        ctx = self._build_context()

        if not ctx["memory"].strip() and not ctx["web_news"].strip():
            logger.warning("无记忆和资讯信息，跳过主动聊天")
            return None

        # 构建用户消息（背景信息作为 user message 传入）
        sections = ["## 背景信息", f"当前时间：{ctx['time']}"]

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

        sections.append("\n---")
        sections.append("请基于以上信息，生成一张话题建议卡。")

        user_message = "\n".join(sections)

        try:
            # 获取 SubmitDecisionCardTool 的 schema
            from llm_chat.tools.registry import ToolRegistry
            registry = ToolRegistry()
            all_tools = registry.get_tools()
            card_tool = [t for t in all_tools if t.get("function", {}).get("name") == "submit_decision_card"]
            if not card_tool:
                logger.warning("submit_decision_card 工具未注册，跳过卡片生成")
                return None

            # 使用 chat_with_tools，LLM 自行调用 submit_decision_card
            self._app.client.chat_with_tools(
                message=user_message,
                tools=card_tool,
                history=[{"role": "system", "content": SYSTEM_PROMPT}],
                temperature=0.8,
                max_tokens=2000,
            )

            # 从 thread-local 提取卡片
            card = get_pending_card()
            if card:
                logger.info(f"ProactiveAgent 生成卡片: {card.id} -> {card.title}")
                return card
            else:
                logger.warning("chat_with_tools 完成但未提取到卡片")
                return None

        except Exception as e:
            logger.error(f"生成话题卡片失败: {e}", exc_info=True)
            return None

    # ----------------------------------------------------------------
    # 推送
    # ----------------------------------------------------------------

    def _push_to_feishu(self, card: DecisionCard):
        """飞书推送纯文本摘要。"""
        if not self._config.feishu.enabled:
            return
        try:
            from llm_chat.frontends.feishu.push import PushService

            adapter = getattr(self._app, "_feishu_adapter", None)
            if not adapter:
                logger.warning("飞书适配器未初始化，跳过推送")
                return

            # 纯文本摘要
            lines = [
                f"💡 {card.title}",
                f"  {card.context}" if card.context else "",
            ]
            for opt in card.options:
                rec = "✅" if opt.id == card.recommendation else "  "
                lines.append(f"{rec} 选{opt.id}: {opt.label} ({int(opt.confidence*100)}%)")
            if card.sources:
                lines.append(f"  来源: {', '.join(card.sources)}")

            push = PushService(adapter)
            push.broadcast("\n".join(filter(None, lines)))
        except Exception as e:
            logger.warning(f"飞书推送失败: {e}")

    def _push_to_gui(self, card: DecisionCard):
        """通过信号将决策卡片推送到 GUI。"""
        try:
            frontend = getattr(self._app, "current_frontend", None)
            if not frontend or frontend.name != "gui":
                return

            signals = getattr(frontend, "_card_signals", None)
            if signals:
                signals.card_created.emit(card)
            else:
                logger.warning("GUI 未初始化 card_signals")
        except Exception as e:
            logger.warning(f"GUI 推送失败: {e}")

    @property
    def last_card(self) -> Optional[DecisionCard]:
        return self._last_card
