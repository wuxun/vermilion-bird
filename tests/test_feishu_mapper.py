import pytest

from src.llm_chat.frontends.feishu.mapper import SessionMapper


def test_to_conversation_id_p2p_basic():
    assert SessionMapper.to_conversation_id("p2p", "open123") == "feishu_p2p_open123"


def test_to_conversation_id_sanitization():
    cid = SessionMapper.to_conversation_id("p2p", "a b!@")
    assert cid == "feishu_p2p_a_b__"


def test_to_conversation_id_group_basic():
    assert (
        SessionMapper.to_conversation_id("group", "chat-01") == "feishu_group_chat_01"
    )


def test_from_conversation_id_p2p():
    assert SessionMapper.from_conversation_id("feishu_p2p_open123") == (
        "p2p",
        "open123",
    )


def test_from_conversation_id_group():
    assert SessionMapper.from_conversation_id("feishu_group_chat01") == (
        "group",
        "chat01",
    )


def test_from_conversation_id_invalid_prefix():
    with pytest.raises(ValueError):
        SessionMapper.from_conversation_id("unknown_prefix")


def test_from_conversation_id_empty_rest():
    with pytest.raises(ValueError):
        SessionMapper.from_conversation_id("feishu_p2p_")


def test_roundtrip():
    samples = [
        ("p2p", "open-123"),
        ("group", "proj 9"),
        ("p2p", "user.name"),
    ]
    for chat_type, original_id in samples:
        cid = SessionMapper.to_conversation_id(chat_type, original_id)
        parsed = SessionMapper.from_conversation_id(cid)
        expected = (
            chat_type,
            "".join(ch if ch.isalnum() else "_" for ch in str(original_id)),
        )
        assert parsed == expected
