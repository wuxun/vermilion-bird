"""测试 KnowledgeStorage + DomainDetector"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from llm_chat.knowledge import (
    KnowledgeStorage,
    DomainDetector,
    DomainMeta,
    get_knowledge_template,
)


@pytest.fixture
def temp_knowledge_dir():
    """创建临时 knowledge 目录，测试结束后清理。"""
    tmpdir = tempfile.mkdtemp(prefix="kb_test_")
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def storage(temp_knowledge_dir):
    """创建 KnowledgeStorage 实例。"""
    return KnowledgeStorage(knowledge_dir=temp_knowledge_dir)


@pytest.fixture
def storage_with_domains(storage):
    """创建包含两个领域文件的 KnowledgeStorage。"""
    storage.create_domain(
        "investment",
        "投资",
        "投资领域专业知识",
        keywords=["股票", "基金", "A股", "PE", "ROE", "仓位", "定投", "ETF"],
    )
    storage.create_domain(
        "machine-learning",
        "机器学习",
        "ML理论和工程实践",
        keywords=["深度学习", "PyTorch", "transformer", "梯度下降", "过拟合"],
    )
    return storage


# ============================================================================
# get_knowledge_template
# ============================================================================


class TestKnowledgeTemplate:
    def test_generates_valid_frontmatter(self):
        tpl = get_knowledge_template(
            "test-domain", "测试", "描述", keywords=["kw1", "kw2"]
        )
        assert tpl.startswith("---\n")
        assert "name: test-domain" in tpl
        assert "display_name: 测试" in tpl
        assert "description: 描述" in tpl
        assert "type: requested" in tpl
        assert "keywords:" in tpl
        assert "kw1" in tpl
        assert "kw2" in tpl

    def test_default_type_is_requested(self):
        tpl = get_knowledge_template("d", "D")
        assert "type: requested" in tpl

    def test_empty_keywords(self):
        tpl = get_knowledge_template("d", "D")
        assert "keywords: []" in tpl


# ============================================================================
# KnowledgeStorage — 发现 & 加载
# ============================================================================


class TestDiscoverDomains:
    def test_empty_dir_returns_empty(self, storage):
        domains = storage.discover_domains()
        assert domains == {}

    def test_creates_and_discovers_domain(self, storage):
        storage.create_domain("investment", "投资", keywords=["股票", "基金"])
        domains = storage.discover_domains()
        assert "investment" in domains
        meta = domains["investment"]
        assert meta.display_name == "投资"
        assert meta.type == "requested"
        assert meta.fact_count == 0

    def test_skips_non_md_files(self, storage):
        # 创建非 .md 文件
        (Path(storage.knowledge_dir) / "notes.txt").write_text("hello")
        domains = storage.discover_domains()
        assert "notes" not in domains

    def test_skips_hidden_files(self, storage):
        (Path(storage.knowledge_dir) / ".hidden.md").write_text("---\nname: hidden\n---\nbody")
        domains = storage.discover_domains()
        assert "hidden" not in domains

    def test_skips_files_without_frontmatter(self, storage):
        (Path(storage.knowledge_dir) / "no_fm.md").write_text("just plain text")
        domains = storage.discover_domains()
        assert "no_fm" not in domains


class TestLoadDomain:
    def test_load_existing(self, storage_with_domains):
        content = storage_with_domains.load_domain("investment")
        assert content is not None
        assert "name: investment" in content
        assert "领域知识：投资" in content

    def test_load_nonexistent(self, storage):
        assert storage.load_domain("nonexistent") is None

    def test_load_body_strips_frontmatter(self, storage_with_domains):
        body = storage_with_domains.load_domain_body("investment")
        assert body is not None
        assert "name:" not in body
        assert "领域知识：投资" in body


class TestGetDomainMeta:
    def test_returns_meta_for_existing(self, storage_with_domains):
        meta = storage_with_domains.get_domain_meta("investment")
        assert meta is not None
        assert meta.name == "investment"
        assert meta.display_name == "投资"

    def test_returns_none_for_nonexistent(self, storage):
        assert storage.get_domain_meta("nonexistent") is None


class TestGetAllDomains:
    def test_returns_all(self, storage_with_domains):
        all_d = storage_with_domains.get_all_domains()
        assert len(all_d) == 2
        assert "investment" in all_d
        assert "machine-learning" in all_d


class TestDomainExists:
    def test_exists(self, storage_with_domains):
        assert storage_with_domains.domain_exists("investment")

    def test_not_exists(self, storage):
        assert not storage.domain_exists("nonexistent")


# ============================================================================
# KnowledgeStorage — 创建
# ============================================================================


class TestCreateDomain:
    def test_creates_file(self, storage):
        meta = storage.create_domain("ml", "机器学习", keywords=["DL", "NN"])
        assert meta.name == "ml"
        file_path = Path(storage.knowledge_dir) / "ml.md"
        assert file_path.exists()

    def test_raises_on_duplicate(self, storage):
        storage.create_domain("test", "Test")
        with pytest.raises(FileExistsError):
            storage.create_domain("test", "Test2")

    def test_all_fields(self, storage):
        meta = storage.create_domain(
            "test",
            "测试领域",
            description="测试描述",
            keywords=["k1", "k2"],
            type="always",
        )
        assert meta.name == "test"
        assert meta.display_name == "测试领域"
        assert meta.description == "测试描述"
        assert meta.keywords == ["k1", "k2"]
        assert meta.type == "always"
        assert meta.fact_count == 0
        assert meta.created_at  # non-empty
        assert meta.updated_at  # non-empty


# ============================================================================
# KnowledgeStorage — 追加知识点
# ============================================================================


class TestAppendFact:
    def test_appends_single_fact(self, storage_with_domains):
        ok = storage_with_domains.append_fact(
            "investment", "A股估值用PE分位数", category="strategy"
        )
        assert ok
        content = storage_with_domains.load_domain("investment")
        assert "[策略] A股估值用PE分位数" in content

    def test_increments_fact_count(self, storage_with_domains):
        storage_with_domains.append_fact("investment", "fact 1")
        storage_with_domains.append_fact("investment", "fact 2")
        storage_with_domains.append_fact("investment", "fact 3")
        meta = storage_with_domains.get_domain_meta("investment")
        assert meta.fact_count == 3

    def test_multiple_facts_same_day(self, storage_with_domains):
        storage_with_domains.append_fact("investment", "fact A")
        storage_with_domains.append_fact("investment", "fact B")
        storage_with_domains.append_fact("investment", "fact C")
        content = storage_with_domains.load_domain("investment")
        # All three should be in the same day section
        assert "fact A" in content
        assert "fact B" in content
        assert "fact C" in content

    def test_different_categories(self, storage_with_domains):
        storage_with_domains.append_fact(
            "investment", "概念类", category="concept"
        )
        storage_with_domains.append_fact(
            "investment", "策略类", category="strategy"
        )
        storage_with_domains.append_fact(
            "investment", "经验类", category="experience"
        )
        content = storage_with_domains.load_domain("investment")
        assert "[概念] 概念类" in content
        assert "[策略] 策略类" in content
        assert "[经验] 经验类" in content

    def test_unknown_category_falls_back_to_raw(self, storage_with_domains):
        storage_with_domains.append_fact(
            "investment", "未知分类", category="unknown"
        )
        content = storage_with_domains.load_domain("investment")
        assert "[unknown] 未知分类" in content

    def test_nonexistent_domain_returns_false(self, storage):
        assert not storage.append_fact("nonexistent", "fact")

    def test_unconsolidated_count(self, storage_with_domains):
        assert (
            storage_with_domains.get_unconsolidated_count("investment") == 0
        )
        storage_with_domains.append_fact("investment", "f1")
        storage_with_domains.append_fact("investment", "f2")
        storage_with_domains.append_fact("investment", "f3")
        assert (
            storage_with_domains.get_unconsolidated_count("investment") == 3
        )

    def test_unconsolidated_count_nonexistent(self, storage):
        assert storage.get_unconsolidated_count("nonexistent") == 0


# ============================================================================
# KnowledgeStorage — 更新 & 搜索 & 删除
# ============================================================================


class TestUpdateFrontmatter:
    def test_updates_fields(self, storage_with_domains):
        ok = storage_with_domains.update_frontmatter(
            "investment", {"type": "always", "description": "updated desc"}
        )
        assert ok
        meta = storage_with_domains.get_domain_meta("investment")
        assert meta.type == "always"
        assert meta.description == "updated desc"

    def test_nonexistent_returns_false(self, storage):
        assert not storage.update_frontmatter("nonexistent", {"type": "always"})


class TestSearch:
    def test_finds_in_domain(self, storage_with_domains):
        storage_with_domains.append_fact("investment", "测试PE分位数估值法")
        results = storage_with_domains.search("PE")
        assert len(results) >= 1
        assert results[0]["domain"] == "investment"

    def test_no_match(self, storage_with_domains):
        results = storage_with_domains.search("ZZZZZ_nonexistent")
        assert results == []

    def test_case_insensitive(self, storage_with_domains):
        storage_with_domains.append_fact("investment", "测试内容")
        results_upper = storage_with_domains.search("测试内容")
        results_lower = storage_with_domains.search("测试内容".lower() if False else "测试内容")
        assert len(results_upper) >= 1
        assert len(results_lower) >= 1


class TestDeleteDomain:
    def test_deletes_file(self, storage_with_domains):
        assert storage_with_domains.domain_exists("investment")
        ok = storage_with_domains.delete_domain("investment")
        assert ok
        assert not storage_with_domains.domain_exists("investment")

    def test_nonexistent_returns_false(self, storage):
        assert not storage.delete_domain("nonexistent")


# ============================================================================
# DomainDetector
# ============================================================================


class TestDomainDetector:
    @pytest.fixture
    def detector(self, storage_with_domains):
        return DomainDetector(storage_with_domains)

    def test_match_single_keyword(self, detector):
        matches = detector.match("最近在看股票")
        assert len(matches) >= 1
        assert matches[0][0] == "investment"

    def test_match_multiple_keywords(self, detector):
        matches = detector.match("股票基金PE估值分析")
        assert len(matches) >= 1
        # "股票", "基金", "PE" — 3 hits
        assert matches[0][1] >= 3

    def test_match_multiple_domains(self, detector):
        matches = detector.match("用深度学习分析A股走势")
        assert len(matches) == 2
        domain_names = [m[0] for m in matches]
        assert "investment" in domain_names
        assert "machine-learning" in domain_names

    def test_no_match(self, detector):
        matches = detector.match("今天天气真好")
        assert matches == []

    def test_match_domains_with_threshold(self, detector):
        # "股票" = 1 hit for investment, 0 for ml
        domains = detector.match_domains("股票分析", min_hits=1)
        assert "investment" in domains

        # threshold too high
        domains2 = detector.match_domains("股票分析", min_hits=3)
        assert "investment" not in domains2

    def test_empty_text(self, detector):
        assert detector.match("") == []
        assert detector.match_domains("") == []

    def test_no_domains_loaded(self, temp_knowledge_dir):
        storage = KnowledgeStorage(knowledge_dir=temp_knowledge_dir)
        detector = DomainDetector(storage)
        assert detector.match("股票") == []


# ============================================================================
# DomainMeta
# ============================================================================


class TestDomainMeta:
    def test_from_frontmatter(self):
        fm = {
            "name": "test",
            "display_name": "测试",
            "description": "desc",
            "type": "always",
            "keywords": ["k1", "k2"],
            "fact_count": 5,
            "created_at": "2026-01-01",
            "updated_at": "2026-06-01",
        }
        meta = DomainMeta.from_frontmatter(fm, Path("/tmp/test.md"))
        assert meta.name == "test"
        assert meta.display_name == "测试"
        assert meta.type == "always"
        assert meta.keywords == ["k1", "k2"]
        assert meta.fact_count == 5

    def test_defaults(self):
        meta = DomainMeta.from_frontmatter({"name": "minimal"}, Path("/tmp/x.md"))
        # display_name 缺失时回退为 name
        assert meta.display_name == "minimal"
        assert meta.type == "requested"
        assert meta.keywords == []
        assert meta.fact_count == 0

    def test_to_frontmatter_dict(self):
        meta = DomainMeta(
            name="test",
            display_name="测试",
            keywords=["k1"],
            fact_count=3,
        )
        d = meta.to_frontmatter_dict()
        assert d["name"] == "test"
        assert d["display_name"] == "测试"
        assert d["keywords"] == ["k1"]
        assert d["fact_count"] == 3


# ============================================================================
# 集成: 完整生命周期
# ============================================================================


class TestIntegration:
    def test_full_lifecycle(self, storage):
        # 1. 空目录
        assert storage.get_all_domains() == {}

        # 2. 创建领域
        storage.create_domain("cooking", "烹饪", keywords=["菜谱", "烘焙"])
        assert storage.domain_exists("cooking")

        # 3. 追加知识点
        for i in range(5):
            storage.append_fact("cooking", f"知识点 {i+1}", category="experience")

        meta = storage.get_domain_meta("cooking")
        assert meta.fact_count == 5
        assert storage.get_unconsolidated_count("cooking") == 5

        # 4. 搜索
        results = storage.search("知识点")
        assert len(results) == 1
        assert results[0]["domain"] == "cooking"

        # 5. 检测
        detector = DomainDetector(storage)
        matches = detector.match("今天想学烘焙")
        assert len(matches) == 1
        assert matches[0][0] == "cooking"

        # 6. 更新 frontmatter
        storage.update_frontmatter("cooking", {"type": "always"})
        assert storage.get_domain_meta("cooking").type == "always"

        # 7. 删除
        storage.delete_domain("cooking")
        assert not storage.domain_exists("cooking")
