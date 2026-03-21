import time
import pytest

from llm_chat.frontends.feishu.security import RateLimiter


def test_rate_limiter_basic(monkeypatch):
    t = [0.0]

    def fake_time():
        return t[0]

    monkeypatch.setattr("time.time", fake_time)

    limiter = RateLimiter(max_requests=5, window_seconds=60)
    user = "userA"

    for _ in range(5):
        assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is False

    t[0] = 61.0
    assert limiter.is_allowed(user) is True

    limiter.cleanup()
    assert limiter.is_allowed(user) in (True, False)


def test_rate_limiter_multi_user_isolation(monkeypatch):
    t = [0.0]

    def fake_time():
        return t[0]

    monkeypatch.setattr("time.time", fake_time)

    limiter = RateLimiter(max_requests=3, window_seconds=30)
    user1 = "alice"
    user2 = "bob"

    for _ in range(3):
        assert limiter.is_allowed(user1) is True
    assert limiter.is_allowed(user1) is False
    assert limiter.is_allowed(user2) is True
    t[0] = 31.0
    assert limiter.is_allowed(user1) is True
