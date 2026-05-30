"""测试 knowledge_base skill 的 ReadKnowledgeTool 和 RememberKnowledgeTool"""

import shutil
import tempfile
from pathlib import Path

import pytest

from llm_chat.knowledge.storage import KnowledgeStorage
from llm_chat.skills.knowledge_base.skill import (
    KnowledgeBaseSkill,
    ReadKnowledgeTool,
    RememberKnowledgeTool,
    _get_storage as _original_get_storage,
)
import llm_chat.skills.knowledge_base.skill as skill_mod


@pytest.fixture
def temp_storage():
    """创建使用临时目录的 KnowledgeStorage。"""
    tmpdir = tempfile.mkdtemp(prefix="kbskill_test_")
    storage = KnowledgeStorage(knowledge_dir=tmpdir)
    # 注入临时 storage 到 skill 模块的 _get_storage
    original = skill_mod._get_storage
    skill_mod._get_storage = lambda: storage
    yield storage
    skill_mod._get_storage = original
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def populated_storage(temp_storage):
    """创建包含投资领域的 KnowledgeStorage。"""
    temp_storage.create_domain(
        "investment",
        "投资",
        "投资领域专业知识",
        keywords=["股票", "基金", "A股", "PE", "ROE", "定投"],
    )
    temp_storage.append_fact("investment", "A股估值用PE分位数", category="strategy")
    temp_storage.append_fact(
        "investment", "定投频率每月优于每周", category="strategy"
    )
    temp_storage.append_fact(
        "investment", "沪深300 ETF 管理费最低的是华泰柏瑞", category="reference"
    )
    # 也创建一个 machine-learning 领域
    temp_storage.create_domain(
        "machine-learning",
        "机器学习",
        "ML理论和实践",
        keywords=["深度学习", "PyTorch", "transformer"],
    )
    temp_storage.append_fact(
        "machine-learning",
        "PyTorch 2.0 torch.compile 可提速 30-50%",
        category="concept",
    )
    return temp_storage


# ============================================================================
# KnowledgeBaseSkill
# ============================================================================


class TestKnowledgeBaseSkill:
    def test_skill_metadata(self):
        skill = KnowledgeBaseSkill()
        assert skill.name == "knowledge_base"
        assert skill.version == "1.0.0"
        assert "领域知识管理" in skill.description

    def test_get_tools(self):
        skill = KnowledgeBaseSkill()
        tools = skill.get_tools()
        tool_names = [t.name for t in tools]
        assert "read_knowledge" in tool_names
        assert "remember_knowledge" in tool_names

    def test_registered_in_builtin(self):
        from llm_chat.skills.registry import get_builtin_skills

        skills = get_builtin_skills()
        assert "knowledge_base" in skills
        assert skills["knowledge_base"] == KnowledgeBaseSkill


# ============================================================================
# ReadKnowledgeTool
# ============================================================================


class TestReadKnowledgeTool:
    def test_tool_metadata(self):
        tool = ReadKnowledgeTool()
        assert tool.name == "read_knowledge"
        assert "加载指定领域的完整知识" in tool.description

    def test_parameters_schema(self):
        tool = ReadKnowledgeTool()
        schema = tool.get_parameters_schema()
        assert schema["type"] == "object"
        assert "domain" in schema["required"]

    def test_read_existing_domain(self, populated_storage):
        tool = ReadKnowledgeTool()
        result = tool.execute("investment")
        assert "领域知识：投资" in result
        assert "A股估值用PE分位数" in result
        assert "定投频率每月优于每周" in result

    def test_read_nonexistent_no_other_domains(self, temp_storage):
        """空目录下读取不存在的领域。"""
        tool = ReadKnowledgeTool()
        result = tool.execute("nonexistent")
        assert "不存在" in result
        assert "暂无任何领域知识" in result

    def test_read_nonexistent_with_other_domains(self, populated_storage):
        """有其他领域时读取不存在的领域 → 列出可用领域。"""
        tool = ReadKnowledgeTool()
        result = tool.execute("nonexistent")
        assert "不存在" in result
        assert "investment" in result
        assert "machine-learning" in result

    def test_read_returns_body_only(self, populated_storage):
        """验证返回不含 YAML frontmatter。"""
        tool = ReadKnowledgeTool()
        result = tool.execute("investment")
        # frontmatter 字段不在 body 中
        assert "name:" not in result
        assert "type:" not in result
        # 但 body 内容在
        assert "领域知识：投资" in result


# ============================================================================
# RememberKnowledgeTool
# ============================================================================


class TestRememberKnowledgeTool:
    def test_tool_metadata(self):
        tool = RememberKnowledgeTool()
        assert tool.name == "remember_knowledge"
        assert "领域专业知识存储" in tool.description

    def test_parameters_schema(self):
        tool = RememberKnowledgeTool()
        schema = tool.get_parameters_schema()
        assert schema["type"] == "object"
        required = schema["required"]
        assert "domain" in required
        assert "fact" in required

    def test_write_to_existing_domain(self, populated_storage):
        tool = RememberKnowledgeTool()
        result = tool.execute(
            "investment",
            "创业板波动率高于主板",
            category="concept",
        )
        assert "已记住" in result
        assert "investment" in result
        # 验证实际写入
        content = populated_storage.load_domain("investment")
        assert "创业板波动率高于主板" in content

    def test_write_creates_new_domain(self, temp_storage):
        tool = RememberKnowledgeTool()
        result = tool.execute(
            "cooking",
            "烘焙面包需要高筋面粉",
            category="experience",
            display_name="烹饪",
            description="烹饪与烘焙知识",
            keywords="烘焙,面包,高筋,面粉",
        )
        assert "已记住" in result
        assert "cooking" in result
        # 验证文件创建
        assert temp_storage.domain_exists("cooking")
        meta = temp_storage.get_domain_meta("cooking")
        assert meta.display_name == "烹饪"
        assert "烘焙" in meta.keywords
        assert "面包" in meta.keywords

    def test_write_auto_creates_without_display_name(self, temp_storage):
        """没有 display_name 时，用 domain 名作为显示名。"""
        tool = RememberKnowledgeTool()
        result = tool.execute("test_domain", "some fact", category="other")
        assert "已记住" in result
        assert temp_storage.domain_exists("test_domain")
        meta = temp_storage.get_domain_meta("test_domain")
        assert meta.display_name == "test_domain"

    def test_increments_fact_count(self, populated_storage):
        before = populated_storage.get_domain_meta("investment").fact_count
        tool = RememberKnowledgeTool()
        tool.execute("investment", "新知识点", category="other")
        after = populated_storage.get_domain_meta("investment").fact_count
        assert after == before + 1

    def test_write_different_categories(self, populated_storage):
        tool = RememberKnowledgeTool()
        for cat in ["concept", "strategy", "experience", "reference"]:
            result = tool.execute(
                "investment", f"{cat} 知识点", category=cat
            )
            assert "已记住" in result

        content = populated_storage.load_domain("investment")
        assert "[概念]" in content
        assert "[策略]" in content
        assert "[经验]" in content
        assert "[参考]" in content

    def test_duplicate_domain_creation_is_idempotent(self, populated_storage):
        """用已有领域名+display_name 参数写入 → 不重复创建，直接追加。"""
        tool = RememberKnowledgeTool()
        result = tool.execute(
            "investment",
            "新增知识点",
            category="other",
            display_name="应该被忽略",  # 领域已存在，忽略此参数
            description="应该被忽略",
            keywords="应该,被,忽略",
        )
        assert "已记住" in result
        meta = populated_storage.get_domain_meta("investment")
        # display_name 不变
        assert meta.display_name == "投资"
        # keywords 不变
        assert "股票" in meta.keywords
        assert "应该" not in meta.keywords


# ============================================================================
# 集成测试
# ============================================================================


class TestIntegration:
    def test_write_then_read(self, temp_storage):
        writer = RememberKnowledgeTool()
        reader = ReadKnowledgeTool()

        # 写入
        writer.execute(
            "python",
            "Python 3.12 的 f-string 支持嵌套引号",
            category="concept",
            display_name="Python",
            keywords="Python,CPython,PyPy",
        )

        # 读取
        result = reader.execute("python")
        assert "Python 3.12" in result
        assert "f-string" in result

    def test_read_after_multiple_writes(self, populated_storage):
        writer = RememberKnowledgeTool()
        reader = ReadKnowledgeTool()

        # 追加 3 条
        facts = ["事实A", "事实B", "事实C"]
        for f in facts:
            writer.execute("investment", f, category="other")

        result = reader.execute("investment")
        for f in facts:
            assert f in result

    def test_cross_domain_isolation(self, populated_storage):
        """不同领域的知识点互不干扰。"""
        reader = ReadKnowledgeTool()

        inv = reader.execute("investment")
        ml = reader.execute("machine-learning")

        assert "沪深300" in inv
        assert "沪深300" not in ml

        assert "PyTorch" in ml
        assert "PyTorch" not in inv

    def test_list_available_domains_includes_all(self, populated_storage):
        """读取不存在的领域时，列出所有可用领域。"""
        reader = ReadKnowledgeTool()
        result = reader.execute("zzz")

        assert "investment" in result
        assert "投资" in result
        assert "machine-learning" in result
        assert "机器学习" in result
