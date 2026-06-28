# Re-export from ember-agent (canonical source)
# Legacy name 'SubmitDecisionCardTool' aliased for backward compatibility
from ember_agent.consensus.submit import (
    SubmitCardTool as SubmitDecisionCardTool,
    init_card_context,
    clear_card_context,
    submit_card,
    get_pending_card,
)

__all__ = [
    "SubmitDecisionCardTool",
    "init_card_context",
    "clear_card_context",
    "submit_card",
    "get_pending_card",
]
