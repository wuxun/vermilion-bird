"""Ghost profile persistence and cache invalidation tests."""

import time

import pytest
import yaml

from llm_chat.ghost import GhostConfig
from llm_chat.ghost.store import GhostStore
from ember_agent.agent import AgentProfile


def test_manual_edit_invalidates_cached_profile(tmp_path):
    store = GhostStore(tmp_path)
    store.save(
        "reviewer",
        GhostConfig(name="Reviewer", system_prompt="version one"),
    )
    assert store.load("reviewer").system_prompt == "version one"

    path = tmp_path / "reviewer.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["system_prompt"] = "version two"
    time.sleep(0.001)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True),
        encoding="utf-8",
    )

    assert store.load("reviewer").system_prompt == "version two"


def test_ghost_is_a_persisted_agent_profile():
    ghost = GhostConfig(
        name="Reviewer",
        system_prompt="Review carefully.",
        context_policy={"include_sensitive": False},
        capability_policy={"allow": ["read"]},
    )

    assert isinstance(ghost, AgentProfile)
    assert ghost.context_policy["include_sensitive"] is False


def test_ghost_key_is_a_bounded_identifier(tmp_path):
    store = GhostStore(tmp_path)
    ghost = GhostConfig(name="Bad", system_prompt="test")

    for key in ("../escape", "has space", "", "x" * 65):
        with pytest.raises(ValueError):
            store.save(key, ghost)
        with pytest.raises(ValueError):
            store.load(key)
        with pytest.raises(ValueError):
            store.delete(key)
