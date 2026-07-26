"""Optional frontend adapters must not inflate the core import surface."""

import importlib
import sys


def test_frontend_package_does_not_eagerly_import_gui():
    sys.modules.pop("llm_chat.frontends.gui", None)
    import llm_chat.frontends as frontends

    importlib.reload(frontends)

    assert "llm_chat.frontends.gui" not in sys.modules
    assert frontends.get_frontend("cli").name == "cli"


def test_feishu_package_does_not_eagerly_import_sdk_adapter():
    sys.modules.pop("llm_chat.frontends.feishu.adapter", None)
    import llm_chat.frontends.feishu as feishu

    importlib.reload(feishu)

    assert "llm_chat.frontends.feishu.adapter" not in sys.modules
