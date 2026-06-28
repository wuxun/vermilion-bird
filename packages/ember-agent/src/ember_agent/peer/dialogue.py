"""PeerDialogue — structured agent-to-agent conversation.

Enables multi-turn dialogue between agents. Agents can:
    - send_message: send a message to another agent
    - check_inbox: read messages addressed to them
    - reply: respond to a specific message

The dialogue log is shared across all agents in a workflow.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DialogueMessage(BaseModel):
    """A single message in an agent-to-agent conversation."""

    id: str = Field(default_factory=lambda: f"dmsg_{uuid.uuid4().hex[:8]}")
    from_agent: str = Field(description="Sender agent ID")
    to_agent: str = Field(description="Recipient agent ID")
    content: str = Field(description="Message body")
    reply_to: Optional[str] = Field(default=None, description="ID of message being replied to")
    timestamp: float = Field(default_factory=time.time)


class PeerDialogue:
    """Manages agent-to-agent dialogue threads.

    Usage:
        dlg = PeerDialogue()

        # Agent A asks Agent B a question
        msg_id = dlg.send("agent-a", "agent-b", "What do you think about X?")

        # Agent B checks inbox
        inbox = dlg.inbox("agent-b")

        # Agent B replies
        dlg.send("agent-b", "agent-a", "I think X is good because...", reply_to=msg_id)
    """

    def __init__(self):
        self._messages: Dict[str, DialogueMessage] = {}
        self._threads: Dict[str, List[str]] = {}  # conversation_id → [msg_ids]

    def send(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        reply_to: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> str:
        """Send a message. Returns the message ID."""
        msg = DialogueMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            reply_to=reply_to,
        )
        self._messages[msg.id] = msg

        cid = conversation_id or f"{from_agent}_{to_agent}"
        if cid not in self._threads:
            self._threads[cid] = []
        self._threads[cid].append(msg.id)

        return msg.id

    def inbox(self, agent_id: str, unread_only: bool = True) -> List[DialogueMessage]:
        """Get messages addressed to an agent."""
        messages = []
        for msg in self._messages.values():
            if msg.to_agent == agent_id:
                messages.append(msg)
        return sorted(messages, key=lambda m: m.timestamp)

    def thread(
        self, conversation_id: str
    ) -> List[DialogueMessage]:
        """Get all messages in a conversation thread."""
        msg_ids = self._threads.get(conversation_id, [])
        return [self._messages[mid] for mid in msg_ids if mid in self._messages]

    def get(self, message_id: str) -> Optional[DialogueMessage]:
        """Get a specific message by ID."""
        return self._messages.get(message_id)

    def ask(
        self,
        from_agent: str,
        to_agent: str,
        question: str,
    ) -> str:
        """Shortcut: send a question. Returns the message ID."""
        msg = f"[QUESTION from {from_agent}] {question}"
        return self.send(from_agent, to_agent, msg)

    def respond(
        self,
        to_message_id: str,
        content: str,
    ) -> Optional[str]:
        """Respond to a specific message."""
        orig = self._messages.get(to_message_id)
        if orig is None:
            return None
        return self.send(
            from_agent=orig.to_agent,   # swap sender/recipient
            to_agent=orig.from_agent,
            content=content,
            reply_to=to_message_id,
        )

    def summary(self, agent_id: str) -> str:
        """Text summary of all conversations involving an agent."""
        parts = []
        for cid, msg_ids in self._threads.items():
            if agent_id in cid:
                msgs = [self._messages[mid] for mid in msg_ids if mid in self._messages]
                if msgs:
                    parts.append(f"## Conversation: {cid}")
                    for m in msgs:
                        direction = "→" if m.from_agent == agent_id else "←"
                        parts.append(
                            f"{direction} [{m.from_agent}]: {m.content[:200]}"
                        )
                    parts.append("")
        return "\n".join(parts) if parts else "(no conversations)"

    def clear(self) -> None:
        """Clear all messages."""
        self._messages.clear()
        self._threads.clear()
