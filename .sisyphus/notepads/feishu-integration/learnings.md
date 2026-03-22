# Feishu Integration - Rate Limiter Learnings

- Implemented an in-memory per-user sliding window rate limiter.
- Uses a per-user deque of timestamps; purges timestamps older than window.
- Provides is_allowed(user_id) and cleanup() methods as required.
- No external storage or distributed locking used.
- Added unit tests to cover basic sliding window behavior and per-user isolation.
