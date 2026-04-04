from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from llm_chat.app import App
    from llm_chat.config import Config
    from .models import Task

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    pass


class NotificationService:
    def __init__(self, app: "App", config: "Config"):
        self._app = app
        self._config = config
        self._feishu_adapter = None

    def _get_feishu_adapter(self):
        if not self._config.feishu.enabled:
            return None

        if self._feishu_adapter is None:
            try:
                from llm_chat.frontends.feishu.adapter import FeishuAdapter

                app_id = self._config.feishu.app_id
                app_secret = self._config.feishu.app_secret
                if app_id and app_secret:
                    self._feishu_adapter = FeishuAdapter(
                        self._app,
                        app_id,
                        app_secret,
                    )
            except Exception as e:
                logger.error(f"Failed to initialize Feishu adapter: {e}")
                return None
        return self._feishu_adapter

    def _get_notification_targets(self, task: "Task") -> List[Dict[str, Any]]:
        """获取通知目标，按优先级顺序：
        1. 任务自己配置的 notify_targets
        2. 配置文件中的 default_targets
        3. 从数据库查询最近的飞书对话
        """
        # 1. 任务自己的配置
        if task.notify_targets:
            logger.info(f"Using task's own notification targets: {task.notify_targets}")
            return task.notify_targets

        # 2. 配置文件中的默认目标
        if self._config.notification.default_targets:
            logger.info(
                f"Using config default notification targets: {self._config.notification.default_targets}"
            )
            return self._config.notification.default_targets

        # 3. 从数据库查询最近的飞书对话
        try:
            recent_chat = self._app.storage.get_recent_feishu_chat()
            if recent_chat:
                logger.info(f"Using recent Feishu chat from database: {recent_chat}")
                return [recent_chat]
        except Exception as e:
            logger.warning(f"Failed to get recent Feishu chat from database: {e}")

        return []

    def send_notification(
        self,
        task: "Task",
        result: str,
        success: bool = True,
    ) -> bool:
        logger.info(
            f"send_notification called for task: {task.id}, notify_enabled={task.notify_enabled}"
        )

        if not task.notify_enabled:
            logger.info("Notification disabled for task, skipping")
            return False

        if success and not task.notify_on_success:
            logger.info("Success notification disabled, skipping")
            return False

        if not success and not task.notify_on_failure:
            logger.info("Failure notification disabled, skipping")
            return False

        targets = self._get_notification_targets(task)
        logger.info(f"Final notification targets: {targets}")

        if not targets:
            logger.info(f"No notification targets found for task: {task.id}")
            return False

        status_icon = "✅" if success else "❌"
        status_text = "完成" if success else "失败"

        message = f"{status_icon} **定时任务{status_text}**: {task.name}\n\n{result}"

        all_success = True
        for target in targets:
            try:
                logger.info(f"Sending to target: {target}")
                target_type = target.get("type")
                if target_type == "feishu":
                    self._send_feishu_notification(target, message)
                else:
                    logger.warning(f"Unknown notification target type: {target_type}")
                    all_success = False
            except Exception as e:
                logger.error(f"Failed to send notification to {target}: {e}")
                all_success = False

        return all_success

    def _send_feishu_notification(self, target: Dict[str, Any], message: str):
        adapter = self._get_feishu_adapter()
        if not adapter:
            raise NotificationError("Feishu not configured or disabled")

        chat_id = target.get("chat_id")
        open_id = target.get("open_id")

        if chat_id:
            receive_id = chat_id
            receive_id_type = "chat_id"
        elif open_id:
            receive_id = open_id
            receive_id_type = "open_id"
        else:
            raise NotificationError("Feishu target requires either chat_id or open_id")

        card = self._build_feishu_markdown_card(message)
        adapter.send_message(
            receive_id=receive_id,
            msg_type="interactive",
            content=card,
            receive_id_type=receive_id_type,
        )
        logger.info(f"Feishu notification sent to {receive_id}")

    def _build_feishu_markdown_card(self, markdown_text: str) -> Dict[str, Any]:
        return {
            "config": {"wide_screen_mode": True},
            "elements": [
                {
                    "tag": "markdown",
                    "content": markdown_text,
                }
            ],
        }
