# Feishu Integration - Rate Limiter Learnings

- Implemented an in-memory per-user sliding window rate limiter.
- Uses a per-user deque of timestamps; purges timestamps older than window.
- Provides is_allowed(user_id) and cleanup() methods as required.
- No external storage or distributed locking used.
- Added unit tests to cover basic sliding window behavior and per-user isolation.

---

## Task 8 (error_handler) Fixes - 2026-03-22

**Bugs Fixed**:
1. Added missing `import logging` - caused "logging is not defined" errors
2. Fixed typo on line 183: `curent_attempt` → `current_attempt`
3. Fixed signal handler implementation:
   - Corrected function scoping issues
   - Added proper signal handler registration and cleanup
   - Fixed `signal.signal()` usage
4. Fixed callback parameter issues:
   - Simplified on_error callback to accept just Exception
   - Removed invalid parameters (last_exception, current_attempt)
5. Fixed decorator usage in example code:
   - Changed from `@error_handler()` syntax to wrapper pattern
   - Properly decorated example function

**Key Learnings**:
- signal.SIGALRM only works on Unix-like systems, not Windows
- Error handler factory function is not a standard decorator syntax
- Need to wrap function with `error_handler(func, **kwargs)` pattern

---

## Task 7 (FeishuServer) Implementation - 2026-03-22

**Implementation Changes**:
- Replaced mock implementation with real lark.ws.Client usage
- Implemented WebSocket connection with event handlers:
  * `im.message.receive_v1` - message reception
  * `im.chat.member.bot.added_v1` - bot added to group
- Implemented reconnection logic with configurable interval (default 5 seconds)
- Implemented graceful shutdown with thread cleanup
- Integrated with FeishuAdapter for event processing
- Added proper logging with sensitive ID masking

**Key Features**:
- Background thread execution (non-blocking start())
- Automatic reconnection on connection loss
- Clean shutdown via stop_event
- Global server registry via _CURRENT_SERVER
- Event handling with exception catching

**Dependency Note**:
- Requires lark-oapi package (listed in pyproject.toml but not installed in current environment)
- Import error expected until lark package is installed
