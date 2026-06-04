"""LLMClient 核心：初始化、技能设置、工具管理"""

import logging
import os
from typing import List, Dict, Any, Optional, Callable

import requests

from llm_chat.config import Config
from llm_chat.exceptions import LLMError, ContentModerationError
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

    def reconfigure(self):
        """根据当前 config 重建 protocol 适配器和 session。

        在 config.llm.model / base_url / api_key / protocol 变更后调用，
        使后续 LLM 调用使用新配置。
        """
        self.session.timeout = self.config.llm.timeout

        if self.config.llm.http_proxy or self.config.llm.https_proxy:
            proxies = {}
            if self.config.llm.http_proxy:
                proxies["http"] = self.config.llm.http_proxy
            if self.config.llm.https_proxy:
                proxies["https"] = self.config.llm.https_proxy
            self.session.proxies = proxies

        self.protocol = get_protocol(
            protocol=self.config.llm.protocol,
            base_url=self.config.llm.base_url,
            api_key=self.config.llm.api_key,
            model=self.config.llm.model,
            timeout=self.config.llm.timeout,
            max_retries=self.config.llm.max_retries,
        )
        logger.info(
            f"LLMClient reconfigured: protocol={self.config.llm.protocol}, "
            f"model={self.config.llm.model}, base_url={self.config.llm.base_url}"
        )

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
        try:
            self._tool_executor_instance.shutdown()
            logger.debug("ToolExecutor thread pool shut down")
        except Exception as e:
            logger.warning(f"Error shutting down ToolExecutor: {e}")

    # ------------------------------------------------------------------
    # 技能设置
    # ------------------------------------------------------------------

    def _setup_skills(self, skills_filter: list = None):
        """加载并初始化技能。注册覆盖同名工具，天然幂等。

        Args:
            skills_filter: 可选，只加载列表中的技能名称。
                          None 表示加载所有技能。用于子 agent 的场景。
        """
        # 注册系统级工具（仅在父 LLMClient，子 agent 不注册卡片工具）
        if skills_filter is None:
            from llm_chat.decision.submit_tool import SubmitDecisionCardTool
            from llm_chat.tools.fetch_rss import FetchRSSTool
            self._tool_registry.register(SubmitDecisionCardTool())
            self._tool_registry.register(FetchRSSTool(config=self.config))

        # 注册技能工具
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
        work_dir = os.path.abspath(os.path.expanduser(self.config.tools.work_dir))

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

        # 注入工作目录到所有文件/Shell 技能
        for skill_name in ("file_reader", "file_writer", "file_editor"):
            if skill_name in skill_configs:
                if "base_dir" not in skill_configs[skill_name]:
                    skill_configs[skill_name]["base_dir"] = work_dir
        if "shell_exec" in skill_configs:
            if "allowed_workdir" not in skill_configs["shell_exec"]:
                skill_configs["shell_exec"]["allowed_workdir"] = work_dir

        self._skill_manager.load_from_config(skill_configs)

        # 自动加载外部发现但未配置的代码 Skill
        # discover_skills 已将类注册到 _skill_classes，但没有 config 条目
        # 因此 load_from_config 会跳过它们。这里补加载。
        loaded = set(self._skill_manager.list_skill_names())
        for name, skill_class in self._skill_manager.get_all_skill_classes().items():
            if name not in loaded:
                try:
                    self._skill_manager.load_skill(name)
                    logger.info(f"Auto-loaded external skill: {name}")
                except Exception as e:
                    logger.warning(f"Failed to auto-load external skill '{name}': {e}")

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
                # 内容审核拒绝 (如 DeepSeek "Content Exists Risk") — 不重试，抛出独立异常
                if self._is_content_moderation_error(e):
                    error_msg = self._format_error(e, label)
                    logger.error(f"[{label}] 内容审核拒绝，跳过重试: {error_msg}")
                    raise ContentModerationError(
                        f"内容审核拒绝: {error_msg}",
                        request_dump=self._build_request_dump(data),
                    )
                if attempt == self.config.llm.max_retries - 1:
                    error_msg = self._format_error(e, label)
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

    # 内容审核拒绝关键词 (各厂商常见错误信息)
    _CONTENT_MODERATION_KEYWORDS = frozenset({
        "content exists risk",
        "content_policy_violation",
        "safety",
        "blocked",
        "moderation",
        "harmful",
        "flagged",
    })

    def _is_content_moderation_error(self, error: requests.RequestException) -> bool:
        """判断是否为内容审核拒绝（非网络错误，重试无意义）。"""
        resp = getattr(error, "response", None)
        if resp is None or resp.status_code != 400:
            return False
        try:
            body = resp.json()
            err_obj = body.get("error", {})
            msg = (err_obj.get("message", "") or "").lower()
            code = (err_obj.get("code", "") or "").lower()
            return any(kw in msg or kw in code for kw in self._CONTENT_MODERATION_KEYWORDS)
        except Exception:
            return False

    def _format_error(self, error: requests.RequestException, label: str) -> str:
        """格式化错误信息，包含 API 详情。"""
        error_msg = str(error)
        resp = getattr(error, "response", None)
        if resp is not None:
            try:
                error_msg = f"{error_msg}\n详情: {resp.json()}"
            except Exception:
                error_msg = f"{error_msg}\n响应: {resp.text}"
        return error_msg

    # ── 内容审核拒绝：日志记录 + 模型 fallback ──

    def _build_request_dump(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """构建请求快照，用于审核日志。脱敏 API key。"""
        messages = data.get("messages", [])
        # 只保留 role + content 前 500 字符
        safe_messages = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                content = content[:500]
            safe_messages.append({
                "role": msg.get("role", "unknown"),
                "content": content,
            })
        return {
            "model": data.get("model", "unknown"),
            "messages_count": len(messages),
            "messages": safe_messages,
            "has_tools": "tools" in data,
        }

    def _log_moderation_request(
        self, error: ContentModerationError, label: str
    ) -> None:
        """将触发审核的请求详情写入专用日志文件。"""
        import json as _json
        from datetime import datetime

        log_dir = self.config.llm.moderation_log_dir
        if not log_dir:
            import pathlib
            log_dir = str(pathlib.Path.home() / ".vermilion-bird" / "moderation_logs")

        try:
            os.makedirs(log_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = os.path.join(log_dir, f"moderation_{ts}.json")
            dump = {
                "timestamp": datetime.now().isoformat(),
                "label": label,
                "model": self.config.llm.model,
                "base_url": self.config.llm.base_url,
                "error": error.message,
                "request": error.request_dump,
            }
            with open(log_path, "w", encoding="utf-8") as f:
                _json.dump(dump, f, ensure_ascii=False, indent=2)
            logger.info(f"审核拒绝请求已记录: {log_path}")
        except Exception as e:
            logger.warning(f"写入审核日志失败: {e}")

    def _handle_content_moderation_fallback(
        self,
        error: ContentModerationError,
        build_request_fn,
        label: str,
    ):
        """内容审核拒绝时：记录日志 + 遍历 fallback 模型重试。

        Args:
            error: 原始审核拒绝异常
            build_request_fn: 无参函数，返回 (url, data, headers) 三元组
            label: 日志标签

        Returns:
            fallback 模型的响应 JSON

        Raises:
            ContentModerationError: 所有 fallback 也失败时重新抛出
        """
        # 1. 记录审核日志
        self._log_moderation_request(error, label)

        # 2. 查找 fallback 模型
        fallback_ids = self.config.llm.fallback_models
        if not fallback_ids:
            logger.warning("无 fallback 模型配置，审核拒绝无法恢复")
            raise error

        # 3. 保存原始配置
        orig_model = self.config.llm.model
        orig_base_url = self.config.llm.base_url
        orig_api_key = self.config.llm.api_key
        orig_protocol = self.config.llm.protocol

        available = {m.id: m for m in self.config.llm.available_models}

        for fb_id in fallback_ids:
            fb_info = available.get(fb_id)
            if not fb_info:
                logger.warning(f"fallback 模型 '{fb_id}' 不在 available_models 中，跳过")
                continue

            # 切换到 fallback 模型
            self.config.llm.model = fb_info.id
            if fb_info.base_url:
                self.config.llm.base_url = fb_info.base_url
            if fb_info.api_key:
                self.config.llm.api_key = fb_info.api_key
            if fb_info.protocol:
                self.config.llm.protocol = fb_info.protocol
            self.reconfigure()

            logger.info(
                f"[{label}] 内容审核拒绝，尝试 fallback 模型: "
                f"{orig_model} → {fb_id}"
            )

            try:
                url, data, headers = build_request_fn()
                result = self._http_post_json_with_retry(
                    url, data, headers, label=f"{label}→{fb_id}"
                )
                logger.info(f"[{label}] fallback 模型 {fb_id} 调用成功")
                return result
            except ContentModerationError:
                logger.warning(f"[{label}] fallback 模型 {fb_id} 也被审核拒绝")
                continue
            except Exception as fb_err:
                logger.warning(f"[{label}] fallback 模型 {fb_id} 调用失败: {fb_err}")
                continue

        # 所有 fallback 都失败，恢复原始配置并抛出
        self.config.llm.model = orig_model
        self.config.llm.base_url = orig_base_url
        self.config.llm.api_key = orig_api_key
        self.config.llm.protocol = orig_protocol
        self.reconfigure()
        raise error
