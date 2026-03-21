import time
import hmac
import hashlib


def _make_signature(key: str, timestamp: str, nonce: str, body: str) -> str:
    return hmac.new(
        key.encode("utf-8"), f"{timestamp}{nonce}{body}".encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _get_verifier():
    mod = __import__(
        "llm_chat.frontends.feishu.security", fromlist=["SignatureVerifier"]
    )
    SignatureVerifier = getattr(mod, "SignatureVerifier")  # type: ignore
    return SignatureVerifier("test-key", 300)


def test_valid_signature():
    verifier = _get_verifier()
    timestamp = str(int(time.time()))
    nonce = "test-nonce"
    body = "test-body"
    signature = _make_signature("test-key", timestamp, nonce, body)
    assert verifier.verify(timestamp, nonce, signature, body) is True


def test_invalid_signature():
    verifier = _get_verifier()
    timestamp = str(int(time.time()))
    nonce = "test-nonce"
    body = "test-body"
    signature = _make_signature("test-key", timestamp, nonce, body)
    bad_signature = "0" * 64
    assert verifier.verify(timestamp, nonce, bad_signature, body) is False


def test_expired_timestamp():
    verifier = _get_verifier()
    timestamp = str(int(time.time()) - 360)  # 6 minutes in the past
    nonce = "test-nonce"
    body = "test-body"
    signature = _make_signature("test-key", timestamp, nonce, body)
    assert verifier.verify(timestamp, nonce, signature, body) is False


def test_future_timestamp_rejected():
    verifier = _get_verifier()
    timestamp = str(int(time.time()) + 10)  # in the future
    nonce = "test-nonce"
    body = "test-body"
    signature = _make_signature("test-key", timestamp, nonce, body)
    assert verifier.verify(timestamp, nonce, signature, body) is False
