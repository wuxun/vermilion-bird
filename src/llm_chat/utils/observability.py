"""
轻量级可观测性层 — 追踪 LLM 调用、工具执行、记忆提取的全链路。

提供：
- Span: 单次操作的追踪记录（耗时、状态、元数据）
- Observability: 结构化指标收集器（spans、counters、gauges）
- @observe 装饰器: 自动追踪函数调用的耗时和异常
- get_observability(): 获取全局单例
"""

import time
import functools
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------


@dataclass
class Span:
    """单次操作的追踪记录。"""

    operation: str
    start_time: float
    end_time: Optional[float] = None
    status: str = "running"  # running | success | error
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def duration_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return 0

    def __repr__(self) -> str:
        return (
            f"Span({self.operation}, {self.status}, "
            f"{self.duration_ms:.1f}ms)"
        )


# ------------------------------------------------------------------
# Observability collector
# ------------------------------------------------------------------


class Observability:
    """轻量级可观测性收集器。

    线程安全。支持 span 追踪、计数器、仪表盘。
    """

    def __init__(self, max_spans: int = 1000):
        self._max_spans = max_spans
        self._lock = threading.Lock()
        self.spans: List[Span] = []
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}

    # -- span 管理 --

    def start_span(self, operation: str, **metadata) -> Span:
        span = Span(
            operation=operation,
            start_time=time.time(),
            metadata=metadata,
        )
        with self._lock:
            self.spans.append(span)
            # 环形限制
            if len(self.spans) > self._max_spans:
                self.spans = self.spans[-self._max_spans:]
        return span

    def end_span(self, span: Span, error: Optional[str] = None):
        span.end_time = time.time()
        span.status = "error" if error else "success"
        span.error = error

    # -- 计数器 --

    def increment(self, metric: str, value: int = 1):
        with self._lock:
            self._counters[metric] = self._counters.get(metric, 0) + value

    def counter(self, metric: str) -> int:
        with self._lock:
            return self._counters.get(metric, 0)

    # -- 仪表盘 --

    def set_gauge(self, metric: str, value: float):
        with self._lock:
            self._gauges[metric] = value

    def gauge(self, metric: str) -> float:
        with self._lock:
            return self._gauges.get(metric, 0.0)

    # -- 摘要 --

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self.spans)
            active = sum(1 for s in self.spans if s.status == "running")
            success = sum(1 for s in self.spans if s.status == "success")
            error_count = sum(1 for s in self.spans if s.status == "error")
            finished = [s for s in self.spans if s.end_time]
            avg_duration = (
                sum(s.duration_ms for s in finished) / max(1, len(finished))
            )

            # 按操作分组统计
            by_op: Dict[str, Dict[str, Any]] = {}
            for s in self.spans:
                if s.operation not in by_op:
                    by_op[s.operation] = {
                        "count": 0,
                        "success": 0,
                        "error": 0,
                        "total_ms": 0.0,
                    }
                by_op[s.operation]["count"] += 1
                if s.status == "success":
                    by_op[s.operation]["success"] += 1
                elif s.status == "error":
                    by_op[s.operation]["error"] += 1
                by_op[s.operation]["total_ms"] += s.duration_ms

            return {
                "total_spans": total,
                "active_spans": active,
                "success_spans": success,
                "error_spans": error_count,
                "avg_duration_ms": round(avg_duration, 2),
                "by_operation": {
                    op: {
                        **stats,
                        "avg_ms": round(stats["total_ms"] / max(1, stats["count"]), 2),
                    }
                    for op, stats in by_op.items()
                },
                "counters": self._counters.copy(),
                "gauges": self._gauges.copy(),
            }

    def get_recent_spans(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近的 span 记录，供 UI 展示。"""
        with self._lock:
            recent = self.spans[-limit:]
        return [
            {
                "operation": s.operation,
                "status": s.status,
                "duration_ms": round(s.duration_ms, 2),
                "error": s.error,
                "metadata": s.metadata,
            }
            for s in recent
        ]

    def reset(self):
        """重置所有指标（测试用）。"""
        with self._lock:
            self.spans.clear()
            self._counters.clear()
            self._gauges.clear()


# ------------------------------------------------------------------
# 全局实例
# ------------------------------------------------------------------

_observability = Observability()


def get_observability() -> Observability:
    """获取全局可观测性实例。"""
    return _observability


# ------------------------------------------------------------------
# @observe 装饰器
# ------------------------------------------------------------------


def observe(
    operation: Optional[str] = None,
    *,
    track_args: bool = False,
    extra_tags: Optional[Dict[str, str]] = None,
) -> Callable:
    """可观测性装饰器 —— 自动追踪函数调用。

    用法:
        @observe("chat_with_tools")
        def chat_with_tools(self, message, tools, history):
            ...

    或直接 @observe，自动取 func.__qualname__:
        @observe
        def send_message(self, message):
            ...

    Args:
        operation: 操作名称，None 时自动取函数限定名。
        track_args: 是否记录参数（可能包含敏感信息，默认关闭）。
        extra_tags: 额外的静态标签。
    """

    def decorator(func):
        op_name = operation or func.__qualname__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            meta = {}
            if extra_tags:
                meta.update(extra_tags)
            if track_args:
                # 只记录参数类型，避免敏感信息泄漏
                meta["arg_types"] = [type(a).__name__ for a in args]
                meta["kwarg_keys"] = list(kwargs.keys())

            span = _observability.start_span(op_name, **meta)
            try:
                result = func(*args, **kwargs)
                _observability.end_span(span)
                _observability.increment(f"{op_name}.success")
                return result
            except Exception as e:
                _observability.end_span(span, error=str(e))
                _observability.increment(f"{op_name}.error")
                raise

        return wrapper

    return decorator


# ------------------------------------------------------------------
# 便捷函数
# ------------------------------------------------------------------


def token_used(count: int, model: str = "unknown"):
    """记录 token 消耗。"""
    obs = get_observability()
    obs.increment("tokens.total", count)
    obs.increment(f"tokens.{model}", count)
    obs.set_gauge("tokens.last_call", count)


def tool_called(name: str, duration_ms: float, success: bool = True):
    """记录工具调用。"""
    obs = get_observability()
    key_base = f"tool.{name}"
    obs.increment(f"{key_base}.count")
    if success:
        obs.increment(f"{key_base}.success")
    else:
        obs.increment(f"{key_base}.error")
    obs.set_gauge(f"{key_base}.last_duration_ms", duration_ms)


def llm_call_completed(duration_ms: float, model: str = "unknown"):
    """记录 LLM 调用完成。"""
    obs = get_observability()
    obs.increment("llm.calls")
    obs.set_gauge("llm.last_duration_ms", duration_ms)
    obs.increment(f"llm.{model}.calls")


# ------------------------------------------------------------------
# 模型定价 & 成本追踪
# ------------------------------------------------------------------

# 每百万 token 价格 (USD)，2026年5月参考价
_MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # DeepSeek
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "deepseek-ai/DeepSeek-V3": {"input": 0.27, "output": 1.10},
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "o1": {"input": 15.00, "output": 60.00},
    "o3-mini": {"input": 1.10, "output": 4.40},
    # Anthropic
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-opus": {"input": 15.00, "output": 75.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    # Google
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    # Qwen (通义千问)
    "qwen-turbo": {"input": 0.14, "output": 0.28},
    "qwen-plus": {"input": 0.55, "output": 1.10},
    "qwen-max": {"input": 2.80, "output": 11.20},
}


def get_model_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """计算指定模型的调用成本 (USD)，支持模糊匹配。"""
    pricing = None
    for key, p in _MODEL_PRICING.items():
        if key.lower() in model.lower():
            pricing = p
            break
    if pricing is None:
        return 0.0
    return (prompt_tokens / 1_000_000) * pricing["input"] + \
           (completion_tokens / 1_000_000) * pricing["output"]


def get_cost_summary() -> Dict[str, Any]:
    """获取会话成本/用量完整摘要，供 GUI 仪表盘使用。"""
    obs = get_observability()

    total_prompt = obs.counter("tokens.prompt")
    total_completion = obs.counter("tokens.completion")
    total_tokens = obs.counter("tokens.total")
    llm_calls = obs.counter("llm.calls")

    # 按模型估算成本 — 用全局 prompt/completion 比例，而非固定 75/25
    model_stats = []
    total_cost = 0.0
    total_all = total_prompt + total_completion
    if total_all > 0:
        prompt_ratio = total_prompt / total_all
    else:
        prompt_ratio = 0.75

    for key, count in sorted(obs._counters.items()):
        if key.startswith("tokens.") and key not in (
            "tokens.prompt", "tokens.completion", "tokens.total", "tokens.last_call"
        ):
            model = key[len("tokens."):]
            if model in ("total", "last_call"):
                continue
            est_prompt = int(count * prompt_ratio)
            est_completion = count - est_prompt
            cost = get_model_cost(model, est_prompt, est_completion)
            total_cost += cost
            model_stats.append({
                "model": model,
                "tokens": count,
                "cost_usd": round(cost, 6),
            })

    # 工具调用统计
    tool_stats = {}
    for key, count in obs._counters.items():
        if key.startswith("tool.") and key.endswith(".count"):
            tool_name = key[len("tool."):-len(".count")]
            success = obs.counter(f"tool.{tool_name}.success")
            error = obs.counter(f"tool.{tool_name}.error")
            tool_stats[tool_name] = {"count": count, "success": success, "error": error}

    return {
        "tokens": {
            "total": total_tokens,
            "prompt": total_prompt,
            "completion": total_completion,
        },
        "cost": {
            "total_usd": round(total_cost, 6),
            "by_model": model_stats,
        },
        "calls": {
            "total": llm_calls,
        },
        "tools": tool_stats,
        "avg_duration_ms": obs.get_summary().get("avg_duration_ms", 0),
    }
