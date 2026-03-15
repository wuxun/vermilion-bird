# Skills 扩展系统设计文档

## 概述

Vermilion Bird 实现了一个高内聚、低耦合、易扩展的 Skills 系统，用于扩展 LLM 的能力。

---

## 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                     Vermilion Bird 应用                          │
├─────────────────────────────────────────────────────────────────┤
│                         App 核心层                               │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              SkillManager (技能管理器)                    │    │
│  │  - 发现和加载 Skills                                      │    │
│  │  - 管理 Skill 生命周期                                    │    │
│  │  - 协调 Skill 与 ToolRegistry                            │    │
│  └─────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│                        Skills 层                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐     │
│  │ WebSearch   │  │ Calculator  │  │ Custom (用户自定义)  │     │
│  │ Skill       │  │ Skill       │  │                     │     │
│  │  - web_search│  │  - calculator│  │  - tool_x          │     │
│  └─────────────┘  └─────────────┘  └─────────────────────┘     │
├─────────────────────────────────────────────────────────────────┤
│                     基础设施层                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐     │
│  │ ToolRegistry│  │   Config    │  │      Logging        │     │
│  └─────────────┘  └─────────────┘  └─────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 文件结构

```
src/llm_chat/
├── skills/                    # Skills 模块
│   ├── __init__.py           # 模块导出
│   ├── base.py               # BaseSkill 基类
│   ├── manager.py            # SkillManager
│   ├── web_search/           # 网络搜索技能
│   │   ├── __init__.py
│   │   └── skill.py          # WebSearchSkill + WebSearchTool
│   └── calculator/           # 计算器技能
│       ├── __init__.py
│       └── skill.py          # CalculatorSkill + CalculatorTool
├── tools/                    # 工具基础设施
│   ├── base.py               # BaseTool 基类
│   ├── registry.py           # ToolRegistry 工具注册表
│   └── __init__.py
├── config.py                 # 配置系统（含 Skills 配置）
├── client.py                 # LLMClient（集成 SkillManager）
└── app.py                    # 应用入口

skills/                       # 外部 Skills 目录（用户自定义）
└── templates/                # Skill 开发模板
    └── example_skill/
        ├── __init__.py
        ├── skill.py
        └── skill.yaml
```

---

## 核心组件

### 1. BaseSkill 基类

每个 Skill 必须继承 `BaseSkill`：

```python
class BaseSkill(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Skill 唯一标识名称"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Skill 功能描述"""
        pass
    
    @property
    def version(self) -> str:
        """Skill 版本号"""
        return "1.0.0"
    
    @abstractmethod
    def get_tools(self) -> List[BaseTool]:
        """返回该 Skill 提供的工具列表"""
        pass
    
    def on_load(self, config: Dict[str, Any]) -> None:
        """Skill 加载时调用"""
        pass
    
    def on_unload(self) -> None:
        """Skill 卸载时调用"""
        pass
```

### 2. SkillManager

负责 Skills 的发现、加载、生命周期管理：

```python
class SkillManager:
    def __init__(self, tool_registry: ToolRegistry):
        self._tool_registry = tool_registry
        self._skills: Dict[str, BaseSkill] = {}
    
    def register_skill_class(self, skill_class: Type[BaseSkill]) -> bool:
        """注册 Skill 类"""
        pass
    
    def discover_skills(self, skill_dirs: List[str]) -> List[Type[BaseSkill]]:
        """从指定目录发现 Skill 类"""
        pass
    
    def load_from_config(self, skill_configs: Dict[str, Any]) -> None:
        """从配置加载 Skills"""
        pass
    
    def list_skill_names(self) -> List[str]:
        """列出所有已加载的 Skill 名称"""
        pass
```

### 3. BaseTool 基类

每个 Tool 必须继承 `BaseTool`：

```python
class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        pass
    
    @abstractmethod
    def get_parameters_schema(self) -> Dict[str, Any]:
        """返回 OpenAI 格式的参数 schema"""
        pass
    
    @abstractmethod
    def execute(self, **kwargs) -> str:
        """执行工具"""
        pass
    
    def to_openai_tool(self) -> Dict[str, Any]:
        """转换为 OpenAI 工具格式"""
        pass
```

---

## 内置 Skills

### 1. WebSearchSkill（网络搜索）

**功能：** 搜索互联网获取实时信息

**工具：** `web_search`

**参数：**
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| query | string | 搜索关键词或问题 | 必填 |
| num_results | integer | 返回结果数量 | 5 |
| region | string | 搜索区域 (cn-zh/us-en/auto) | auto |

**特性：**
- 自动检测中文查询，使用 `cn-zh` region
- 中文搜索优先使用 `yandex` 后端
- 支持 DuckDuckGo 和 Brave 搜索引擎
- 支持代理配置

**配置示例：**
```yaml
skills:
  web_search:
    enabled: true
    engine: "duckduckgo"
    api_key: null
    http_proxy: "http://127.0.0.1:7890"
    https_proxy: "http://127.0.0.1:7890"
    timeout: 30
```

### 2. CalculatorSkill（计算器）

**功能：** 执行数学计算

**工具：** `calculator`

**参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| expression | string | 数学表达式 |

**支持：**
- 基本算术运算 (+, -, *, /)
- 幂运算 (pow, **)
- 数学函数 (sqrt, sin, cos, tan, log, exp)
- 常量 (pi, e)

---

## 配置系统

### 配置文件结构

```yaml
# config.yaml
skills:
  web_search:
    enabled: true
    engine: "duckduckgo"
    timeout: 30
  
  calculator:
    enabled: true

# 外部 Skills 目录
external_skill_dirs:
  - "~/.vermilion-bird/skills"
```

### 配置类

```python
class SkillConfig:
    enabled: bool = True
    
    def get_all_skill_configs(self) -> Dict[str, Any]:
        """获取所有 Skill 配置"""
        pass

class Config:
    skills: SkillConfig
    external_skill_dirs: List[str] = []
```

---

## 生命周期管理

```
App 启动
    │
    ▼
LLMClient 初始化
    │
    ├─► SkillManager 初始化
    │
    ├─► 注册内置 Skill 类 (WebSearchSkill, CalculatorSkill)
    │
    ├─► 发现外部 Skills (external_skill_dirs)
    │
    ├─► 从配置加载 Skills (load_from_config)
    │       │
    │       ▼
    │   Skill.on_load(config)
    │       │
    │       ▼
    │   注册 Tools 到 ToolRegistry
    │
    ▼
App 运行（Skills 可用）
    │
    ▼
App 关闭
    │
    ▼
Skill.on_unload() 清理
```

---

## 开发自定义 Skill

### 1. 创建 Skill 目录

```
~/.vermilion-bird/skills/my_skill/
├── __init__.py
├── skill.py
└── skill.yaml (可选)
```

### 2. 实现 Skill

```python
# skill.py
from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool
from typing import Dict, Any, List

class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "my_tool"
    
    @property
    def description(self) -> str:
        return "我的自定义工具"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "输入参数"}
            },
            "required": ["input"]
        }
    
    def execute(self, input: str) -> str:
        return f"处理结果: {input}"

class MySkill(BaseSkill):
    @property
    def name(self) -> str:
        return "my_skill"
    
    @property
    def description(self) -> str:
        return "我的自定义技能"
    
    def get_tools(self) -> List[BaseTool]:
        return [MyTool()]
    
    def on_load(self, config: Dict[str, Any]) -> None:
        self.logger.info(f"加载技能: {config}")
```

### 3. 配置

```yaml
# config.yaml
external_skill_dirs:
  - "~/.vermilion-bird/skills"

skills:
  my_skill:
    enabled: true
    # Skill 特定配置
```

---

## 日志规范

关键位置打印日志：

| 位置 | 日志级别 | 说明 |
|------|---------|------|
| Skill 加载 | INFO | 记录加载的 Skill 名称和配置 |
| Tool 注册 | INFO | 记录注册的工具名称 |
| 搜索执行 | INFO | 记录查询参数和结果数量 |
| 错误处理 | ERROR | 记录错误详情和堆栈 |

---

## 设计原则

1. **高内聚**：每个 Skill 封装独立的功能模块
2. **低耦合**：Skills 之间相互独立，通过接口交互
3. **易扩展**：用户可通过简单规范添加新 Skill
4. **可配置**：通过配置文件管理 Skills 启用/禁用
5. **日志支持**：关键位置打印日志，便于调试

---

## 更新历史

| 日期 | 版本 | 更新内容 |
|------|------|---------|
| 2024-01 | 1.0.0 | 初始设计 |
| 2024-01 | 1.1.0 | 添加 WebSearchSkill 中文搜索优化 |
