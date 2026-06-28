"""Tests for ember-agent peer module — PeerReviewTool, PeerDialogue."""

import pytest
from ember_agent.peer import PeerReviewTool, PeerDialogue, DialogueMessage
from ember_agent.agent import AgentRegistry, make_agent_context


class TestPeerDialogue:
    def test_send_and_inbox(self):
        dlg = PeerDialogue()
        dlg.send("agent-a", "agent-b", "Hello")
        inbox = dlg.inbox("agent-b")
        assert len(inbox) == 1
        assert inbox[0].from_agent == "agent-a"
        assert inbox[0].content == "Hello"

    def test_respond(self):
        dlg = PeerDialogue()
        msg_id = dlg.send("agent-a", "agent-b", "Question?")
        resp_id = dlg.respond(msg_id, "Answer!")
        assert resp_id is not None
        inbox_a = dlg.inbox("agent-a")
        assert len(inbox_a) == 1
        assert inbox_a[0].content == "Answer!"

    def test_thread(self):
        dlg = PeerDialogue()
        dlg.send("a", "b", "msg1", conversation_id="thread-1")
        dlg.send("a", "b", "msg2", conversation_id="thread-1")
        thread = dlg.thread("thread-1")
        assert len(thread) == 2

    def test_summary(self):
        dlg = PeerDialogue()
        dlg.send("a", "b", "Hello from a")
        dlg.send("b", "a", "Hello from b")
        summary = dlg.summary("a")
        assert "Hello from a" in summary
        assert "Hello from b" in summary

    def test_respond_nonexistent(self):
        dlg = PeerDialogue()
        assert dlg.respond("no-such-msg", "reply") is None

    def test_clear(self):
        dlg = PeerDialogue()
        dlg.send("a", "b", "msg")
        dlg.clear()
        assert len(dlg.inbox("b")) == 0


class TestPeerReviewTool:
    def test_review_completed_agent(self):
        reg = AgentRegistry(max_workers=2)
        ctx = make_agent_context("a1", None, 0, set(), "c1", "analyze code")
        ctx.status = "completed"
        ctx.result = "The code is well-structured."
        reg.spawn("a1", ctx)

        tool = PeerReviewTool(reg)
        result = tool.execute("a1", ["correctness", "completeness"], ["error handling"])
        assert "Peer Review Request" in result
        assert "a1" in result
        assert "correctness" in result
        assert "error handling" in result
        assert "The code is well-structured" in result
        reg.shutdown(wait=False)

    def test_review_running_agent(self):
        reg = AgentRegistry(max_workers=2)
        ctx = make_agent_context("a1", None, 0, set(), "c1", "task")
        ctx.status = "running"
        reg.spawn("a1", ctx)

        tool = PeerReviewTool(reg)
        result = tool.execute("a1", ["correctness"])
        assert "still running" in result.lower()
        reg.shutdown(wait=False)

    def test_review_missing_agent(self):
        reg = AgentRegistry(max_workers=2)
        tool = PeerReviewTool(reg)
        result = tool.execute("ghost", ["correctness"])
        assert "not found" in result.lower()
        reg.shutdown(wait=False)
