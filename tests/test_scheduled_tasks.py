"""Tests for scheduled task storage operations (digest + executions)."""

import os
import json
import tempfile
import pytest
from datetime import date
from unittest.mock import MagicMock, patch


# ── Tests for daily_digest (StorageDigestMixin) ──


class TestDailyDigest:
    @pytest.fixture
    def storage(self, tmp_path):
        """Create a Storage instance with temp DB."""
        from llm_chat.storage import Storage

        db_path = tmp_path / "test.db"
        s = Storage(db_path=str(db_path))
        yield s

    def test_save_and_get_by_source(self, storage):
        """Multiple digests per day, filtered by source."""
        today = date.today().isoformat()

        # Save two different tasks' digests on the same day
        storage.save_digest(
            digest_date=today,
            items=[{"title": "新闻精选", "summary": "AI板块回调"}],
            source="每日新闻精选",
        )
        storage.save_digest(
            digest_date=today,
            items=[{"title": "讨论话题", "summary": "聊聊AI趋势"}],
            source="每日话题",
        )

        # Retrieve by source
        d1 = storage.get_digest_by_date(today, source="每日新闻精选")
        assert d1 is not None
        assert d1["items"][0]["title"] == "新闻精选"

        d2 = storage.get_digest_by_date(today, source="每日话题")
        assert d2 is not None
        assert d2["items"][0]["title"] == "讨论话题"

        # Retrieve without source returns one (any) of them
        d3 = storage.get_digest_by_date(today)
        assert d3 is not None

        # get_today_digest with source
        d4 = storage.get_today_digest(source="每日新闻精选")
        assert d4 is not None
        assert d4["items"][0]["title"] == "新闻精选"

    def test_save_digest_idempotent_by_source(self, storage):
        """Same (date, source) overwrites."""
        today = date.today().isoformat()

        sid1 = storage.save_digest(
            digest_date=today,
            items=[{"title": "旧"}],
            source="每日话题",
        )
        sid2 = storage.save_digest(
            digest_date=today,
            items=[{"title": "新"}],
            source="每日话题",
        )
        # Should overwrite: same MD5 hash for (date, source)
        assert sid1 == sid2

        d = storage.get_digest_by_date(today, source="每日话题")
        assert d["items"][0]["title"] == "新"

    def test_get_digest_by_date_returns_none_for_missing(self, storage):
        d = storage.get_digest_by_date("1970-01-01")
        assert d is None

    def test_get_digest_by_date_with_source_returns_none_for_missing(self, storage):
        d = storage.get_digest_by_date("1970-01-01", source="不存在")
        assert d is None


# ── Tests for task executions (StorageTaskMixin) ──


class TestTaskExecutions:
    @pytest.fixture
    def storage(self, tmp_path):
        from llm_chat.storage import Storage
        db_path = tmp_path / "test.db"
        s = Storage(db_path=str(db_path))
        yield s

    def _make_execution(self, task_id, status="COMPLETED", result="ok"):
        from datetime import datetime
        from llm_chat.scheduler.models import TaskExecution, TaskStatus
        import uuid
        now = datetime.now()
        return TaskExecution(
            id=uuid.uuid4().hex,
            task_id=task_id,
            status=TaskStatus(status),
            started_at=now,
            finished_at=now,
            result=result,
            error=None,
            retry_count=0,
        )

    def test_save_and_load_executions(self, storage):
        """Save executions and load them back by task_id."""
        e1 = self._make_execution("task-1", result="done")
        e2 = self._make_execution("task-1", result="also done")
        e3 = self._make_execution("task-2", result="other task")

        storage.save_execution(e1)
        storage.save_execution(e2)
        storage.save_execution(e3)

        # Load by task_id
        execs = storage.load_executions(task_id="task-1", limit=10)
        assert len(execs) == 2
        assert execs[0].result in ("done", "also done")

        execs2 = storage.load_executions(task_id="task-2")
        assert len(execs2) == 1

    def test_load_executions_all_tasks(self, storage):
        """load_executions with task_id=None returns all."""
        storage.save_execution(self._make_execution("task-a"))
        storage.save_execution(self._make_execution("task-b"))
        storage.save_execution(self._make_execution("task-c"))

        execs = storage.load_executions(task_id=None, limit=100)
        assert len(execs) == 3

    def test_delete_executions_by_task_id(self, storage):
        """delete_executions for specific task."""
        storage.save_execution(self._make_execution("task-x"))
        storage.save_execution(self._make_execution("task-x"))
        storage.save_execution(self._make_execution("task-y"))

        count = storage.delete_executions(task_id="task-x")
        assert count == 2

        remaining = storage.load_executions(task_id="task-x")
        assert len(remaining) == 0

        remaining_y = storage.load_executions(task_id="task-y")
        assert len(remaining_y) == 1

    def test_delete_executions_all(self, storage):
        """delete_executions with task_id=None clears all."""
        storage.save_execution(self._make_execution("task-1"))
        storage.save_execution(self._make_execution("task-2"))
        storage.save_execution(self._make_execution("task-3"))

        count = storage.delete_executions(task_id=None)
        assert count == 3

        all_remaining = storage.load_executions(task_id=None)
        assert len(all_remaining) == 0


# ── Tests for FetchRSSTool ──


class TestFetchRSSTool:
    def test_name_and_schema(self):
        from llm_chat.tools.fetch_rss import FetchRSSTool
        tool = FetchRSSTool()
        assert tool.name == "fetch_rss"
        assert "RSS" in tool.description

        schema = tool.get_parameters_schema()
        assert schema["type"] == "object"
        assert "max_per_feed" in schema["properties"]

    def test_no_config_returns_no_feeds_message(self):
        from llm_chat.tools.fetch_rss import FetchRSSTool
        tool = FetchRSSTool(config=None)
        result = tool.execute()
        assert "urls" in result or "未提供" in result

    def test_openai_tool_format(self):
        from llm_chat.tools.fetch_rss import FetchRSSTool
        tool = FetchRSSTool()
        openai_tool = tool.to_openai_tool()
        assert openai_tool["type"] == "function"
        assert openai_tool["function"]["name"] == "fetch_rss"
        assert "parameters" in openai_tool["function"]

    def test_urls_parameter_accepted(self):
        """传入 urls 参数时优先使用，不走 config。"""
        from llm_chat.tools.fetch_rss import FetchRSSTool
        tool = FetchRSSTool(config=None)
        # 无 config，但传了 urls → 不应报"未配置"（会尝试抓取，可能网络失败）
        result = tool.execute(urls=["https://example.com/rss"], max_per_feed=1)
        # 网络失败也算正常路径，不是 "未配置" 错误
        assert "未提供" not in result

    def test_no_urls_and_no_config_gives_help(self):
        """不传 urls 且无 config → 给出清晰的配置指引。"""
        from llm_chat.tools.fetch_rss import FetchRSSTool
        tool = FetchRSSTool(config=None)
        result = tool.execute()
        assert "urls" in result or "proactive_rss_feeds" in result
