"""Test IntentClassifier — three-layer routing pipeline."""

import pytest
from llm_chat.intent import IntentClassifier
from llm_chat.intent.types import Intent, RoutingDecision


# ------------------------------------------------------------------
# Fixture
# ------------------------------------------------------------------

@pytest.fixture
def classifier():
    return IntentClassifier(enable_layer1=True)


# ═══════════════════════════════════════════════════════════════════════
# Layer 0: / 前缀快捷指令
# ═══════════════════════════════════════════════════════════════════════

class TestLayer0Shortcuts:
    """Test /-prefixed shortcut commands."""

    # -- /search --

    @pytest.mark.parametrize("msg,expected_content", [
        ("/search Python decorators", "Python decorators"),
        ("/SEARCH best restaurants", "best restaurants"),
        ("/search   multiple   spaces", "multiple   spaces"),
    ])
    def test_search_extracts_query(self, classifier, msg, expected_content):
        d = classifier.classify(msg)
        assert d.intent == Intent.SEARCH
        assert d.override_message == expected_content
        assert d.confidence == 0.9
        assert "web_search" in d.suggested_tools

    # -- /file /read /write --

    @pytest.mark.parametrize("msg", [
        "/file /etc/hosts",
        "/read /etc/hosts",
        "/write /tmp/test.txt",
    ])
    def test_file_op_shortcuts(self, classifier, msg):
        d = classifier.classify(msg)
        assert d.intent == Intent.FILE_OP
        assert d.confidence == 0.9
        assert any(t in d.suggested_tools for t in ["file_reader", "file_writer", "file_editor"])

    # -- /code --

    def test_code_shortcut(self, classifier):
        d = classifier.classify("/code write a fibonacci function")
        assert d.intent == Intent.CODE
        assert d.confidence == 0.9
        assert d.force_reasoning is True
        assert "shell_exec" in d.suggested_tools

    # -- /new --

    def test_new_conversation(self, classifier):
        d = classifier.classify("/new")
        assert d.intent == Intent.SHORTCUT
        assert d.skip_llm is True
        assert d.override_message == "__new_conversation__"

    def test_new_with_title(self, classifier):
        d = classifier.classify("/new project discussion")
        assert d.skip_llm is True
        assert d.override_message == "__new_conversation__"

    # -- /style --

    def test_style_switch(self, classifier):
        d = classifier.classify("/style academic")
        assert d.intent == Intent.SHORTCUT
        assert d.skip_llm is True
        assert d.override_message == "__style__:academic"

    def test_style_default(self, classifier):
        d = classifier.classify("/style default")
        assert d.override_message == "__style__:default"

    # -- /remember /记住 --

    @pytest.mark.parametrize("msg,expected_content", [
        ("/remember Python 3.11 is my default", "Python 3.11 is my default"),
        ("/记住 我最喜欢用 Poetry 管理依赖", "我最喜欢用 Poetry 管理依赖"),
        ("/记忆 用户偏好：深色模式", "用户偏好：深色模式"),
    ])
    def test_remember_shortcut(self, classifier, msg, expected_content):
        d = classifier.classify(msg)
        assert d.intent == Intent.SHORTCUT
        assert d.skip_llm is True
        assert d.override_message == f"__remember__:{expected_content}"

    # -- /clear /reset --

    @pytest.mark.parametrize("msg", ["/clear", "/reset", "/清空", "/重置"])
    def test_clear_conversation(self, classifier, msg):
        d = classifier.classify(msg)
        assert d.intent == Intent.SHORTCUT
        assert d.skip_llm is True
        assert d.direct_response == "对话已清空。开始新的对话吧！"

    # -- /help --

    @pytest.mark.parametrize("msg", ["/help"])
    def test_help_shortcut(self, classifier, msg):
        d = classifier.classify(msg)
        assert d.intent == Intent.SHORTCUT
        assert d.skip_llm is True
        assert "Vermilion Bird" in d.direct_response
        assert "/search" in d.direct_response

    def test_help_question_mark_not_matched(self, classifier):
        """'/?"' is not a recognized shortcut — falls through to CHAT.

        Known gap: the regex uses r'\\?' which matches literal '\?'
        not '/?'.  Fix would be r'\?' or r'/?\b'.
        """
        d = classifier.classify("/?")
        assert d.intent == Intent.CHAT

    def test_help_chinese(self, classifier):
        d = classifier.classify("/帮助")
        assert d.skip_llm is True
        assert "Vermilion Bird" in d.direct_response

    # -- /memory (non-shortcut) --

    def test_memory_command(self, classifier):
        d = classifier.classify("/memory")
        assert d.intent == Intent.MEMORY
        assert "memory_status" in d.suggested_tools

    # -- /summary --

    def test_summarize_command(self, classifier):
        d = classifier.classify("/summary the last 5 messages")
        assert d.intent == Intent.SUMMARIZE
        assert d.suggested_model == "medium"

    # -- /schedule --

    def test_schedule_command(self, classifier):
        d = classifier.classify("/schedule")
        assert d.intent == Intent.SCHEDULE
        assert "create_task" in d.suggested_tools


# ═══════════════════════════════════════════════════════════════════════
# Layer 1: 关键词/模式匹配 — 短路回复 (skip_llm=True)
# ═══════════════════════════════════════════════════════════════════════

class TestLayer1Bypass:
    """Test L1 patterns that skip LLM entirely."""

    @pytest.mark.parametrize("msg", [
        "你好", "hi", "hello", "Hey!", "嗨", "早上好", "晚上好",
        "在吗", "hello there", "Good Morning",
    ])
    def test_greeting_bypasses_llm(self, classifier, msg):
        d = classifier.classify(msg)
        assert d.intent == Intent.GREETING
        assert d.skip_llm is True
        assert d.direct_response is not None

    @pytest.mark.parametrize("msg", [
        "谢谢", "感谢", "多谢", "thanks", "Thank you", "thx",
    ])
    def test_thanks_bypasses_llm(self, classifier, msg):
        d = classifier.classify(msg)
        assert d.intent == Intent.GREETING
        assert d.skip_llm is True

    @pytest.mark.parametrize("msg", [
        "再见", "拜拜", "bye", "晚安", "byebye",
    ])
    def test_bye_bypasses_llm(self, classifier, msg):
        d = classifier.classify(msg)
        assert d.intent == Intent.GREETING
        assert d.skip_llm is True

    def test_short_confirm_bypasses_llm(self, classifier):
        """Very short confirmations like '好', '嗯' skip LLM."""
        for msg in ["好", "嗯", "哦", "是", "对", "好的", "行"]:
            d = classifier.classify(msg)
            assert d.intent == Intent.GREETING
            assert d.skip_llm is True


# ═══════════════════════════════════════════════════════════════════════
# Layer 1: 关键词/模式匹配 — 路由 (不短路)
# ═══════════════════════════════════════════════════════════════════════

class TestLayer1Routing:
    """Test L1 patterns that route to specific intent + tools but still go to LLM."""

    @pytest.mark.parametrize("msg", [
        "帮我搜索最新的 React 教程",
        "查一下 GitHub trending",
        "搜一下 Python asyncio 最佳实践",
        "网上查找 transformers 库的使用方法",
        "Google search for fastapi middleware",
    ])
    def test_search_keywords_route(self, classifier, msg):
        d = classifier.classify(msg)
        assert d.intent == Intent.SEARCH
        assert d.confidence == 0.8
        assert d.skip_llm is False
        assert "web_search" in d.suggested_tools
        assert d.suggested_model == "small"

    @pytest.mark.parametrize("msg", [
        "帮我写一个排序函数",
        "debug 这段代码为什么报错",
        "重构这个类的设计",
        "帮我改改这个 bug",
    ])
    def test_code_keywords_route(self, classifier, msg):
        d = classifier.classify(msg)
        assert d.intent == Intent.CODE
        assert d.confidence == 0.85
        assert d.skip_llm is False
        assert d.force_reasoning is True
        assert "shell_exec" in d.suggested_tools
        assert d.suggested_model == "large"

    def test_code_keyword_gaps(self, classifier):
        """Messages that should match CODE but don't due to keyword gaps.

        Known gaps in _CODE_KEYWORDS:
        - '实现' only matches when followed by '功能' (实现.*功能)
        - '优化' only matches when followed by '代码' (优化.*代码)
        These should fall through to CHAT for now.
        """
        for msg in ["实现一个缓存装饰器", "优化这个查询的性能"]:
            d = classifier.classify(msg)
            assert d.intent == Intent.CHAT  # known gap, should be CODE

    @pytest.mark.parametrize("msg", [
        "帮我总结一下今天的对话",
        "摘要一下这个文档",
        "概括这篇文章的主要内容",
        "归纳推理的要点",
    ])
    def test_summarize_keywords_route(self, classifier, msg):
        d = classifier.classify(msg)
        assert d.intent == Intent.SUMMARIZE
        assert d.suggested_model == "medium"

    @pytest.mark.parametrize("msg", [
        "读取这个文件的内容",
        "帮我打开 config.yaml",
        "编辑 entrypoint.sh",
        "修改第 10 行的配置",
        "创建一个新的测试文件",
    ])
    def test_file_op_keywords_route(self, classifier, msg):
        d = classifier.classify(msg)
        assert d.intent == Intent.FILE_OP
        assert d.confidence == 0.75
        assert any(t in d.suggested_tools for t in [
            "file_reader", "file_writer", "file_editor"
        ])

    @pytest.mark.parametrize("msg", [
        "每天九点提醒我喝水",
        "设置一个每周五下午的定时任务",
        "预约下周一的会议提醒",
        "create a daily cron job",
    ])
    def test_schedule_keywords_route(self, classifier, msg):
        d = classifier.classify(msg)
        assert d.intent == Intent.SCHEDULE
        assert d.confidence == 0.7
        assert "create_task" in d.suggested_tools

    @pytest.mark.parametrize("msg", [
        "什么是机器学习",
        "how does git rebase work",
        "为什么天空是蓝色的",
    ])
    def test_simple_qa_routing(self, classifier, msg):
        d = classifier.classify(msg)
        assert d.intent == Intent.SIMPLE_QA
        assert d.confidence == 0.6
        assert d.suggested_model == "small"

    def test_simple_qa_gap(self, classifier):
        """'哪个' is not in _SIMPLE_QA_PATTERNS — falls to CHAT.

        Known gap: pattern has '哪里'/'哪儿' but not '哪个'.  Adding
        '哪个' would catch more simple QA intents.
        """
        d = classifier.classify("哪个国家面积最大")
        assert d.intent == Intent.CHAT  # known gap, should be SIMPLE_QA

    def test_simple_qa_length_limit(self, classifier):
        """Long messages shouldn't match simple QA even with question words."""
        long_msg = "为什么" + "a" * 60  # > 50 chars
        d = classifier.classify(long_msg)
        # Should fall through to CHAT, not SIMPLE_QA
        assert d.intent == Intent.CHAT


# ═══════════════════════════════════════════════════════════════════════
# Default / edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestDefaults:
    """Test fallback to CHAT intent."""

    def test_empty_message(self, classifier):
        d = classifier.classify("")
        assert d.intent == Intent.CHAT  # passthrough

    def test_whitespace_only(self, classifier):
        d = classifier.classify("   ")
        assert d.intent == Intent.CHAT

    def test_none_message(self, classifier):
        d = classifier.classify(None)
        assert d.intent == Intent.CHAT

    def test_generic_chat(self, classifier):
        """Unrecognized message goes to CHAT."""
        d = classifier.classify("给我讲个故事")
        assert d.intent == Intent.CHAT
        assert d.suggested_model == "large"
        assert d.skip_llm is False

    def test_complex_conversation_stays_chat(self, classifier):
        d = classifier.classify("你觉得未来的 AI 会发展成什么样？它会对社会产生什么影响？")
        assert d.intent == Intent.CHAT


# ═══════════════════════════════════════════════════════════════════════
# Layer 1 disabled
# ═══════════════════════════════════════════════════════════════════════

class TestLayer1Disabled:
    """When layer1 is disabled, all non-shortcut messages go to CHAT."""

    @pytest.fixture
    def classifier_no_l1(self):
        return IntentClassifier(enable_layer1=False)

    def test_greeting_goes_to_chat(self, classifier_no_l1):
        d = classifier_no_l1.classify("你好")
        assert d.intent == Intent.CHAT
        assert d.skip_llm is False

    def test_search_keywords_go_to_chat(self, classifier_no_l1):
        d = classifier_no_l1.classify("帮我搜索 Python 教程")
        assert d.intent == Intent.CHAT

    def test_shortcuts_still_work(self, classifier_no_l1):
        """Layer 0 (shortcuts) works regardless of layer1 setting."""
        d = classifier_no_l1.classify("/clear")
        assert d.intent == Intent.SHORTCUT
        assert d.skip_llm is True

        d2 = classifier_no_l1.classify("/search django tutorial")
        assert d2.intent == Intent.SEARCH
        assert d2.override_message == "django tutorial"


# ═══════════════════════════════════════════════════════════════════════
# Model hint API
# ═══════════════════════════════════════════════════════════════════════

class TestModelHints:
    """Test static model hint mapping."""

    @pytest.mark.parametrize("intent,expected_hint", [
        (Intent.SIMPLE_QA, "small"),
        (Intent.GREETING, "small"),
        (Intent.SEARCH, "small"),
        (Intent.SUMMARIZE, "medium"),
        (Intent.FILE_OP, "medium"),
        (Intent.SCHEDULE, "medium"),
        (Intent.MEMORY, "medium"),
        (Intent.CODE, "large"),
        (Intent.CHAT, "large"),
    ])
    def test_model_hints(self, intent, expected_hint):
        assert IntentClassifier.get_model_hint(intent) == expected_hint

    def test_shortcut_has_no_hint(self):
        assert IntentClassifier.get_model_hint(Intent.SHORTCUT) is None


# ═══════════════════════════════════════════════════════════════════════
# Shortcut listing
# ═══════════════════════════════════════════════════════════════════════

class TestShortcutListing:
    def test_list_shortcuts(self):
        shortcuts = IntentClassifier.list_shortcuts()
        labels = [s[1] for s in shortcuts]
        assert "搜索" in labels
        assert "文件操作" in labels
        assert "代码" in labels


# ═══════════════════════════════════════════════════════════════════════
# RoutingDecision DTO
# ═══════════════════════════════════════════════════════════════════════

class TestRoutingDecision:
    def test_passthrough(self):
        d = RoutingDecision.passthrough()
        assert d.intent == Intent.CHAT
        assert d.skip_llm is False
        assert d.direct_response is None

    def test_bypass(self):
        d = RoutingDecision.bypass(Intent.GREETING, "Hello!")
        assert d.intent == Intent.GREETING
        assert d.skip_llm is True
        assert d.direct_response == "Hello!"
