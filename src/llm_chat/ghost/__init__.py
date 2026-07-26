"""Ghost — YAML-defined, reusable agent profiles.

A Ghost is a reusable agent template combining:
    - system_prompt (personality + instructions)
    - tools (default tool set)
    - model (preferred model config)
    - skills (optional skills to load)
    - metadata (tags, description, version)

Ghosts are stored as YAML files in ~/.vermilion-bird/ghosts/ and loaded
at startup. SpawnSubagentTool accepts a `ghost=` parameter to reference
a pre-defined ghost by name.

Example ghost YAML (~/.vermilion-bird/ghosts/researcher.yaml):

    name: "Deep Researcher"
    description: "Multi-step web researcher"
    system_prompt: "You are a thorough researcher..."
    tools: [web_search, web_fetch, file_writer]
    model: gpt-4o-mini
    skills: [web_fetch]
    metadata:
      tags: [research, analysis]
      version: "1.0"
"""

from llm_chat.ghost.schema import GhostConfig
from llm_chat.ghost.store import GhostStore, get_ghost_store

__all__ = ["GhostConfig", "GhostStore", "get_ghost_store"]
