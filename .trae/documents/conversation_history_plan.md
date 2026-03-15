# 会话历史保存及展示功能实现计划

## 需求分析

1. **GUI界面会话展示和切换**：在交互页面添加会话列表，支持切换不同会话
2. **历史对话保存**：所有对话都需要持久化保存
3. **扩展性要求**：未来需要支持从会话历史查询数据

## 存储方案选择

### 方案对比

| 方案 | 优点 | 缺点 | 扩展性 |
|------|------|------|--------|
| JSON文件 | 简单、人类可读 | 查询困难、性能差 | 低 |
| SQLite | 轻量级、支持复杂查询、单文件 | 需要SQL知识 | 高 |
| Markdown | 人类可读 | 不适合程序查询 | 低 |

### 推荐方案：SQLite

**理由**：
- Python内置sqlite3模块，无需额外依赖
- 支持全文搜索(FTS)，便于从历史查询数据
- 单文件存储，便于备份和迁移
- 支持复杂查询（按时间、关键词、角色等筛选）
- 事务支持，数据安全

## 数据库设计

### 表结构

```sql
-- 会话表
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT  -- JSON格式的扩展元数据
);

-- 消息表
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,  -- user, assistant, tool
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,  -- JSON格式的扩展元数据（如token数、模型等）
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

-- 全文搜索索引
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content,
    content='messages',
    content_rowid='id'
);
```

## 实现步骤

### 第一阶段：存储层重构

1. **创建数据库管理模块** `src/llm_chat/storage.py`
   - 实现数据库初始化
   - 会话CRUD操作
   - 消息CRUD操作
   - 全文搜索功能

2. **重构Conversation类**
   - 修改为使用SQLite存储
   - 保持API兼容性
   - 添加会话标题自动生成

### 第二阶段：GUI会话管理

3. **修改GUI布局**
   - 左侧添加会话列表侧边栏
   - 右侧保持聊天区域
   - 添加新建会话按钮
   - 添加删除会话功能

4. **实现会话切换**
   - 切换会话时加载历史消息
   - 保存当前会话状态
   - 更新会话列表显示

### 第三阶段：会话列表展示

5. **会话列表UI**
   - 显示会话标题
   - 显示最后更新时间
   - 高亮当前会话
   - 支持会话重命名

6. **会话搜索功能**（可选扩展）
   - 搜索框
   - 搜索历史消息

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/llm_chat/storage.py` | 新建 | SQLite存储管理 |
| `src/llm_chat/conversation.py` | 修改 | 使用新存储层 |
| `src/llm_chat/frontends/gui.py` | 修改 | 添加会话侧边栏 |
| `src/llm_chat/app.py` | 修改 | 集成会话管理 |

## GUI布局设计

```
+------------------------------------------+
|  Vermilion Bird          [MCP] [Clear]   |
+------------+-----------------------------+
|            |                             |
|  会话列表   |       聊天显示区域           |
|            |                             |
|  [+] 新建  |                             |
|            |                             |
|  会话1     |                             |
|  会话2     |                             |
|  会话3     |                             |
|            |-----------------------------|
|            |  输入框        [Send] [Exit]|
+------------+-----------------------------+
```

## 技术细节

### 会话标题生成
- 使用第一条用户消息的前20个字符作为默认标题
- 支持用户自定义标题

### 数据迁移
- 启动时检测旧JSON文件
- 自动迁移到SQLite数据库
- 迁移后保留原JSON文件作为备份

### 并发安全
- 使用SQLite的WAL模式提高并发性能
- 写操作使用事务保证一致性

## 预估工作量

| 阶段 | 任务 | 预估 |
|------|------|------|
| 第一阶段 | 存储层 | 创建storage.py，修改conversation.py |
| 第二阶段 | GUI布局 | 修改gui.py添加侧边栏 |
| 第三阶段 | 会话管理 | 实现切换、新建、删除功能 |
| 测试验证 | 功能测试 | 确保所有功能正常工作 |
