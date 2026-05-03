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
        self._model_combo.clear()
        if self._config is None:
            self._model_combo.addItem(self._current_model)
            self._model_combo.setCurrentText(self._current_model)
            return
        available_models = getattr(self._config.llm, "available_models", [])
        if available_models:
            for model_info in available_models:
                if hasattr(model_info, "name"):
                    model_name = model_info.name
                elif hasattr(model_info, "get"):
                    model_name = model_info.get("id")
                else:
                    model_name = str(model_info)
                self._model_combo.addItem(model_name)
            current_model = self._config.llm.model
            index = self._model_combo.findText(current_model)
            if index >= 0:
                self._model_combo.setCurrentIndex(index)
            else:
                self._model_combo.setCurrentText(current_model)
        else:
            self._model_combo.addItem(self._current_model)
            self._model_combo.setCurrentText(self._current_model)

    def _on_model_changed(self, index: int):
        if self._config is None or self._model_combo is None:
            return
        model_name = self._model_combo.currentText()
        old_model = self._config.llm.model
        if model_name == old_model:
            return
        available_models = getattr(self._config.llm, "available_models", [])
        model_id = model_name
        selected_model_info = None
        if available_models:
            for model_info in available_models:
                info_name = (
                    model_info.name
                    if hasattr(model_info, "name")
                    else (
                        model_info.get("name")
                        if hasattr(model_info, "get")
                        else str(model_info)
                    )
                )
                if info_name == model_name:
                    model_id = (
                        model_info.id
                        if hasattr(model_info, "id")
                        else (
                            model_info.get("id")
                            if hasattr(model_info, "get")
                            else model_name
                        )
                    )
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
        dialog = MCPConfigDialog(parent=None)
        dialog.exec()

    def _on_skills_config(self):
        from llm_chat.frontends.skills_dialog import SkillsConfigDialog
        from PyQt6.QtWidgets import QDialog
        dialog = SkillsConfigDialog(parent=None)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if getattr(self, '_app_instance', None):
                self._app_instance.reload_skills_from_config()

    def _on_models_config(self):
        from llm_chat.frontends.models_dialog import ModelsConfigDialog
        from PyQt6.QtWidgets import QDialog
        dialog = ModelsConfigDialog(config=self._config, parent=None)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if getattr(self, '_app_instance', None):
                self._app_instance.reload_skills_from_config()
                self._init_model_combo()

    def _on_scheduler_config(self):
        from llm_chat.frontends.scheduler_dialog import SchedulerDialog
        app = getattr(self, '_app_instance', None)
        dialog = SchedulerDialog(
            parent=None,
            scheduler=app.scheduler if app else None,
            storage=app.storage if app else None,
        )
        dialog.exec()

    def _on_dashboard(self):
        from llm_chat.frontends.observability_dialog import ObservabilityDialog
        dialog = ObservabilityDialog(parent=None)
        dialog.exec()
