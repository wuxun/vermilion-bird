Task: Add AccessController, MessageDeduplicator, and SignatureVerifier to Feishu security module.

- Rationale: Improve security utilities for Feishu Feishu frontend integration.
- Key decisions:
  - SignatureVerifier uses HMAC-SHA256 with message = timestamp\nnonce\nbody; hex digest; rejects future timestamps and respects max_clock_skew_seconds.
  - AccessController supports open/whitelist/blacklist modes; whitelist matches either user_id or chat_id.
  - MessageDeduplicator uses a thread-safe in-memory store with TTL and max size, with cleanup and eviction of oldest entries.
- Follow-up work: add unit tests for edge cases and consider persistence for deduplicator across restarts.
