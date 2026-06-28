# ember-core

Zero-LLM-infrastructure toolkit for building AI agent frameworks.

## Packages

- **tools** — `BaseTool`, `ToolRegistry`, `ToolExecutor` (parallel + retry)
- **storage** — `SQLiteStore` (DI-ready, generic CRUD)
- **mcp** — `MCPClient`, `MCPManager` (stdio/SSE transports)
- **graph** — `StateGraph` engine (invoke/stream/ainvoke/astream/resume + Checkpointer)
- **pipeline** — `PipelineStage`, `PipelineRunner` (linear pipeline executor)
- **memory** — `MemoryStorage` (Markdown file I/O, atomic writes, backup/restore)

## Philosophy

**Zero LLM awareness.** No imports of `openai`, `anthropic`, `requests`, `http`, `chat`, `model`, or `token` anywhere in this package. Pure infrastructure — use ember-core to build agent frameworks, LLM chat apps, or anything else that needs tools, storage, and graph execution.

## Install

```bash
pip install ember-core
```

## Usage

```python
from ember_core.tools import ToolRegistry, ToolExecutor
from ember_core.graph import StateGraph
from ember_core.storage import SQLiteStore
```
