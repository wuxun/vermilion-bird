import logging
from typing import Optional, List, Dict, Any
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QGroupBox,
    QLineEdit,
    QComboBox,
    QTextEdit,
    QCheckBox,
    QMessageBox,
    QWidget,
    QSplitter,
    QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

logger = logging.getLogger(__name__)


class ModelEditDialog(QDialog):
    def __init__(self, parent=None, model_config: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.model_config = model_config
        self.result_config: Optional[Dict[str, Any]] = None

        self.setWindowTitle("编辑模型" if model_config else "添加模型")
        self.setMinimumWidth(500)

        self._setup_ui()

        if model_config:
            self._load_config(model_config)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        form_layout = QVBoxLayout()

        id_layout = QHBoxLayout()
        id_layout.addWidget(QLabel("模型 ID:"))
        self._id_edit = QLineEdit()
        self._id_edit.setPlaceholderText("如 gpt-4, deepseek-ai/DeepSeek-V3")
        id_layout.addWidget(self._id_edit)
        form_layout.addLayout(id_layout)

        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("显示名称:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("如 GPT-4, DeepSeek V3")
        name_layout.addWidget(self._name_edit)
        form_layout.addLayout(name_layout)

        desc_layout = QHBoxLayout()
        desc_layout.addWidget(QLabel("描述:"))
        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("模型描述（可选）")
        desc_layout.addWidget(self._desc_edit)
        form_layout.addLayout(desc_layout)

        api_group = QGroupBox("API 配置")
        api_layout = QVBoxLayout(api_group)

        base_url_layout = QHBoxLayout()
        base_url_layout.addWidget(QLabel("Base URL:"))
        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText("如 https://api.openai.com/v1")
        base_url_layout.addWidget(self._base_url_edit)
        api_layout.addLayout(base_url_layout)

        api_key_layout = QHBoxLayout()
        api_key_layout.addWidget(QLabel("API Key:"))
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("留空则使用全局配置")
        api_key_layout.addWidget(self._api_key_edit)
        api_layout.addLayout(api_key_layout)

        protocol_layout = QHBoxLayout()
        protocol_layout.addWidget(QLabel("协议:"))
        self._protocol_combo = QComboBox()
        self._protocol_combo.addItems(["openai", "anthropic", "gemini"])
        protocol_layout.addWidget(self._protocol_combo)
        api_layout.addLayout(protocol_layout)

        form_layout.addWidget(api_group)

        layout.addLayout(form_layout)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._on_save)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _load_config(self, config: Dict[str, Any]):
        self._id_edit.setText(config.get("id", ""))
        self._name_edit.setText(config.get("name", ""))
        self._desc_edit.setText(config.get("description", ""))
        self._base_url_edit.setText(config.get("base_url", ""))
        self._api_key_edit.setText(config.get("api_key", ""))
        protocol = config.get("protocol", "openai")
        index = self._protocol_combo.findText(protocol)
        if index >= 0:
            self._protocol_combo.setCurrentIndex(index)

    def _on_save(self):
        model_id = self._id_edit.text().strip()
        if not model_id:
            QMessageBox.warning(self, "错误", "请输入模型 ID")
            return

        name = self._name_edit.text().strip()
        if not name:
            name = model_id

        self.result_config = {
            "id": model_id,
            "name": name,
            "description": self._desc_edit.text().strip() or None,
            "base_url": self._base_url_edit.text().strip() or None,
            "api_key": self._api_key_edit.text().strip() or None,
            "protocol": self._protocol_combo.currentText(),
        }

        self.accept()


class ModelsConfigDialog(QDialog):
    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self._config = config
        self._models_data: List[Dict[str, Any]] = []
        self._current_model_index = -1

        self.setWindowTitle("模型配置")
        self.setMinimumSize(800, 500)

        self._load_models()
        self._setup_ui()

    def _load_models(self):
        if self._config is None:
            return

        available_models = getattr(self._config.llm, "available_models", [])
        self._models_data = []

        for model_info in available_models:
            if hasattr(model_info, "model_dump"):
                self._models_data.append(model_info.model_dump())
            elif hasattr(model_info, "__dict__"):
                self._models_data.append(
                    {
                        "id": getattr(model_info, "id", ""),
                        "name": getattr(model_info, "name", ""),
                        "description": getattr(model_info, "description", ""),
                        "base_url": getattr(model_info, "base_url", None),
                        "api_key": getattr(model_info, "api_key", None),
                        "protocol": getattr(model_info, "protocol", "openai"),
                    }
                )
            elif isinstance(model_info, dict):
                self._models_data.append(model_info.copy())

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        left_layout.addWidget(QLabel("可用模型:"))

        self._models_table = QTableWidget()
        self._models_table.setColumnCount(3)
        self._models_table.setHorizontalHeaderLabels(["名称", "ID", "协议"])
        self._models_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._models_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._models_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._models_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._models_table.itemSelectionChanged.connect(self._on_model_selected)
        left_layout.addWidget(self._models_table)

        button_layout = QHBoxLayout()

        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self._on_add_model)
        button_layout.addWidget(add_btn)

        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(self._on_edit_model)
        button_layout.addWidget(edit_btn)

        delete_btn = QPushButton("删除")
        delete_btn.clicked.connect(self._on_delete_model)
        button_layout.addWidget(delete_btn)

        set_default_btn = QPushButton("设为默认")
        set_default_btn.clicked.connect(self._on_set_default)
        button_layout.addWidget(set_default_btn)

        left_layout.addLayout(button_layout)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        right_layout.addWidget(QLabel("模型详情:"))

        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        right_layout.addWidget(self._detail_text)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([500, 300])

        layout.addWidget(splitter)

        close_layout = QHBoxLayout()
        close_layout.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_layout.addWidget(close_btn)

        layout.addLayout(close_layout)

        self._refresh_models_table()

    def _refresh_models_table(self):
        self._models_table.setRowCount(0)

        current_model = self._config.llm.model if self._config else ""

        for i, model in enumerate(self._models_data):
            row = self._models_table.rowCount()
            self._models_table.insertRow(row)

            name = model.get("name", model.get("id", ""))
            is_default = model.get("id") == current_model
            display_name = f"{name} (默认)" if is_default else name

            name_item = QTableWidgetItem(display_name)
            if is_default:
                name_item.setForeground(QColor("#4CAF50"))
            self._models_table.setItem(row, 0, name_item)

            self._models_table.setItem(row, 1, QTableWidgetItem(model.get("id", "")))
            self._models_table.setItem(
                row, 2, QTableWidgetItem(model.get("protocol", "openai"))
            )

    def _on_model_selected(self):
        selected = self._models_table.selectedItems()
        if not selected:
            self._detail_text.clear()
            return

        row = selected[0].row()
        if row < len(self._models_data):
            model = self._models_data[row]
            self._current_model_index = row
            self._show_model_detail(model)

    def _show_model_detail(self, model: Dict[str, Any]):
        detail = f"""模型 ID: {model.get("id", "N/A")}
显示名称: {model.get("name", "N/A")}
描述: {model.get("description", "N/A")}

API 配置:
  Base URL: {model.get("base_url", "使用全局配置")}
  协议: {model.get("protocol", "openai")}
  API Key: {"已配置" if model.get("api_key") else "使用全局配置"}
"""
        self._detail_text.setPlainText(detail)

    def _on_add_model(self):
        dialog = ModelEditDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.result_config:
                self._models_data.append(dialog.result_config)
                self._refresh_models_table()
                self._save_to_config()

    def _on_edit_model(self):
        selected = self._models_table.selectedItems()
        if not selected:
            QMessageBox.information(self, "提示", "请先选择一个模型")
            return

        row = selected[0].row()
        if row < len(self._models_data):
            model = self._models_data[row]
            dialog = ModelEditDialog(self, model)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                if dialog.result_config:
                    self._models_data[row] = dialog.result_config
                    self._refresh_models_table()
                    self._save_to_config()

    def _on_delete_model(self):
        selected = self._models_table.selectedItems()
        if not selected:
            QMessageBox.information(self, "提示", "请先选择一个模型")
            return

        row = selected[0].row()
        if row < len(self._models_data):
            model = self._models_data[row]
            reply = QMessageBox.question(
                self,
                "确认删除",
                f"确定要删除模型 '{model.get('name', model.get('id'))}' 吗?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._models_data.pop(row)
                self._refresh_models_table()
                self._save_to_config()

    def _on_set_default(self):
        selected = self._models_table.selectedItems()
        if not selected:
            QMessageBox.information(self, "提示", "请先选择一个模型")
            return

        row = selected[0].row()
        if row < len(self._models_data):
            model = self._models_data[row]
            model_id = model.get("id")
            if self._config:
                self._config.llm.model = model_id
                self._refresh_models_table()
                self._save_to_config()
                QMessageBox.information(
                    self, "成功", f"已将 '{model.get('name')}' 设为默认模型"
                )

    def _save_to_config(self):
        if self._config is None:
            return

        from llm_chat.config import ModelInfo

        model_infos = []
        for model_data in self._models_data:
            model_infos.append(
                ModelInfo(
                    id=model_data.get("id", ""),
                    name=model_data.get("name", ""),
                    description=model_data.get("description"),
                    base_url=model_data.get("base_url"),
                    api_key=model_data.get("api_key"),
                    protocol=model_data.get("protocol", "openai"),
                )
            )

        self._config.llm.available_models = model_infos

        try:
            self._config.to_yaml()
            logger.info("模型配置已保存到 config.yaml")
        except Exception as e:
            logger.error(f"保存模型配置失败: {e}")
            QMessageBox.warning(self, "错误", f"保存配置失败: {e}")
