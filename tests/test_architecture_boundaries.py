"""防止三层架构在后续迭代中发生反向依赖。"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _imports_under(root: Path):
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield path, alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                yield path, node.module


def _assert_no_forbidden_imports(root: Path, forbidden):
    violations = [
        f"{path.relative_to(ROOT)} -> {module}"
        for path, module in _imports_under(root)
        if any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden)
    ]
    assert violations == []


def test_ember_core_has_no_agent_application_or_llm_framework_dependency():
    _assert_no_forbidden_imports(
        ROOT / "packages" / "ember-core" / "src",
        {"ember_agent", "llm_chat", "langchain", "langgraph"},
    )


def test_ember_agent_does_not_depend_on_desktop_application():
    _assert_no_forbidden_imports(
        ROOT / "packages" / "ember-agent" / "src",
        {"llm_chat"},
    )


def test_product_domain_services_do_not_depend_on_frontends_or_llm_client():
    for package in ("work", "workflows"):
        _assert_no_forbidden_imports(
            ROOT / "src" / "llm_chat" / package,
            {
                "PyQt6",
                "llm_chat.frontends",
                "llm_chat.client",
                "llm_chat.chat_core_graph",
            },
        )
