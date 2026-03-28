"""CLI 集成测试 - 测试 CLI 模式下的任务执行和恢复功能

测试场景：
1. CLI 模式任务执行：创建一次性任务（5秒后执行），运行应用，等待6秒，检查任务执行记录
2. 任务恢复测试：添加 Cron 任务，关闭应用，重新启动，检查任务是否恢复

注意：
- 使用真实的 SQLite 数据库（临时文件）
- 使用 subprocess 运行 CLI 应用
- 不使用 mock
- 不依赖 GUI
"""

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def check_scheduler_available():
    try:
        import importlib

        importlib.import_module("apscheduler.schedulers.background")
        importlib.import_module("apscheduler.jobstores.sqlalchemy")
        return True
    except Exception:
        return False


SCHEDULER_AVAILABLE = check_scheduler_available()


def create_temp_config(db_path: str, config_path: str) -> dict:
    config_data = {
        "llm": {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-3.5-turbo",
            "protocol": "openai",
        },
        "enable_tools": False,
        "memory": {"enabled": False},
        "scheduler": {
            "enabled": True,
            "max_workers": 2,
            "default_timezone": "local",
        },
    }

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

    return config_data


def test_cli_schedule_create_command(tmp_path):
    from llm_chat.storage import Storage
    from llm_chat.scheduler.models import Task, TaskType

    db_path = str(tmp_path / "test_cli_create.db")
    config_path = str(tmp_path / "config.yaml")

    create_temp_config(db_path, config_path)

    Storage._instance = None
    storage = Storage(db_path=db_path)

    task = Task(
        id="test-cli-create-001",
        name="CLI创建的任务",
        task_type=TaskType.LLM_CHAT,
        trigger_config={"cron": "30 9 * * *"},
        params={"message": "早安！"},
        enabled=True,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    storage.save_task(task)

    saved = storage.load_task(task.id)
    assert saved is not None
    assert saved.name == "CLI创建的任务"
    assert saved.task_type == TaskType.LLM_CHAT
    assert "message" in saved.params


@pytest.mark.skipif(
    not SCHEDULER_AVAILABLE,
    reason="APScheduler/SQLAlchemy not available or incompatible",
)
class TestCLISchedulerWithSubprocess:
    """需要完整调度器环境的集成测试"""

    pytestmark = pytest.mark.skipif(
        not SCHEDULER_AVAILABLE,
        reason="APScheduler/SQLAlchemy not available or incompatible",
    )

    @pytest.fixture(autouse=True)
    def setup_storage(self):
        if not SCHEDULER_AVAILABLE:
            pytest.skip("Scheduler not available")
        from llm_chat.storage import Storage

        Storage._instance = None
        yield
        Storage._instance = None

    def test_cli_one_time_task_execution(self, tmp_path):
        from llm_chat.storage import Storage
        from llm_chat.scheduler.models import Task, TaskType, TaskStatus

        db_path = str(tmp_path / "test_scheduler.db")
        config_path = str(tmp_path / "config.yaml")

        create_temp_config(db_path, config_path)

        Storage._instance = None
        storage = Storage(db_path=db_path)

        run_time = datetime.now() + timedelta(seconds=3)
        run_time_str = run_time.strftime("%Y-%m-%d %H:%M:%S")

        task = Task(
            id="test-one-time-task-001",
            name="测试一次性任务",
            task_type=TaskType.SYSTEM_MAINTENANCE,
            trigger_config={"date": run_time_str},
            params={"action": "vacuum_database"},
            enabled=True,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        storage.save_task(task)

        saved_task = storage.load_task(task.id)
        assert saved_task is not None
        assert saved_task.name == "测试一次性任务"

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent / "src")

        test_script = tmp_path / "run_scheduler.py"
        test_script.write_text(f'''
import os
import sys
import time

os.environ["VB_DB_PATH"] = "{db_path}"

from llm_chat.config import Config
from llm_chat.app import App
from llm_chat.storage import Storage

Storage._instance = None
Storage._db_path = "{db_path}"

config = Config.from_yaml("{config_path}")
app = App(config)

scheduler = app.get_scheduler()
if not scheduler:
    print("ERROR: Scheduler not available")
    sys.exit(1)

scheduler.start()
print("Scheduler started")

time.sleep(5)

storage = Storage("{db_path}")
executions = storage.load_executions("{task.id}")

if executions:
    print(f"Task executed: {{executions[0].status}}")
else:
    print("No execution record found")

scheduler.shutdown()
print("Scheduler shutdown")
''')

        result = subprocess.run(
            [sys.executable, str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            cwd=str(tmp_path),
        )

        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)

        assert "Scheduler started" in result.stdout

        Storage._instance = None
        storage = Storage(db_path=db_path)
        executions = storage.load_executions(task.id)

        assert len(executions) > 0, "任务应该有执行记录"
        assert executions[0].status == TaskStatus.COMPLETED, (
            f"任务应该成功完成，实际状态: {executions[0].status}"
        )

    def test_task_recovery_after_restart(self, tmp_path):
        from llm_chat.storage import Storage
        from llm_chat.scheduler.models import Task, TaskType

        db_path = str(tmp_path / "test_recovery.db")
        config_path = str(tmp_path / "config.yaml")

        create_temp_config(db_path, config_path)

        Storage._instance = None
        storage = Storage(db_path=db_path)

        cron_task = Task(
            id="test-cron-recovery-001",
            name="测试Cron任务恢复",
            task_type=TaskType.SYSTEM_MAINTENANCE,
            trigger_config={"cron": "0 * * * *"},
            params={"action": "cleanup_old_executions", "days": 30},
            enabled=True,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        storage.save_task(cron_task)

        saved_task = storage.load_task(cron_task.id)
        assert saved_task is not None

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent / "src")

        first_start_script = tmp_path / "first_start.py"
        first_start_script.write_text(f'''
import os
import sys
import time

os.environ["VB_DB_PATH"] = "{db_path}"

from llm_chat.config import Config
from llm_chat.app import App
from llm_chat.storage import Storage

Storage._instance = None
Storage._db_path = "{db_path}"

config = Config.from_yaml("{config_path}")
app = App(config)

scheduler = app.get_scheduler()
if not scheduler:
    print("ERROR: Scheduler not available")
    sys.exit(1)

scheduler.start()
print("First start: Scheduler started")

all_tasks = scheduler.get_all_tasks()
print(f"Loaded tasks: {{len(all_tasks)}}")
for t in all_tasks:
    print(f"  - {{t.id}}: {{t.name}}")

time.sleep(1)

scheduler.shutdown()
print("First start: Scheduler shutdown")
''')

        result1 = subprocess.run(
            [sys.executable, str(first_start_script)],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            cwd=str(tmp_path),
        )

        print("First start STDOUT:", result1.stdout)
        print("First start STDERR:", result1.stderr)

        assert "First start: Scheduler started" in result1.stdout
        assert "test-cron-recovery-001" in result1.stdout

        second_start_script = tmp_path / "second_start.py"
        second_start_script.write_text(f'''
import os
import sys
import time

os.environ["VB_DB_PATH"] = "{db_path}"

from llm_chat.config import Config
from llm_chat.app import App
from llm_chat.storage import Storage

Storage._instance = None
Storage._db_path = "{db_path}"

config = Config.from_yaml("{config_path}")
app = App(config)

scheduler = app.get_scheduler()
if not scheduler:
    print("ERROR: Scheduler not available")
    sys.exit(1)

scheduler.start()
print("Second start: Scheduler started")

all_tasks = scheduler.get_all_tasks()
print(f"Recovered tasks: {{len(all_tasks)}}")
for t in all_tasks:
    print(f"  - {{t.id}}: {{t.name}}")

time.sleep(1)

scheduler.shutdown()
print("Second start: Scheduler shutdown")
''')

        result2 = subprocess.run(
            [sys.executable, str(second_start_script)],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            cwd=str(tmp_path),
        )

        print("Second start STDOUT:", result2.stdout)
        print("Second start STDERR:", result2.stderr)

        assert "Second start: Scheduler started" in result2.stdout
        assert "test-cron-recovery-001" in result2.stdout

    def test_multiple_tasks_scheduling(self, tmp_path):
        from llm_chat.storage import Storage
        from llm_chat.scheduler.models import Task, TaskType

        db_path = str(tmp_path / "test_multi_tasks.db")
        config_path = str(tmp_path / "config.yaml")

        create_temp_config(db_path, config_path)

        Storage._instance = None
        storage = Storage(db_path=db_path)

        tasks = [
            Task(
                id="multi-task-001",
                name="Cron任务1",
                task_type=TaskType.SYSTEM_MAINTENANCE,
                trigger_config={"cron": "0 0 * * *"},
                params={"action": "cleanup_old_executions"},
                enabled=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            ),
            Task(
                id="multi-task-002",
                name="Cron任务2",
                task_type=TaskType.SYSTEM_MAINTENANCE,
                trigger_config={"cron": "0 12 * * *"},
                params={"action": "vacuum_database"},
                enabled=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            ),
            Task(
                id="multi-task-003",
                name="一次性任务",
                task_type=TaskType.SYSTEM_MAINTENANCE,
                trigger_config={
                    "date": (datetime.now() + timedelta(hours=1)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                },
                params={"action": "cleanup_old_executions"},
                enabled=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            ),
        ]

        for task in tasks:
            storage.save_task(task)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent / "src")

        test_script = tmp_path / "multi_tasks_test.py"
        test_script.write_text(f'''
import os
import sys
import time

os.environ["VB_DB_PATH"] = "{db_path}"

from llm_chat.config import Config
from llm_chat.app import App
from llm_chat.storage import Storage

Storage._instance = None
Storage._db_path = "{db_path}"

config = Config.from_yaml("{config_path}")
app = App(config)

scheduler = app.get_scheduler()
if not scheduler:
    print("ERROR: Scheduler not available")
    sys.exit(1)

scheduler.start()
print("Scheduler started")

all_tasks = scheduler.get_all_tasks()
print(f"Total tasks loaded: {{len(all_tasks)}}")
for t in all_tasks:
    print(f"  - {{t.id}}: {{t.name}} ({{t.task_type.value}})")

time.sleep(1)

scheduler.shutdown()
print("Scheduler shutdown")
''')

        result = subprocess.run(
            [sys.executable, str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            cwd=str(tmp_path),
        )

        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)

        assert "multi-task-001" in result.stdout
        assert "multi-task-002" in result.stdout
        assert "multi-task-003" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
