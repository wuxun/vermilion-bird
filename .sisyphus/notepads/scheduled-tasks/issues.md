# Scope Fidelity Check (F4) - 发现的问题

## 问题 1: GUI 管理界面缺失
**严重性**: 高
**影响**: 用户无法通过 GUI 管理定时任务
**位置**: Task 12-14 未实现
**文件**: `src/llm_chat/frontends/scheduler_dialog.py` 不存在
**发现时间**: 2026-03-29
**建议**: 立即实现 GUI 管理界面

**修复优先级**: P0 (最高)

**计划引用**: Task 12-14

**相关代码**:
- scheduler.py: _build_trigger() 函数（第 270-274 行）
- scheduler.py: _build_trigger() 函数（第 281 行)

---

## 问题 2: Interval 触发器违规
**严重性**: 中
**影响**: 违反了 "不支持固定间隔触发" 的计划约束
**位置**: scheduler.py:270-274, 281
**发现时间**: 2026-03-29
**建议**: 立即移除 interval 触发器支持
**修复优先级**: P1 (高)
**计划引用**: "不支持固定间隔触发（仅 Cron + 一次性任务)"
**代码位置**:
```python
# 第 270-274 行
if "interval" in trigger_config or "interval_seconds" in trigger_config:
    seconds = trigger_config.get("interval") or trigger_config.get(
        "interval_seconds", 60
    )
    return IntervalTrigger(seconds=seconds)

```
**相关函数**: `_build_trigger()`
**修复建议**: 移除第 270-274 行和第 281 行，仅保留 cron 和 date 触发器逻辑

```