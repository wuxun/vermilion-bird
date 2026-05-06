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

SYSTEM_PROMPT = """你是一个有好奇心、有品位的AI伙伴。每天你会主动找用户聊天。

你的目标是生成一张「话题建议卡」，给用户 2-3 个值得讨论的方向。

## 提交方式
使用 submit_decision_card 工具提交卡片。不要输出 JSON 文本。

## 选题原则
1. **从用户出发**：优先从记忆中的兴趣、项目、近期讨论中找线索
2. **借势资讯**：如果网络上有令人兴奋的新发现，以此为引
3. **出其不意**：偶尔跳出常规，给一个用户自己都没想到、但会眼前一亮的角度
4. **言之有物**：每个选项必须有具体的讨论锚点，不是泛泛而谈

## 卡片内容要求
- title: 吸引人的主题（含 emoji）
- context: 一句话 — 为什么今天这个有意思
- options: 2-3 个方向
  - id: A, B, C
  - label: 方向名称（要有张力，让人想点）
  - description: 30字以内 — 具体聊什么
  - expected_effect: 聊完能带来什么（启发/灵感/决策/认知升级）
  - risk: 可能的争议或局限
  - confidence: 0.0~1.0
- sources: 引用来源

## 要求
1. 2-3 个选项，id 为 A, B, C
2. 选项之间要有区分度，不要同质化
3. title 含 emoji
4. 每个选项 description ≤ 30 字

## 禁区
- 不要问"今天怎么样"这种空泛的问候
- 不要给用户无法参与的技术指令（比如"你来写个编译器"）
- 不要讲大道理，要能给用户新的视角或具体的灵感"""


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
        """获取网络资讯，按星期几轮换不同领域的搜索词。

        目的是给 LLM 多角度的信息燃料，而非总是从科技/AI 出发。
        """
        from datetime import datetime
        weekday = datetime.now().weekday()  # 0=Mon, 6=Sun

        # 按星期轮换的启发式搜索词（避免每天固定主题）
        THEME_ROTATION = [
            # 周一：商业与趋势
            ["2026年商业趋势 创新", "新兴行业 增长", "商业模式 变化"],
            # 周二：科学与探索
            ["科学新发现 2026", "太空探索 最新", "生物学 突破"],
            # 周三：文化与创意
            ["当代艺术 展览 2026", "创意灵感 设计趋势", "文学 新书推荐"],
            # 周四：社会与人文
            ["社会现象 深度分析", "城市化 生活方式", "教育 新趋势"],
            # 周五：个人成长
            ["效率 方法论 2026", "心理学 认知升级", "技能 学习曲线"],
            # 周六：生活与体验
            ["旅行 目的地推荐", "美食 饮食文化", "户外 运动 方式"],
            # 周日：哲学与反思
            ["哲学 思想 当代意义", "幸福 研究 2026", "技术 伦理 讨论"],
        ]

        general_queries = THEME_ROTATION[weekday]

        results = []
        for q in general_queries:
            text = self._search(q, max_results=2)
            if text:
                results.append(f"【资讯·{['周一','周二','周三','周四','周五','周六','周日'][weekday]}】{text[:200]}")

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
        """推送话题卡片到飞书最近活跃会话。"""
        if not self._config.feishu.enabled:
            return
        try:
            adapter = getattr(self._app, "_feishu_adapter", None)
            if not adapter:
                logger.warning("飞书适配器未初始化，跳过推送")
                return

            # 获取最近活跃的飞书会话
            recent = adapter.get_recent_chat()
            if not recent or recent.get("type") != "feishu":
                logger.warning("无最近飞书会话，跳过主动推送")
                return

            # 确定 chat_id 和 receive_id_type
            receive_id = recent.get("chat_id") or recent.get("open_id") or recent.get("user_id")
            receive_id_type = "chat_id" if "chat_id" in recent else ("open_id" if "open_id" in recent else "user_id")
            if not receive_id:
                logger.warning("无法确定飞书接收方 ID，跳过推送")
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

            text = "\n".join(filter(None, lines))
            adapter.send_message(
                receive_id=receive_id,
                msg_type="text",
                content={"text": text},
                receive_id_type=receive_id_type,
            )
            logger.info(f"主动话题卡片已推送到飞书: {card.title}")
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
