import time
from collections import deque
from typing import Dict, Optional, Set
import hmac
import hashlib
import threading


class RateLimiter:
    """
    Sliding window rate limiter.
    - Maintains per-user request timestamps in-memory.
    - Allows up to max_requests within the last window_seconds.
    - Not suitable for distributed scenarios; aligns with Phase 1 requirements.
    """

    def __init__(self, max_requests: int, window_seconds: int):
        if max_requests <= 0:
            raise ValueError("max_requests must be > 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # user_id -> deque[float]
        self._records: Dict[str, deque] = {}


class SignatureVerifier:
    def __init__(self, secret_key: str, max_clock_skew_seconds: int):
        self.secret_key = secret_key
        self.max_clock_skew_seconds = int(max_clock_skew_seconds)

    def _compute_signature(self, timestamp: str, nonce: str, body: str) -> str:
        message = f"{timestamp}{nonce}{body}".encode("utf-8")
        return hmac.new(
            self.secret_key.encode("utf-8"), message, hashlib.sha256
        ).hexdigest()

    def verify(self, timestamp: str, nonce: str, signature: str, body: str) -> bool:
        try:
            ts = int(timestamp)
        except (ValueError, TypeError):
            return False
        now = int(time.time())
        # Reject future timestamps
        if ts > now:
            return False
        # Check clock skew allowed window
        if now - ts > self.max_clock_skew_seconds:
            return False
        expected = self._compute_signature(timestamp, nonce, body)
        return hmac.compare_digest(signature, expected)


class AccessController:
    def __init__(
        self,
        mode: str,
        whitelist: Optional[Set[str]] = None,
        blacklist: Optional[Set[str]] = None,
    ):
        self.mode = mode.lower()
        self.whitelist: Set[str] = set(whitelist or [])
        self.blacklist: Set[str] = set(blacklist or [])

    def is_allowed(self, user_id: str, chat_id: str) -> bool:
        if self.mode == "open":
            return True
        if self.mode == "whitelist":
            return (user_id in self.whitelist) or (chat_id in self.whitelist)
        if self.mode == "blacklist":
            return not ((user_id in self.blacklist) or (chat_id in self.blacklist))
        return False


class MessageDeduplicator:
    def __init__(self, max_size: int = 10000, ttl: int = 3600):
        self.max_size = int(max_size)
        self.ttl = int(ttl)
        self._store: Dict[str, float] = {}
        self._lock = threading.Lock()

    def is_duplicate(self, event_id: str) -> bool:
        with self._lock:
            self._cleanup_locked()
            return event_id in self._store

    def mark_processed(self, event_id: str) -> None:
        with self._lock:
            now = time.time()
            self._store[event_id] = now
            if len(self._store) > self.max_size:
                self._evict_oldest_locked()

    def cleanup(self) -> None:
        with self._lock:
            self._cleanup_locked()

    def _cleanup_locked(self) -> None:
        cutoff = time.time() - self.ttl
        for k in list(self._store.keys()):
            if self._store[k] < cutoff:
                del self._store[k]

    def _evict_oldest_locked(self) -> None:
        if not self._store:
            return
        while len(self._store) > self.max_size:
            oldest = min(self._store, key=lambda k: self._store[k])
            del self._store[oldest]
