"""Common pytest fixtures for ember packages."""

import pytest
import sys
import os

if not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Ensure ember packages are on path
_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_base, "packages", "ember-core", "src"))
sys.path.insert(0, os.path.join(_base, "packages", "ember-agent", "src"))
sys.path.insert(0, os.path.join(_base, "src"))


@pytest.fixture(scope="session")
def qt_app():
    """整套 GUI 测试共享唯一 QApplication，避免原生 Qt 重建竞态。"""

    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        pytest.skip("PyQt6 is not installed")

    app = QApplication.instance() or QApplication([])
    yield app
    app.closeAllWindows()
    app.processEvents()


@pytest.fixture(scope="session", autouse=True)
def isolated_app_database(tmp_path_factory):
    """测试套件不能读写开发者真实的默认数据库。"""

    previous = os.environ.get("VB_DB_PATH")
    if previous is None:
        os.environ["VB_DB_PATH"] = str(tmp_path_factory.mktemp("vermilion-bird") / "app.db")
    # 一些 App 生命周期测试会刻意 mock Storage.__init__；先创建 schema，
    # 使这些测试不再隐式依赖开发者机器上的真实数据库。
    from llm_chat.storage import Storage

    Storage.set_instance(None)
    Storage(os.environ["VB_DB_PATH"])
    yield
    Storage.set_instance(None)
    if previous is None:
        os.environ.pop("VB_DB_PATH", None)
    else:
        os.environ["VB_DB_PATH"] = previous
