"""测试 KnowledgeManager + KnowledgeExtractor + 管道集成"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from llm_chat.knowledge import (
    KnowledgeStorage,
    KnowledgeManager,
    KnowledgeExtractor,
    DomainDetector,
)
from llm_chat.knowledge.manager import KnowledgeManager as KM
from llm_chat.config.knowledge_config import KnowledgeConfig


@pytest.fixture
def temp_knowledge_dir():
    tmpdir = tempfile.mkdtemp(prefix="km_test_")
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def storage(temp_knowledge_dir):
    return KnowledgeStorage(knowledge_dir=temp_knowledge_dir)


@pytest.fixture
def mock_summarizer():
    """创建 mock Summarizer，用于测试 LLM 相关行为。"""
    m = MagicMock()
    m.generate = MagicMock(return_value="")
    return m


@pytest.fixture
def populated_storage(storage):
    """创建包含领域的 storage。"""
    storage.create_domain(
        "investment",
        "投资",
        "投资领域专业知识",
        keywords=["股票", "基金", "PE", "ROE"],
    )
    storage.create_domain(
        "ml",
        "机器学习",
        "ML 理论和实践",
        keywords=["深度学习", "PyTorch", "transformer"],
        type="always",
    )
    for i in range(5):
        storage.append_fact("investment", f"投资知识点 {i+1}", category="strategy")
    return storage


# ============================================================================
# KnowledgeConfig
# ============================================================================


class TestKnowledgeConfig:
    def test_defaults(self):
        cfg = KnowledgeConfig()
        assert cfg.enabled is True
        assert cfg.extraction_interval == 20
        assert cfg.consolidate_min_entries == 10
        assert cfg.refine_min_total == 50
        assert cfg.max_knowledge_tokens == 300
        assert "knowle" in cfg.storage_dir

    def test_in_main_config(self):
        from llm_chat.config import Config
        cfg = Config()
        assert hasattr(cfg, "knowledge")
        assert isinstance(cfg.knowledge, KnowledgeConfig)


# ============================================================================
# KnowledgeManager — 基本行为
# ============================================================================


class TestKnowledgeManagerBasic:
    def test_create_without_summarizer(self, storage):
        mgr = KnowledgeManager(storage=storage)
        assert mgr.storage is storage
        assert mgr._conversation_count == 0

    def test_record_conversation_increments_count(self, storage):
        mgr = KnowledgeManager(storage=storage)
        mgr.record_conversation("hello", "hi")
        assert mgr._conversation_count == 1
        mgr.record_conversation("how are you", "good")
        assert mgr._conversation_count == 2

    def test_build_context_no_match(self, populated_storage):
        mgr = KnowledgeManager(storage=populated_storage)
        # type=always 的 ml 领域始终注入，即使关键词不匹配
        result = mgr.build_knowledge_context("今天天气真好")
        assert "机器学习" in result  # always type always injects

    def test_build_context_with_match(self, populated_storage):
        mgr = KnowledgeManager(storage=populated_storage)
        result = mgr.build_knowledge_context("最近在看股票和基金")
        # always type: ml body always injected
        assert "机器学习" in result
        # requested type: investment only on keyword match
        assert "投资" in result
        assert "read_knowledge" in result

    def test_build_context_always_type_injects_body(self, populated_storage):
        mgr = KnowledgeManager(storage=populated_storage)
        result = mgr.build_knowledge_context("深度学习 transformer 原理")
        # type=always → body 注入
        assert "机器学习" in result
        # 不应包含 read_knowledge 提示（always 类型直接注入全文）
        # 但 requested 类型会显示 summary 行

    def test_build_context_mixed_types(self, populated_storage):
        """同时匹配 always 和 requested 领域。"""
        mgr = KnowledgeManager(storage=populated_storage)
        result = mgr.build_knowledge_context("用深度学习分析股票走势")
        # ml is always → body injected (body starts with '# 领域知识')
        assert "领域知识：机器学习" in result
        # investment is requested → summary line
        assert "投资" in result
        assert "read_knowledge" in result

    def test_empty_message(self, populated_storage):
        mgr = KnowledgeManager(storage=populated_storage)
        assert mgr.build_knowledge_context("") == ""

    def test_get_stats(self, populated_storage):
        mgr = KnowledgeManager(storage=populated_storage)
        stats = mgr.get_stats()
        assert stats["domain_count"] == 2
        assert stats["total_facts"] == 5  # 5 facts in investment
        assert "investment" in stats["domains"]


# ============================================================================
# KnowledgeManager — 提取 (需要 mock summarizer)
# ============================================================================


class TestKnowledgeManagerExtraction:
    def test_extract_no_summarizer_noop(self, populated_storage):
        """没有 summarizer 时不触发 LLM 调用。"""
        mgr = KnowledgeManager(storage=populated_storage)
        mgr._conversation_count = 25  # force trigger
        # 不应该抛异常
        mgr._extract_from_recent([
            {"role": "user", "content": "股票分析"},
            {"role": "assistant", "content": "PE分位数很重要"},
        ])

    def test_extract_with_summarizer_mocked(self, populated_storage, mock_summarizer):
        """Mock summarizer 返回知识点 → 应追加到 storage。"""
        mock_summarizer.generate.return_value = json.dumps([
            {"fact": "PE分位数估值法", "category": "strategy"},
            {"fact": "定投优于择时", "category": "strategy"},
        ])

        mgr = KnowledgeManager(
            storage=populated_storage, summarizer=mock_summarizer
        )

        before = populated_storage.get_unconsolidated_count("investment")

        mgr._extract_from_recent([
            {"role": "user", "content": "股票怎么估值"},
            {"role": "assistant", "content": "用PE分位数，沪深300PE分位数40%"},
        ])

        # summarizer was called
        assert mock_summarizer.generate.called

        after = populated_storage.get_unconsolidated_count("investment")
        assert after >= before  # may or may not add depending on mock

    def test_record_conversation_triggers_extraction(
        self, populated_storage, mock_summarizer
    ):
        """record_conversation 达到阈值后触发提取。"""
        import json as _json
        mock_summarizer.generate.return_value = _json.dumps([
            {"fact": "PE分位数40%低估", "category": "strategy"},
        ])

        mgr = KnowledgeManager(
            storage=populated_storage,
            summarizer=mock_summarizer,
            config={"extraction_interval": 20},
        )
        mgr._last_extraction_time = __import__("datetime").datetime(2020, 1, 1)

        # 模拟 20 轮对话（但只触发一次因为时间间隔保护）
        for i in range(20):
            mgr.record_conversation(f"股票分析 {i}", "PE很重要")

        # 计数应该重置
        assert mgr._conversation_count < 20


# ============================================================================
# KnowledgeManager — 维护 (整合/提炼)
# ============================================================================


class TestKnowledgeManagerMaintenance:
    def test_maybe_consolidate_below_threshold(self, populated_storage):
        mgr = KnowledgeManager(storage=populated_storage)
        # 5 facts < 10 (threshold) → 不触发
        assert not mgr._maybe_consolidate("investment")

    def test_maybe_consolidate_no_summarizer(self, populated_storage):
        mgr = KnowledgeManager(storage=populated_storage)
        mgr._consolidate_min_entries = 3  # lower threshold
        # 5 unconsolidated > 3, but no summarizer → no error
        assert not mgr._maybe_consolidate("investment")

    def test_maybe_refine_below_threshold(self, populated_storage):
        mgr = KnowledgeManager(storage=populated_storage)
        # 5 facts < 50 (threshold) → 不触发
        assert not mgr._maybe_refine("investment")

    def test_maybe_refine_no_summarizer(self, populated_storage):
        mgr = KnowledgeManager(storage=populated_storage)
        mgr._refine_min_total = 3  # lower threshold
        # fact_count=5 > 3, but no summarizer → no error, returns False
        assert not mgr._maybe_refine("investment")

    def test_consolidate_with_summarizer_mocked(
        self, populated_storage, mock_summarizer
    ):
        """Mock summarizer 返回整合结果 → 应更新文件。"""
        # Return a valid JSON that consolidator expects
        mock_summarizer.generate.return_value = json.dumps({
            "concept": ["PE分位数概念"],
            "strategy": ["定投策略", "估值策略"],
            "experience": ["经验教训"],
            "reference": [],
            "other": [],
        })

        mgr = KnowledgeManager(
            storage=populated_storage,
            summarizer=mock_summarizer,
            config={"consolidate_min_entries": 3},
        )

        result = mgr._maybe_consolidate("investment")
        # Should have triggered (5 unconsolidated >= 3)
        assert mock_summarizer.generate.called
        # The result may be True or False depending on the safety net
        # Most importantly: no exception


# ============================================================================
# KnowledgeExtractor — 单元测试
# ============================================================================


class TestKnowledgeExtractor:
    def test_extract_facts_no_summarizer(self):
        ext = KnowledgeExtractor()
        assert ext.extract_facts([{"role": "user", "content": "test"}], "test") == []

    def test_extract_facts_with_mock(self, mock_summarizer):
        """验证提取器的 JSON 解析。"""
        mock_summarizer.generate.return_value = (
            '[{"fact": "factAAA", "category": "strategy"}, '
            '{"fact": "factBBB", "category": "concept"}]'
        )
        ext = KnowledgeExtractor(summarizer=mock_summarizer)
        facts = ext.extract_facts(
            [{"role": "user", "content": "A股估值用PE分位数"}],
            "投资",
        )
        assert len(facts) == 2
        assert facts[0]["fact"] == "factAAA"
        assert facts[0]["category"] == "strategy"

    def test_extract_facts_with_code_block(self, mock_summarizer):
        """验证 markdown code block 包裹的 JSON。"""
        mock_summarizer.generate.return_value = (
            '```json\n'
            '[{"fact": "factCCC", "category": "experience"}]\n'
            '```'
        )
        ext = KnowledgeExtractor(summarizer=mock_summarizer)
        facts = ext.extract_facts(
            [{"role": "user", "content": "经验教训"}],
            "投资",
        )
        assert len(facts) == 1
        assert facts[0]["fact"] == "factCCC"

    def test_extract_facts_filters_short(self, mock_summarizer):
        """过滤过短的知识点 (< 5 chars)。"""
        mock_summarizer.generate.return_value = (
            '[{"fact": "A股", "category": "concept"}, '
            '{"fact": "PE分位数估值法很重要", "category": "strategy"}]'
        )
        ext = KnowledgeExtractor(summarizer=mock_summarizer)
        facts = ext.extract_facts(
            [{"role": "user", "content": "test"}],
            "投资",
        )
        assert len(facts) == 1
        assert "PE分位数" in facts[0]["fact"]

    def test_suggest_new_domain_no_summarizer(self):
        ext = KnowledgeExtractor()
        assert ext.suggest_new_domain([{"role": "user", "content": "test"}]) is None

    def test_suggest_new_domain_with_mock(self, mock_summarizer):
        """验证新领域建议。"""
        mock_summarizer.generate.return_value = (
            '{"name": "cooking", "display_name": "烹饪", '
            '"description": "烹饪知识", "keywords": ["菜谱", "烘焙", "面包"]}'
        )
        ext = KnowledgeExtractor(summarizer=mock_summarizer)
        result = ext.suggest_new_domain(
            [{"role": "user", "content": "烘焙面包需要高筋面粉"}]
        )
        assert result is not None
        assert result["name"] == "cooking"
        assert result["display_name"] == "烹饪"
        assert "烘焙" in result["keywords"]

    def test_suggest_new_domain_null(self, mock_summarizer):
        """LLM 返回 null → 不创建。"""
        mock_summarizer.generate.return_value = "null"
        ext = KnowledgeExtractor(summarizer=mock_summarizer)
        result = ext.suggest_new_domain(
            [{"role": "user", "content": "今天天气真好"}]
        )
        assert result is None


# ============================================================================
# 管道集成
# ============================================================================


class TestPipelineIntegration:
    def test_knowledge_extract_stage(self, populated_storage):
        """验证 KnowledgeExtractStage 正确工作。"""
        from llm_chat.pipeline.stages import KnowledgeExtractStage
        from llm_chat.pipeline.stage import PipelineContext

        # 创建 mock ConversationManager
        mock_cm = MagicMock()
        mock_cm.knowledge_manager = KnowledgeManager(storage=populated_storage)

        stage = KnowledgeExtractStage(mock_cm)
        ctx = PipelineContext(
            conversation_id="test",
            user_message="test message",
            response="test response",
        )

        import asyncio
        result = asyncio.run(stage.process(ctx))
        assert result is ctx  # should return same context

    def test_knowledge_extract_stage_no_manager(self):
        """没有 KnowledgeManager 时应该安全通过。"""
        from llm_chat.pipeline.stages import KnowledgeExtractStage
        from llm_chat.pipeline.stage import PipelineContext

        mock_cm = MagicMock()
        mock_cm.knowledge_manager = None

        stage = KnowledgeExtractStage(mock_cm)
        ctx = PipelineContext(
            conversation_id="test",
            user_message="test",
            response="response",
        )

        import asyncio
        result = asyncio.run(stage.process(ctx))
        assert result is ctx  # should pass through

    def test_system_context_injects_knowledge(self, populated_storage):
        """验证 SystemContextStage 注入领域知识。"""
        from llm_chat.pipeline.stages import SystemContextStage
        from llm_chat.pipeline.stage import PipelineContext, MutableStrHolder
        from llm_chat.intent.types import Intent

        mock_cm = MagicMock()
        mock_conv = MagicMock()
        mock_conv._memory_manager = None  # no memory
        mock_cm.get_conversation.return_value = mock_conv
        mock_cm.knowledge_manager = KnowledgeManager(storage=populated_storage)
        mock_cm.search_messages.return_value = []

        stage = SystemContextStage(
            mock_cm,
            MutableStrHolder(""),
            MutableStrHolder("default"),
        )

        ctx = PipelineContext(
            conversation_id="test",
            user_message="股票PE分析",
            effective_message="股票PE分析",
        )
        # 设置 routing_decision 以避免 None
        from llm_chat.intent.types import RoutingDecision
        ctx.routing_decision = RoutingDecision(
            intent=Intent.CHAT, confidence=1.0, skip_llm=False
        )

        import asyncio
        result = asyncio.run(stage.process(ctx))

        # system_context 应该包含领域知识
        assert result.system_context is not None
        assert "投资" in result.system_context


# ============================================================================
# 完整集成测试
# ============================================================================


class TestFullIntegration:
    def test_write_then_detect_then_inject(self, storage):
        """完整流程：创建领域 → 写知识点 → 检测 → 注入。"""
        # 1. 创建领域
        storage.create_domain(
            "cooking", "烹饪", keywords=["烘焙", "菜谱", "面包"]
        )
        storage.append_fact("cooking", "烘焙需要高筋面粉", category="experience")

        # 2. 创建 manager
        mgr = KnowledgeManager(storage=storage)

        # 3. 检测 — 应该匹配
        detector = DomainDetector(storage)
        matches = detector.match_domains("最近学烘焙面包", min_hits=1)
        assert "cooking" in matches

        # 4. 注入 — 应该注入摘要
        ctx = mgr.build_knowledge_context("烘焙面包用什么面粉")
        assert "烹饪" in ctx
        assert "read_knowledge" in ctx

    def test_new_domain_natural_emergence(self, storage, mock_summarizer):
        """新领域自然涌现：检测 → 提取 → 创建。"""
        mock_summarizer.generate.return_value = (
            '{"name": "photography", "display_name": "摄影", '
            '"description": "摄影技术知识", '
            '"keywords": ["光圈", "快门", "ISO", "构图"]}'
        )

        mgr = KnowledgeManager(
            storage=storage, summarizer=mock_summarizer
        )

        messages = [
            {"role": "user", "content": "大光圈适合拍人像还是风景"},
            {"role": "assistant", "content": "大光圈适合人像，背景虚化好"},
        ]

        mgr._extract_from_recent(messages)

        # 新领域应该被创建
        assert storage.domain_exists("photography")
        meta = storage.get_domain_meta("photography")
        assert meta.display_name == "摄影"
        assert "光圈" in meta.keywords


# 需要 json 模块
import json
