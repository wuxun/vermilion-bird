# Skills 扩展系统设计方案

## 背景

当前项目 **Vermilion Bird** 已具备：
- 多协议 LLM 支持（OpenAI、Anthropic、Gemini）
- MCP 工具客户端支持
- 内置工具系统（WebSearchTool、CalculatorTool）
- 工具注册机制（ToolRegistry）
- PyQt6 GUI 界面

用户需要支持 **Skills** 机制，以扩展系统能力，实现高内聚、低耦合、易扩展的插件式架构。

---

## 需求分析

### Skills 的定义

Skills 是一种**能力扩展模块**，每个 Skill 封装特定的功能集，可以：
1. 注册工具（Tools）到系统
2. 提供特定领域的处理逻辑
3. 支持配置化管理
4. 动态加载和卸载

### 设计目标

| 目标 | 说明 |
|------|------|
| **高内聚** | 每个 Skill 封装独立的功能模块 |
| **低耦合** | Skills 之间相互独立，通过接口交互 |
| **易扩展** | 用户可通过简单规范添加新 Skill |
| **可配置** | 通过配置文件管理 Skills 启用/禁用 |
| **日志支持** | 关键位置打印日志，便于调试 |

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
│  │ Skill A     │  │ Skill B     │  │ Skill C (用户自定义) │     │
│  │ (内置技能)   │  │ (内置技能)   │  │                     │     │
│  │  - Tool 1   │  │  - Tool 3   │  │  - Tool X           │     │
│  │  - Tool 2   │  │  - Tool 4   │  │  - Tool Y           │     │
│  └─────────────┘  └─────────────┘  └─────────────────────┘     │
├─────────────────────────────────────────────────────────────────┤
│                     基础设施层                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐     │
│  │ ToolRegistry│  │   Config    │  │      Logging        │     │
│  └─────────────┘  └─────────────┘  └─────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 核心组件设计

### 1. Skill 基类 (`BaseSkill`)

每个 Skill 必须继承 `BaseSkill`，定义统一接口：

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
    
    @property
    def dependencies(self) -> List[str]:
        """依赖的其他 Skill 名称列表"""
        return []
    
    @abstractmethod
    def get_tools(self) -> List[BaseTool]:
        """返回该 Skill 提供的工具列表"""
        pass
    
    def on_load(self, config: Dict[str, Any]) -> None:
        """Skill 加载时调用，可进行初始化"""
        pass
    
    def on_unload(self) -> None:
        """Skill 卸载时调用，可进行清理"""
        pass
```

### 2. SkillManager（技能管理器）

负责 Skills 的发现、加载、生命周期管理：

```python
class SkillManager:
    def __init__(self, tool_registry: ToolRegistry):
        self._tool_registry = tool_registry
        self._skills: Dict[str, BaseSkill] = {}
        self._skill_configs: Dict[str, Any] = {}
    
    def discover_skills(self, skill_dirs: List[str]) -> List[Type[BaseSkill]]:
        """从指定目录发现 Skill 类"""
        pass
    
    def load_skill(self, skill_class: Type[BaseSkill], config: Dict = None) -> bool:
        """加载单个 Skill"""
        pass
    
    def unload_skill(self, name: str) -> bool:
        """卸载 Skill"""
        pass
    
    def get_skill(self, name: str) -> Optional[BaseSkill]:
        """获取已加载的 Skill"""
        pass
    
    def list_skills(self) -> List[BaseSkill]:
        """列出所有已加载的 Skills"""
        pass
```

### 3. Skill 发现机制

支持两种方式发现 Skills：

**方式一：内置 Skills 目录**
```
src/llm_chat/skills/
├── __init__.py
├── base.py           # BaseSkill 基类
├── manager.py        # SkillManager
├── web_search/       # 网络搜索技能
│   ├── __init__.py
│   └── skill.py
└── calculator/       # 计算器技能
    ├── __init__.py
    └── skill.py
```

**方式二：外部 Skills 目录（用户自定义）**
```
~/.vermilion-bird/skills/
├── my_skill_1/
│   ├── __init__.py
│   └── skill.py
└── my_skill_2/
    ├── __init__.py
    └── skill.py
```

---

## 配置设计

### 配置文件扩展

```yaml
# config.yaml
skills:
  # 内置 Skills 配置
  web_search:
    enabled: true
    engine: "duckduckgo"
    api_key: null
  
  calculator:
    enabled: true
  
  # 外部 Skills 配置
  custom_skill:
    enabled: true
    path: "~/.vermilion-bird/skills/custom_skill"
    # Skill 特定配置
    option1: "value1"
```

### Skill 元数据

每个 Skill 目录下可包含 `skill.yaml` 元数据文件：

```yaml
name: "web_search"
version: "1.0.0"
description: "网络搜索能力"
author: "Vermilion Bird Team"
dependencies: []
```

---

## 实施计划

### 第一阶段：核心架构

| 序号 | 任务 | 文件 | 说明 |
|------|------|------|------|
| 1.1 | 创建 Skill 基类 | `src/llm_chat/skills/base.py` | 定义 BaseSkill 接口 |
| 1.2 | 实现 SkillManager | `src/llm_chat/skills/manager.py` | Skill 生命周期管理 |
| 1.3 | 创建 Skills 模块 | `src/llm_chat/skills/__init__.py` | 模块导出 |

### 第二阶段：内置 Skills 迁移

| 序号 | 任务 | 文件 | 说明 |
|------|------|------|------|
| 2.1 | 迁移 WebSearchTool | `src/llm_chat/skills/web_search/` | 封装为 Skill |
| 2.2 | 迁移 CalculatorTool | `src/llm_chat/skills/calculator/` | 封装为 Skill |
| 2.3 | 更新工具注册逻辑 | `src/llm_chat/client.py` | 使用 SkillManager |

### 第三阶段：配置系统集成

| 序号 | 任务 | 文件 | 说明 |
|------|------|------|------|
| 3.1 | 扩展配置模型 | `src/llm_chat/config.py` | 添加 Skills 配置 |
| 3.2 | 更新配置示例 | `config.example.yaml` | 添加 Skills 配置示例 |
| 3.3 | 集成到 App | `src/llm_chat/app.py` | 初始化 SkillManager |

### 第四阶段：外部 Skills 支持

| 序号 | 任务 | 文件 | 说明 |
|------|------|------|------|
| 4.1 | 实现动态发现 | `src/llm_chat/skills/manager.py` | 扫描外部目录 |
| 4.2 | 添加 Skill 模板 | `skills/templates/` | 提供开发模板 |
| 4.3 | 编写开发文档 | - | Skill 开发指南 |

### 第五阶段：测试与验证

| 序号 | 任务 | 说明 |
|------|------|------|
| 5.1 | 单元测试 | 测试 SkillManager、BaseSkill |
| 5.2 | 集成测试 | 测试 Skills 与 LLM 工具调用集成 |
| 5.3 | 端到端测试 | 验证完整流程 |

---

## 文件结构规划

```
src/llm_chat/
├── skills/                    # Skills 模块
│   ├── __init__.py
│   ├── base.py               # BaseSkill 基类
│   ├── manager.py            # SkillManager
│   ├── web_search/           # 网络搜索技能
│   │   ├── __init__.py
│   │   └── skill.py
│   └── calculator/           # 计算器技能
│       ├── __init__.py
│       └── skill.py
├── tools/                    # 保留原有工具定义
│   ├── base.py
│   └── registry.py
├── config.py                 # 扩展 Skills 配置
├── client.py                 # 更新工具注册逻辑
└── app.py                    # 集成 SkillManager

skills/                       # 外部 Skills 目录（用户自定义）
└── templates/                # Skill 开发模板
    └── example_skill/
        ├── __init__.py
        ├── skill.py
        └── skill.yaml
```

---

## 关键设计决策

### 1. Skill 与 Tool 的关系

- **Skill** 是能力模块的容器，可包含多个 **Tool**
- **Tool** 是具体的执行单元，由 Skill 注册到 ToolRegistry
- 一个 Skill 可以提供 0 到多个 Tools

### 2. 生命周期管理

```
App 启动
    │
    ▼
SkillManager 初始化
    │
    ├─► 发现 Skills（内置 + 外部）
    │
    ├─► 加载配置中 enabled 的 Skills
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

### 3. 日志规范

关键位置打印日志：
- Skill 加载/卸载
- Tool 注册
- 配置读取
- 错误处理

---

## 示例：创建自定义 Skill

```python
# ~/.vermilion-bird/skills/weather/skill.py
from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool
from typing import Dict, Any, List

class WeatherTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_weather"
    
    @property
    def description(self) -> str:
        return "获取指定城市的天气信息"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名称"}
            },
            "required": ["city"]
        }
    
    def execute(self, city: str) -> str:
        # 实现天气查询逻辑
        return f"{city} 的天气：晴，25°C"

class WeatherSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "weather"
    
    @property
    def description(self) -> str:
        return "天气查询能力"
    
    def get_tools(self) -> List[BaseTool]:
        return [WeatherTool()]
    
    def on_load(self, config: Dict[str, Any]) -> None:
        self.logger.info(f"加载天气技能，配置: {config}")
```

---

## 总结

本方案设计了一个高内聚、低耦合、易扩展的 Skills 系统：

1. **统一接口**：通过 `BaseSkill` 定义标准接口
2. **生命周期管理**：`SkillManager` 负责加载、卸载、协调
3. **灵活配置**：支持 YAML 配置管理 Skills
4. **动态扩展**：支持内置和外部 Skills
5. **日志支持**：关键位置打印日志，便于调试

实施完成后，用户可以轻松添加新技能，扩展系统能力。
