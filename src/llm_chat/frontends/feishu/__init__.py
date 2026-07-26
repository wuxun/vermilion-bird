"""Optional Feishu adapter package with lazy public exports."""

_EXPORTS = {
    "FeishuAdapter": ("adapter", "FeishuAdapter"),
    "FeishuAdapterError": ("adapter", "FeishuAdapterError"),
    "AccessDeniedError": ("adapter", "AccessDeniedError"),
    "DuplicateEventError": ("adapter", "DuplicateEventError"),
    "RateLimitExceededError": ("adapter", "RateLimitExceededError"),
    "SecurityViolationError": ("adapter", "SecurityViolationError"),
    "FeishuMessage": ("models", "FeishuMessage"),
    "FeishuEvent": ("models", "FeishuEvent"),
    "FeishuUser": ("models", "FeishuUser"),
    "FeishuChat": ("models", "FeishuChat"),
    "SessionMapper": ("mapper", "SessionMapper"),
    "PushService": ("push", "PushService"),
    "PushServiceError": ("push", "PushServiceError"),
}


def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    module = __import__(
        f"llm_chat.frontends.feishu.{module_name}",
        fromlist=[attribute],
    )
    return getattr(module, attribute)


__all__ = list(_EXPORTS)
