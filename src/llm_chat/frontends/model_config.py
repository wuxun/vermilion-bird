"""Model & Settings 面板 — 从 GUIFrontend 拆分。

提供模型选择/温度/推理面板 + 对话框按钮回调。
"""

import logging

logger = logging.getLogger(__name__)


class ModelConfigMixin:
    """模型配置面板 mixin。

    依赖 GUIFrontend 提供的:
    - self._config / self._current_model
    - self._model_combo / self._temperature_slider / self._temperature_value
    - self._reasoning_combo
    """

    # ------------------------------------------------------------------
    # Model Combo
    # ------------------------------------------------------------------

    def _init_model_combo(self):
        if self._model_combo is None:
            return
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        if self._config is None:
            self._model_combo.addItem(self._current_model, self._current_model)
            self._model_combo.setCurrentText(self._current_model)
            self._model_combo.blockSignals(False)
            return
        available_models = getattr(self._config.llm, "available_models", [])
        if available_models:
            for model_info in available_models:
                if hasattr(model_info, "id"):
                    model_id = model_info.id
                    model_name = getattr(model_info, "name", model_id)
                elif hasattr(model_info, "get"):
                    model_id = model_info.get("id", "")
                    model_name = model_info.get("name", model_id)
                else:
                    model_id = str(model_info)
                    model_name = model_id
                # displayText = name, userData = id
                self._model_combo.addItem(model_name, model_id)
            current_model = self._config.llm.model
            # 用 itemData 匹配，避免 name/id 不一致导致选不中
            for i in range(self._model_combo.count()):
                if self._model_combo.itemData(i) == current_model:
                    self._model_combo.setCurrentIndex(i)
                    break
        else:
            self._model_combo.addItem(self._current_model, self._current_model)
            self._model_combo.setCurrentText(self._current_model)
        self._model_combo.blockSignals(False)

    def _on_model_changed(self, index: int):
        if self._config is None or self._model_combo is None:
            return
        # 从 itemData 获取真实 model id，不再依赖 currentText
        model_id = self._model_combo.itemData(index)
        if not model_id:
            model_id = self._model_combo.currentText()
        old_model = self._config.llm.model
        if model_id == old_model:
            return
        # 查找对应的 ModelInfo 以获取 per-model 配置
        available_models = getattr(self._config.llm, "available_models", [])
        selected_model_info = None
        for model_info in available_models:
            mid = model_info.id if hasattr(model_info, "id") else model_info.get("id", "")
            if mid == model_id:
                selected_model_info = model_info
                break
        self._config.llm.model = model_id
        self._current_model = model_id
        if selected_model_info:
            if (
                hasattr(selected_model_info, "base_url")
                and selected_model_info.base_url
            ):
                self._config.llm.base_url = selected_model_info.base_url
            if hasattr(selected_model_info, "api_key") and selected_model_info.api_key:
                self._config.llm.api_key = selected_model_info.api_key
            if (
                hasattr(selected_model_info, "protocol")
                and selected_model_info.protocol
            ):
                self._config.llm.protocol = selected_model_info.protocol
        logger.info(f"模型切换: {old_model} -> {model_id}")
        self._save_config()

        # 刷新 LLMClient 的 protocol 以立即生效
        if getattr(self, '_app_instance', None):
            self._app_instance.refresh_client_config()

    # ------------------------------------------------------------------
    # Temperature / Reasoning
    # ------------------------------------------------------------------

    def _on_temperature_changed(self, value):
        temp = value / 10.0
        self._temperature_value.setText(f"{temp:.1f}")
        logger.info(f"温度设置为: {temp}")

    def _on_reasoning_changed(self, index):
        reasoning_levels = ["off", "low", "medium", "high"]
        if index > 0:
            logger.info(
                f"推理强度设置为: {reasoning_levels[index]}"
            )
        else:
            logger.info("推理模式关闭")

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _save_config(self):
        if self._config is None:
            return
        try:
            self._config.to_yaml()
            logger.info("配置已保存到 config.yaml")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    # ------------------------------------------------------------------
    # Dialog buttons
    # ------------------------------------------------------------------

    def _on_mcp_config(self):
        from llm_chat.frontends.mcp_dialog import MCPConfigDialog
        dialog = MCPConfigDialog(parent=getattr(self, '_main_window', None))
        dialog.exec()

    def _on_skills_config(self):
        from llm_chat.frontends.skills_dialog import SkillsConfigDialog
        from PyQt6.QtWidgets import QDialog
        dialog = SkillsConfigDialog(parent=getattr(self, '_main_window', None))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if getattr(self, '_app_instance', None):
                self._app_instance.reload_skills_from_config()

    def _on_models_config(self):
        from llm_chat.frontends.models_dialog import ModelsConfigDialog
        from PyQt6.QtWidgets import QDialog
        dialog = ModelsConfigDialog(config=self._config, parent=getattr(self, '_main_window', None))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if getattr(self, '_app_instance', None):
                self._app_instance.reload_skills_from_config()
                self._app_instance.refresh_client_config()
                self._init_model_combo()

    def _on_scheduler_config(self):
        from llm_chat.frontends.scheduler_dialog import SchedulerDialog
        app = getattr(self, '_app_instance', None)
        dialog = SchedulerDialog(
            parent=getattr(self, '_main_window', None),
            scheduler=app.scheduler if app else None,
            storage=app.storage if app else None,
        )
        dialog.exec()

    def _on_dashboard(self):
        from llm_chat.frontends.observability_dialog import ObservabilityDialog
        dialog = ObservabilityDialog(parent=getattr(self, '_main_window', None))
        dialog.exec()
