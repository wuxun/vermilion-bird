# 搜索信息量不足问题分析与优化计划

## 问题分析

### 当前搜索工具的问题

**1. 搜索结果信息量有限**

当前 `WebSearchTool` 只返回搜索引擎提供的摘要信息：
```json
{
    "title": "网页标题",
    "url": "https://...",
    "snippet": "搜索引擎提供的简短摘要，通常只有几十个字"
}
```

**2. 信息深度不足**

- snippet 是搜索引擎自动提取的摘要，内容简略
- 没有获取网页的完整内容
- 无法深入了解某个结果的详细信息

**3. 结果数量有限**

- 默认只返回 5 个结果
- 信息覆盖面窄

### 根本原因

搜索引擎 API（DuckDuckGo、Brave 等）只提供摘要信息，不提供完整网页内容。要获取更多信息，需要：

1. 增加搜索结果数量
2. 抓取网页完整内容
3. 支持多轮深入搜索

---

## 解决方案

### 方案1：增加搜索结果数量（简单）

**优点：**
- 实现简单，只需调整参数
- 立即生效

**缺点：**
- 仍然只有摘要信息
- 信息深度不足

**实现：**
- 将默认 `num_results` 从 5 增加到 10
- 允许用户通过参数指定更大的数量

### 方案2：添加网页内容抓取工具（推荐）

**优点：**
- 获取网页完整内容，信息量大
- 可以深入了解特定结果
- 与搜索工具配合使用

**缺点：**
- 需要额外的网络请求
- 可能遇到反爬虫限制
- 需要处理网页解析

**实现：**
- 新增 `fetch_url` 工具
- 支持抓取网页并提取正文内容
- 支持转换为 Markdown 格式

### 方案3：优化搜索结果格式（辅助）

**优点：**
- 让 LLM 更好地理解搜索结果
- 提供更结构化的信息

**实现：**
- 优化返回的 JSON 格式
- 添加搜索建议和相关信息

---

## 实施计划

### 阶段1：快速优化（立即实施）

1. **增加默认搜索结果数量**
   - 文件：`src/llm_chat/skills/web_search/skill.py`
   - 将 `num_results` 默认值从 5 改为 10

2. **优化搜索结果描述**
   - 让 LLM 知道可以指定更多结果
   - 更新工具描述

### 阶段2：添加网页抓取工具（核心优化）

1. **创建 WebFetchTool**
   - 文件：`src/llm_chat/skills/web_fetch/skill.py`
   - 功能：抓取网页内容并转换为 Markdown
   - 参数：url, max_length

2. **创建 WebFetchSkill**
   - 注册新技能
   - 配置支持

3. **更新文档**
   - 添加新工具使用说明

### 阶段3：增强搜索体验（可选）

1. **添加搜索结果缓存**
   - 避免重复搜索

2. **支持搜索结果筛选**
   - 按时间、来源筛选

---

## 详细实施步骤

### 步骤1：增加搜索结果数量

修改 `WebSearchTool.get_parameters_schema()`:
```python
"num_results": {
    "type": "integer",
    "description": "返回结果数量，默认为10，最大20",
    "default": 10
}
```

### 步骤2：创建 WebFetchTool

新建文件 `src/llm_chat/skills/web_fetch/skill.py`:

```python
class WebFetchTool(BaseTool):
    @property
    def name(self) -> str:
        return "fetch_url"
    
    @property
    def description(self) -> str:
        return "抓取网页完整内容。当需要深入了解某个网页的详细信息时使用此工具。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要抓取的网页URL"
                },
                "max_length": {
                    "type": "integer",
                    "description": "返回内容的最大字符数，默认5000",
                    "default": 5000
                }
            },
            "required": ["url"]
        }
    
    def execute(self, url: str, max_length: int = 5000) -> str:
        # 使用 requests 抓取网页
        # 使用 BeautifulSoup 或 readability 提取正文
        # 转换为 Markdown 格式
        # 返回截断后的内容
        pass
```

### 步骤3：注册新技能

修改 `src/llm_chat/client.py`:
```python
from llm_chat.skills.web_fetch import WebFetchSkill

def _setup_skills(self):
    self._skill_manager.register_skill_class(WebSearchSkill)
    self._skill_manager.register_skill_class(CalculatorSkill)
    self._skill_manager.register_skill_class(WebFetchSkill)  # 新增
```

### 步骤4：更新配置

修改 `src/llm_chat/config.py`:
```python
class SkillsConfig(BaseSettings):
    web_search: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))
    calculator: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))
    web_fetch: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))  # 新增
```

---

## 预期效果

### 优化前

```
用户：搜索一下 Python 最新版本
AI：[调用 web_search]
返回：5个结果，每个只有简短摘要
AI：根据摘要回答，信息有限
```

### 优化后

```
用户：搜索一下 Python 最新版本
AI：[调用 web_search]
返回：10个结果，包含标题和URL
AI：[调用 fetch_url] 抓取最相关的网页
返回：网页完整内容
AI：根据完整内容详细回答
```

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 网页抓取失败 | 中 | 添加错误处理，返回错误信息 |
| 反爬虫限制 | 中 | 添加 User-Agent，支持代理 |
| 内容过长 | 低 | 限制返回长度，智能截断 |
| 性能影响 | 低 | 设置超时，异步处理 |

---

## 依赖项

- `requests` - 已有
- `beautifulsoup4` - 需要添加（用于解析 HTML）
- `readability-lxml` - 可选（用于提取正文）

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/llm_chat/skills/web_search/skill.py` | 修改 | 增加默认结果数量 |
| `src/llm_chat/skills/web_fetch/__init__.py` | 新建 | 模块初始化 |
| `src/llm_chat/skills/web_fetch/skill.py` | 新建 | WebFetchTool 实现 |
| `src/llm_chat/client.py` | 修改 | 注册新技能 |
| `src/llm_chat/config.py` | 修改 | 添加配置支持 |
| `pyproject.toml` | 修改 | 添加依赖 |
