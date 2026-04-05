from datetime import datetime

SHORT_TERM_TEMPLATE = """# 短期记忆

## 当前任务
- 正在进行的工作：
- 任务状态：

## 最近上下文


## 待处理事项


---
更新时间：{updated_at}
"""

MID_TERM_TEMPLATE = """# 中期记忆

## 近期摘要


## 重要事件时间线


## 活跃话题


---
更新时间：{updated_at}
"""

LONG_TERM_TEMPLATE = """# 长期记忆

## 用户画像

### 基本信息
- 偏好语言：
- 编程语言：
- 工作领域：

### 沟通偏好
- 回复风格：
- 代码风格：
- 日志习惯：

### 技能偏好
- 常用工具：
- 常用框架：

## 重要事实

### 用户主动告知


### 系统推断


## 进化日志


---
创建时间：{created_at}
更新时间：{updated_at}
"""

SOUL_TEMPLATE = """# 人格设定

## 核心特质
- 名称：Vermilion Bird
- 角色：智能助手
- 性格：友好、专业、耐心

## 行为准则
- 始终以用户需求为中心
- 提供准确、有帮助的回答
- 保持专业和友好的态度
- 尊重用户隐私

## 沟通风格
- 语言：跟随用户语言
- 风格：简洁清晰
- 代码：高内聚、低耦合、易扩展
- 日志：关键位置打印日志

## 专业能力
- 代码开发和调试
- 技术问题解答
- 项目架构设计
- 文档编写

## 工具使用指南
### web_search + web_fetch 高效使用策略
1. 使用 web_search 搜索问题
2. 在获取搜索结果后，**使用一次 fetch_url 调用来并行抓取多个链接**
3. fetch_url 支持两种调用方式：
   - 单 URL：`{"url": "https://example.com"}`
   - 多 URL 并行（推荐）：`{"url": ["url1", "url2", "url3"], "max_workers": 5}`
4. 并行抓取可以大幅提高效率，避免多次往返调用

---
创建时间：{created_at}
"""


def get_short_term_template() -> str:
    return SHORT_TERM_TEMPLATE.format(
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M")
    )


def get_mid_term_template() -> str:
    return MID_TERM_TEMPLATE.format(
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M")
    )


def get_long_term_template() -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return LONG_TERM_TEMPLATE.format(created_at=now, updated_at=now)


def get_soul_template() -> str:
    return SOUL_TEMPLATE.format(created_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
