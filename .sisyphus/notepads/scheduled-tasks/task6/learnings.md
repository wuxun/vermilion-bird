Task 6 (Wave 1) 模块入口 - 学习记录
- 目标：实现 __init__.py 对导出接口的正确公开，避免引入未实现的依赖
- 行动：
 1) 修改 src/llm_chat/scheduler/__init__.py，导出 Task/TaskExecution/TaskType/TaskStatus，保留 SchedulerService/TaskExecutor 的保留注释
 2) 设置 __all__，避免对未实现对象的暴露
 3) 验证 Python 导入：从 llm_chat.scheduler 导出 Task，且 storage.Storage 正常导入
- 验证结果：OK
- 结论：暴露核心模型接口对当前阶段是合适的，保留未来实现点以避免循环依赖
