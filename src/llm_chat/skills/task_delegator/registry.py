# Re-export from ember-agent (canonical source)
# SubAgentRegistry is the legacy name; AgentRegistry is the canonical name.
from ember_agent.agent.registry import AgentRegistry as SubAgentRegistry
from ember_agent.agent.registry import StatusCallback

__all__ = ["SubAgentRegistry", "StatusCallback"]
