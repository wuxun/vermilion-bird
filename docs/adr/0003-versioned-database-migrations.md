# ADR-0003：SQLite 使用显式版本迁移与升级前备份

**状态**：Accepted  
**日期**：2026-07-28

## 决策

1. `PRAGMA user_version` 是当前 schema 版本的机器事实；
2. `schema_migrations` 保存成功迁移的版本、名称和时间；
3. 任何旧库升级或当前版本 schema 漂移修复前，使用 SQLite backup API 创建 WAL 一致副本；
4. 迁移失败后从副本恢复，并写入原子 sidecar 诊断记录；
5. 高于应用支持版本的数据库拒绝打开，禁止降级写入；
6. 每个历史版本必须有数据保留、重复启动和失败恢复测试。

## 边界

迁移只负责数据库结构和确定性数据变换。Run checkpoint、WorkflowDefinition 和记忆内容的
语义升级分别由各自领域版本处理，不在 SQLite schema migration 中隐式修改。
