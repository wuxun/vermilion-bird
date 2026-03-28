## Learnings from scheduling task setup
- Created tests/test_scheduler/__init__.py with a minimal package docstring.
- Created tests/test_scheduler/conftest.py with fixtures: temp_db (in-memory sqlite3), sample_task, sample_execution.
- Verified: pytest tests/test_scheduler/ --collect-only collects 2 tests from test_models.py.
- Next steps: If more tests depend on these fixtures, ensure integration tests use them.
2026-03-29: Wave 1 completed - all 6 tasks done; storage extended with tasks and task_executions tables; test infrastructure created; module exports configured.
