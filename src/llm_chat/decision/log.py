# Re-export from ember-agent (canonical source)
# vermilion-bird adapter: wraps vermilion-bird Storage for backward compat
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ember_agent.consensus.store import DecisionLogStore as _BaseDecisionLogStore

logger = logging.getLogger(__name__)


class DecisionLogStore(_BaseDecisionLogStore):
    """Decision log store backed by vermilion-bird's Storage singleton.

    Maintains backward compatibility with existing code that uses
    DecisionLogStore() without arguments.
    """

    def __init__(self):
        from llm_chat.storage import Storage
        from ember_core.storage.sqlite import SQLiteStore

        # Wrap vermilion-bird's Storage.s connection() in a SQLiteStore-compatible interface
        self._vb_storage = Storage()

        # Create a thin SQLiteStore-compatible wrapper
        class _StorageWrapper:
            def __init__(self, vb_storage):
                self._vb = vb_storage

            def connection(self):
                # Use the existing Storage's connection contextmanager
                return self._vb._get_connection()

        wrapper = _StorageWrapper(self._vb_storage)
        # Bypass __init__ to set the store directly
        self._store = wrapper
        self._ensure_table()


__all__ = ["DecisionLogStore"]
