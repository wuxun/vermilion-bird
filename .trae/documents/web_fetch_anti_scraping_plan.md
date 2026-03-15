# 网页抓取防爬优化计划

## 问题分析

### 当前实现的问题

**1. 简单的 requests 请求**

当前使用 `requests.get()` 直接请求网页，容易被识别为爬虫：
- 缺少完整的浏览器指纹
- 没有 JavaScript 执行能力
- 没有 Cookie/Session 管理

**2. 常见防爬机制**

| 防爬类型 | 说明 | 当前处理 |
|---------|------|---------|
| User-Agent 检测 | 检查请求头 | ✅ 已处理 |
| JavaScript 渲染 | 内容由 JS 动态加载 | ❌ 无法处理 |
| Cloudflare 保护 | 人机验证 | ❌ 无法处理 |
| 登录墙 | 需要登录才能访问 | ❌ 无法处理 |
| IP 限流 | 请求频率限制 | ❌ 无法处理 |
| Cookie 验证 | 需要 Cookie | ❌ 无法处理 |

**3. 结果**

- 很多网站返回 403 Forbidden
- JavaScript 渲染的页面返回空内容
- 触发人机验证后无法继续

---

## 解决方案

### 方案1：使用 Jina Reader API（推荐）

**优点：**
- 免费 API，无需配置
- 自动处理 JavaScript 渲染
- 自动处理常见防爬机制
- 返回 Markdown 格式，易于处理

**缺点：**
- 依赖第三方服务
- 可能有请求限制

**实现：**
```python
def fetch_with_jina_reader(url: str) -> str:
    jina_url = f"https://r.jina.ai/{url}"
    response = requests.get(jina_url, timeout=30)
    return response.text
```

### 方案2：使用 Playwright 无头浏览器

**优点：**
- 完整的浏览器环境
- 支持 JavaScript 渲染
- 可以处理复杂的交互

**缺点：**
- 资源消耗大
- 需要安装浏览器
- 速度较慢

**实现：**
```python
from playwright.sync_api import sync_playwright

def fetch_with_playwright(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        content = page.content()
        browser.close()
        return content
```

### 方案3：增强 requests 请求

**优点：**
- 轻量级，无需额外依赖
- 速度快

**缺点：**
- 无法处理 JavaScript 渲染
- 对高级防爬仍然无效

**实现：**
- 添加完整的浏览器指纹
- 随机化请求特征
- 添加 Referer 等头部

---

## 推荐方案：多层降级策略

```
┌─────────────────────────────────────────────────────────────┐
│                    网页抓取请求                              │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  第1层: Jina Reader API                                      │
│  - 免费、快速、支持 JS 渲染                                   │
│  - 自动处理常见防爬                                           │
└─────────────────────────────────────────────────────────────┘
                            │ 失败
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  第2层: 增强的 requests                                      │
│  - 完整浏览器指纹                                             │
│  - 随机化请求特征                                             │
└─────────────────────────────────────────────────────────────┘
                            │ 失败
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  第3层: Playwright 无头浏览器（可选）                         │
│  - 完整浏览器环境                                             │
│  - 支持 JavaScript 渲染                                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 实施计划

### 阶段1：添加 Jina Reader 支持（核心优化）

1. **更新 WebFetchTool**
   - 添加 `use_jina_reader` 参数
   - 默认使用 Jina Reader
   - 降级到 requests

2. **处理 Jina Reader 响应**
   - 解析 Markdown 格式
   - 提取正文内容

### 阶段2：增强 requests 请求

1. **添加完整浏览器指纹**
   - 完整的请求头
   - 随机化 User-Agent
   - 添加 Referer

2. **添加请求间隔**
   - 随机延迟
   - 避免触发限流

### 阶段3：添加 Playwright 支持（可选）

1. **安装 Playwright**
   - 添加依赖
   - 下载浏览器

2. **实现 Playwright 抓取**
   - 无头模式
   - 等待页面加载

---

## 详细实施步骤

### 步骤1：添加 Jina Reader 支持

修改 `src/llm_chat/skills/web_fetch/skill.py`:

```python
class WebFetchTool(BaseTool):
    def __init__(
        self,
        http_proxy: Optional[str] = None,
        https_proxy: Optional[str] = None,
        timeout: int = 30,
        user_agent: Optional[str] = None,
        use_jina_reader: bool = True
    ):
        self.use_jina_reader = use_jina_reader
        # ... 其他初始化
    
    def execute(self, url: str, max_length: int = 5000) -> str:
        if self.use_jina_reader:
            return self._fetch_with_jina_reader(url, max_length)
        else:
            return self._fetch_with_requests(url, max_length)
    
    def _fetch_with_jina_reader(self, url: str, max_length: int) -> str:
        try:
            jina_url = f"https://r.jina.ai/{url}"
            headers = {
                "User-Agent": self.user_agent,
                "Accept": "text/markdown",
            }
            
            proxies = self._get_proxies()
            response = requests.get(
                jina_url,
                headers=headers,
                proxies=proxies,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            content = response.text
            
            if len(content) > max_length:
                content = content[:max_length] + "\n\n... [内容已截断]"
            
            return f"来源: {url}\n\n{content}"
            
        except Exception as e:
            logger.warning(f"Jina Reader 失败: {e}，降级到 requests")
            return self._fetch_with_requests(url, max_length)
    
    def _fetch_with_requests(self, url: str, max_length: int) -> str:
        # 现有的 requests 实现
        pass
```

### 步骤2：增强 requests 请求

```python
def _get_enhanced_headers(self, url: str) -> Dict[str, str]:
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    ]
    
    parsed_url = urlparse(url)
    domain = parsed_url.netloc
    
    return {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "Referer": f"{parsed_url.scheme}://{domain}/",
    }
```

### 步骤3：更新配置

```python
class WebFetchConfig(BaseSettings):
    enabled: bool = Field(default=True)
    use_jina_reader: bool = Field(default=True, description="是否使用 Jina Reader API")
    jina_reader_url: str = Field(default="https://r.jina.ai/", description="Jina Reader API URL")
    timeout: int = Field(default=30)
    max_retries: int = Field(default=3)
```

---

## 预期效果

### 优化前

```
用户：获取某个新闻网站的详细内容
AI：[调用 fetch_url]
返回：错误: 403 Forbidden
AI：抱歉，无法获取该网页内容
```

### 优化后

```
用户：获取某个新闻网站的详细内容
AI：[调用 fetch_url]
     → 尝试 Jina Reader
     → 成功获取 Markdown 内容
返回：网页完整内容
AI：根据内容详细回答
```

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Jina Reader 服务不可用 | 中 | 降级到 requests |
| Jina Reader 请求限制 | 低 | 添加缓存机制 |
| Playwright 资源消耗 | 中 | 作为最后降级选项 |
| 法律风险 | 低 | 仅用于公开信息 |

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/llm_chat/skills/web_fetch/skill.py` | 修改 | 添加 Jina Reader 支持 |
| `src/llm_chat/config.py` | 修改 | 添加 WebFetchConfig |
| `pyproject.toml` | 修改 | 添加依赖（可选） |

---

## 依赖项

- `requests` - 已有
- `beautifulsoup4` - 已有
- `playwright` - 可选（如需完整浏览器支持）
