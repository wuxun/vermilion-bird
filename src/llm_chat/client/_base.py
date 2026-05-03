"""LLMClient 核心：初始化、技能设置、工具管理"""

import logging
from typing import List, Dict, Any, Optional, Callable

import requests

from llm_chat.config import Config
from llm_chat.protocols import get_protocol
from llm_chat.tools import get_tool_registry, ToolExecutor
from llm_chat.skills import SkillManager
from llm_chat.skills.registry import get_builtin_skills

logger = logging.getLogger(__name__)


class LLMClientBase:
    """LLM 客户端核心基类

    职责：
    - 初始化 session、协议适配器、工具注册表、技能管理器
    - 提供工具/技能相关的 getter/setter
    - 不包含任何聊天/生成方法（由 mixin 提供）
    """

    def __init__(self, config: Config, skip_skills_setup: bool = False,
                 tool_call_hook=None, tool_registry=None,
                 skills_filter: list = None):
        self.config = config
        self._tool_call_hook = tool_call_hook  # Callable[[str, dict, str], None]
        self.session = requests.Session()
        self.session.timeout = config.llm.timeout

        if config.llm.http_proxy or config.llm.https_proxy:
            proxies = {}
            if config.llm.http_proxy:
                proxies["http"] = config.llm.http_proxy
            if config.llm.https_proxy:
                proxies["https"] = config.llm.https_proxy
            self.session.proxies = proxies

        logger.info(
            f"初始化 LLMClient: protocol={config.llm.protocol}, "
            f"model={config.llm.model}, base_url={config.llm.base_url}"
        )

        self.protocol = get_protocol(
            protocol=config.llm.protocol,
            base_url=config.llm.base_url,
            api_key=config.llm.api_key,
            model=config.llm.model,
            timeout=config.llm.timeout,
            max_retries=config.llm.max_retries,
        )
        self._tool_registry = tool_registry if tool_registry is not None else get_tool_registry()
        self._skill_manager = SkillManager(self._tool_registry)
        self._tool_executor_instance = ToolExecutor(
            tool_registry=self._tool_registry,
            max_workers=config.tools.max_workers,
            max_retries=config.tools.max_retries,
            retry_delay=config.tools.retry_delay,
            timeout=config.tools.timeout,
        )
        if not skip_skills_setup:
            self._setup_skills(skills_filter=skills_filter)

    def close(self):
        """关闭客户端，释放连接资源。

        子 agent 执行完成后应调用此方法，避免 requests.Session
        连接池泄漏（大量并发子代理可能耗尽文件描述符）。
        """
        try:
            self.session.close()
            logger.debug("LLMClient session closed")
        except Exception as e:
            logger.warning(f"Error closing LLMClient session: {e}")

    # ------------------------------------------------------------------
    # 技能设置
    # ------------------------------------------------------------------

    def _setup_skills(self, skills_filter: list = None):
        """加载并初始化技能。

        Args:
            skills_filter: 可选，只加载列表中的技能名称。
                          None 表示加载所有技能。用于子 agent 的场景。
        """
        self._tool_registry.clear()

        for skill_name, skill_class in get_builtin_skills().items():
            if skills_filter is not None and skill_name not in skills_filter:
                continue
            self._skill_manager.register_skill_class(skill_class)

        if self.config.external_skill_dirs:
            self._skill_manager.discover_skills(self.config.external_skill_dirs)

        skill_configs = self.config.skills.get_all_skill_configs()

        # 如果用 skills_filter，过滤掉不在白名单中的 skill 配置
        # 避免 load_from_config 中 "Skill class not found" 的无害报错
        if skills_filter is not None:
            skill_configs = {
                k: v for k, v in skill_configs.items()
                if k in skills_filter
            }

        # 注入代理配置（不修改原始 config 对象）
        proxy_defaults = {
            "http_proxy": self.config.llm.http_proxy,
            "https_proxy": self.config.llm.https_proxy,
            "timeout": self.config.llm.timeout,
        }
        work_dir = self.config.tools.work_dir

        for skill_name in ("web_search", "web_fetch"):
            if skill_name in skill_configs:
                cfg = skill_configs[skill_name]
                for key, val in proxy_defaults.items():
                    if val and key not in cfg:
                        cfg[key] = val

        if "todo_manager" in skill_configs:
            if "base_dir" not in skill_configs["todo_manager"]:
                skill_configs["todo_manager"]["base_dir"] = work_dir
        if "task_delegator" in skill_configs:
            if "work_dir" not in skill_configs["task_delegator"]:
                skill_configs["task_delegator"]["work_dir"] = work_dir

        self._skill_manager.load_from_config(skill_configs)

        logger.info(
            f"Skills setup complete. Loaded: {self._skill_manager.list_skill_names()}"
        )

    # ------------------------------------------------------------------
    # 工具管理 getter/setter
    # ------------------------------------------------------------------

    def get_skill_manager(self) -> SkillManager:
        return self._skill_manager

    def get_builtin_tools(self) -> List[Dict[str, Any]]:
        return self._tool_registry.get_tools_for_openai()

    def has_builtin_tools(self) -> bool:
        return len(self._tool_registry.get_all_tools()) > 0

    def execute_builtin_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        return self._tool_registry.execute_tool(name, arguments=arguments)

    def _http_post_json_with_retry(
        self, url: str, data: Dict[str, Any], headers: Dict[str, str],
        label: str = "API",
    ) -> Dict[str, Any]:
        """POST JSON 请求 + 重试。所有 client mixin 共用此方法。

        Returns: 解析后的 JSON 响应
        Raises: LLMError on exhaustion
        """
        import time
        import random
        last_error = None
        for attempt in range(self.config.llm.max_retries):
            try:
                response = self.session.post(url, json=data, headers=headers)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                last_error = e
                if attempt == self.config.llm.max_retries - 1:
                    error_msg = str(e)
                    if hasattr(e, "response") and e.response is not None:
                        try:
                            error_msg = f"{error_msg}\n详情: {e.response.json()}"
                        except Exception:
                            error_msg = f"{error_msg}\n响应: {e.response.text}"
                    logger.error(f"[{label}] 重试耗尽: {error_msg}")
                    raise LLMError(f"API 请求失败: {error_msg}")
                # 指数退避 + 抖动: base=1s, max=60s
                delay = min(2 ** attempt, 60)
                jitter = delay * 0.1 * random.random()
                total_delay = delay + jitter
                logger.warning(
                    f"[{label}] 请求失败, {total_delay:.1f}s后重试 "
                    f"({attempt + 1}/{self.config.llm.max_retries}): {e}"
                )
                time.sleep(total_delay)
        # unreachable
        raise LLMError(f"API 请求失败: {last_error}")
