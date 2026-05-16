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

SYSTEM_PROMPT = """你是一个消息灵通、嗅觉敏锐的AI伙伴。每天你会主动找用户聊天。

你最重要的燃料是「网络资讯」——今天世界上发生了什么新鲜事、有什么新发现、
新争论、新趋势。你对用户已有了解（记忆），但你的价值在于把外部世界的新鲜信息
和用户已知的兴趣做连接，让用户接触到他们自己不会主动去搜的东西。

你的目标是生成一张「话题建议卡」，给用户 2-3 个值得讨论的方向。

## 提交方式
使用 submit_decision_card 工具提交卡片。不要输出 JSON 文本。

## 选题原则（按优先级排列）
1. **借势资讯为主**：从网络资讯中找出最令人兴奋的发现——新研究、新趋势、
   意外事件、正在发生的争论。不要平铺直叙地转述新闻，要找到它和用户的"化学反应点"：
   「这个新闻为什么跟用户有关？」「它可以改变用户对什么的看法？」
   「它提供了一个什么新的行动可能性？」
2. **连接记忆**：把资讯和记忆中的兴趣/项目/讨论做连接。但连接是"调味料"，
   不是"主菜"——不要变成围绕记忆自说自话。如果资讯本身已经足够有趣，
   不需要强加记忆连接。
3. **出其不意**：如果网络资讯中出现了用户从未接触过但可能感兴趣的新领域，
   大胆引入。用户不知道自己不知道的东西，是你存在的意义。
4. **言之有物**：每个选项必须有具体的讨论锚点（具体事件、具体发现、具体问题），
   不是泛泛而谈的"聊聊AI趋势"。

## 卡片内容要求
- title: 吸引人的主题（含 emoji），最好带有一点"新闻感"而非纯总结
  好例子: 🧬 人类首次在活体细胞内观测到蛋白质"折纸"过程
  坏例子: 💡 一些有趣的科学发现
- context: 一句话 — 为什么今天这个有意思，以及和用户有什么关系
- options: 2-3 个方向
  - id: A, B, C
  - label: 方向名称（要有张力，让人想点）
  - description: 30字以内 — 具体聊什么
  - expected_effect: 聊完能带来什么（启发/灵感/决策/认知升级）
  - risk: 可能的争议或局限
  - confidence: 0.0~1.0
- sources: 引用来源 URL（从网络资讯中提取）

## 要求
1. 2-3 个选项，id 为 A, B, C
2. 选项之间要有区分度，不要同质化
3. title 含 emoji
4. 每个选项 description ≤ 30 字

## 禁区
- 不要问"今天怎么样"这种空泛的问候
- 不要给用户无法参与的技术指令（比如"你来写个编译器"）
- 不要讲大道理，要能给用户新的视角或具体的灵感
- 不要把话题做成"基于记忆的重复推荐"——如果网络资讯不足，宁可跳过"""


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

        搜索策略升级：
        - 每类主题执行 3 个搜索词 × 4 条结果，而非 3×2
        - 结果摘要更完整（300 字），保留足够信息供 LLM 判断价值
        - 轮换主题覆盖更多领域，增加"意外发现"的概率
        """
        from datetime import datetime
        weekday = datetime.now().weekday()  # 0=Mon, 6=Sun

        # 按星期轮换的启发式搜索词
        THEME_ROTATION = [
            # 周一：商业与趋势
            ["2026年商业趋势 创新", "新兴行业 增长 2026", "商业模式 变化 案例"],
            # 周二：科学与探索
            ["科学新发现 2026", "太空探索 最新进展", "生物学 突破性研究"],
            # 周三：文化与创意
            ["当代艺术 展览 2026", "创意灵感 设计趋势", "文学 新书推荐 2026"],
            # 周四：社会与人文
            ["社会现象 深度分析", "城市化 生活方式 变化", "教育 改革 2026"],
            # 周五：个人成长
            ["效率 方法论 2026", "心理学 认知升级", "技能 学习 新方法"],
            # 周六：生活与体验
            ["旅行 目的地推荐 2026", "美食 饮食文化 新趋势", "户外 运动 探索"],
            # 周日：哲学与反思
            ["哲学 思想 当代意义", "幸福 研究 2026", "技术 伦理 人工智能"],
        ]

        general_queries = THEME_ROTATION[weekday]

        results = []
        for q in general_queries:
            text = self._search(q, max_results=4)
            if text:
                # 保留更多内容 (300 字)，让 LLM 有足够信息判断价值
                results.append(
                    f"【资讯·{['周一','周二','周三','周四','周五','周六','周日'][weekday]}】"
                    f"{text[:300]}"
                )

        # 基于用户兴趣的搜索（同样增加深度）
        for interest in interests:
            # 搜两个维度：最新动态 + 深度分析
            for suffix in [" 2026 最新进展", " 深度分析"]:
                query = f"{interest}{suffix}"
                text = self._search(query, max_results=3)
                if text:
                    results.append(f"【{interest[:20]}相关】{text[:300]}")

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
                href = item.get("href", "")
                if title or body:
                    # 保留 URL 供 LLM 填写 sources 字段
                    snippet = f"{title}"
                    if body:
                        snippet += f": {body[:200]}"
                    if href:
                        snippet += f" [{href}]"
                    snippets.append(snippet)
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

        # 网络资讯放在最前面——这是你的主要信息燃料
        if ctx["web_news"].strip():
            sections.append("\n### 🌐 网络资讯（主要素材——今天的新闻、发现、趋势）")
            sections.append(ctx["web_news"])

        # 记忆作为"用户画像"辅助，排在资讯之后
        if ctx["memory"].strip():
            sections.append("\n### 关于用户的背景（辅助——帮助判断哪些资讯跟用户有关）")
            sections.append(ctx["memory"])

        if ctx["recent_topics"].strip():
            sections.append("\n### 近期讨论（辅助——避免重复推荐已聊过的话题）")
            sections.append(ctx["recent_topics"])

        if ctx["current_project"]:
            sections.append(f"\n### 当前项目（辅助）\n{ctx['current_project']}")

        sections.append("\n---")
        sections.append(
            "请基于以上信息生成一张话题建议卡。\n\n"
            "核心原则：从网络资讯中找出最值得聊的东西。"
            "用户背景和近期讨论只用来判断'这个资讯跟用户有没有关系'，"
            "不要把它们当作话题本身。如果网络资讯充足且有趣，"
            "用户记忆可以完全不体现在卡片中。"
        )

        user_message = "\n".join(sections)

        try:
            # 获取 SubmitDecisionCardTool 的 schema
            from llm_chat.tools.registry import ToolRegistry
            registry = ToolRegistry()
            all_tools = registry.get_tools_for_openai()
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
        """推送话题卡片到飞书，并为卡片新建独立会话。

        每次推送都是新话题的起点，不混入已有对话。
        用户 30 分钟内回复则继续该会话，超时则按默认策略再切新会话。
        """
        if not self._config.feishu.enabled:
            return
        try:
            adapter = getattr(self._app, "_feishu_adapter", None)
            if not adapter:
                logger.warning("飞书适配器未初始化，跳过推送")
                return

            # 获取最近活跃的飞书会话 (内存 → 数据库回退)
            recent = adapter.get_recent_chat()
            if not recent or recent.get("type") != "feishu":
                try:
                    recent = self._app.storage.get_recent_feishu_chat()
                except Exception as e:
                    logger.debug(f"数据库回退查询飞书会话失败: {e}")
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

            # 1. 推送到飞书
            adapter.send_message(
                receive_id=receive_id,
                msg_type="text",
                content={"text": text},
                receive_id_type=receive_id_type,
            )

            # 2. 为卡片新建独立会话并持久化消息
            conversation_id = self._open_proactive_session(receive_id, text, card)

            logger.info(
                f"主动话题卡片已推送到飞书: {card.title}, "
                f"会话: {conversation_id or '?'}"
            )
        except Exception as e:
            logger.warning(f"飞书推送失败: {e}")

    # ----------------------------------------------------------------
    # 会话管理
    # ----------------------------------------------------------------

    def _open_proactive_session(
        self, chat_id: str, text: str, card: DecisionCard
    ) -> Optional[str]:
        """为 ProactiveAgent 卡片新建独立会话并持久化消息。

        利用 SessionMapper.to_conversation_id(force_new_session=True)
        创建新会话编号，30 分钟内用户回复将复用此会话。
        """
        from llm_chat.frontends.feishu.mapper import SessionMapper

        # 从已有会话推断 p2p / group 类型
        chat_type = self._infer_chat_type(chat_id)

        # 强制新建会话 (SessionMapper 递增 session_number)
        conv_id = SessionMapper.to_conversation_id(
            chat_type, chat_id, force_new_session=True
        )

        try:
            storage = self._app.storage
            # 确保会话记录存在
            if storage.get_conversation(conv_id) is None:
                storage.create_conversation(conv_id, title=card.title[:80])

            # 持久化卡片消息
            storage.add_message(
                conversation_id=conv_id,
                role="assistant",
                content=text,
                metadata={
                    "source": "proactive_agent",
                    "card_id": card.id,
                    "card_title": card.title,
                },
            )
            logger.info(
                f"ProactiveAgent 新建会话并持久化: conv={conv_id}, card={card.id}"
            )
            return conv_id
        except Exception as e:
            logger.warning(f"新建 proactive 会话失败: {e}")
            return None

    def _infer_chat_type(self, chat_id: str) -> str:
        """从已有 conversations 表推断飞书会话类型 (p2p / group)。"""
        sanitized = "".join(ch if ch.isalnum() else "_" for ch in str(chat_id))
        try:
            storage = self._app.storage
            with storage._get_connection() as conn:
                # 查 p2p 优先
                row = conn.execute(
                    "SELECT id FROM conversations "
                    "WHERE id LIKE ? "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (f"feishu_p2p_{sanitized}_%",),
                ).fetchone()
                if row:
                    return "p2p"
                # 再查 group
                row = conn.execute(
                    "SELECT id FROM conversations "
                    "WHERE id LIKE ? "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (f"feishu_group_{sanitized}_%",),
                ).fetchone()
                if row:
                    return "group"
        except Exception as e:
            logger.debug(f"推断 chat_type 失败: {e}")
        return "p2p"  # 默认私聊

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
