import logging
from typing import Dict, Any, List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

logger = logging.getLogger(__name__)


class SkillsConfigDialog(QDialog):
    """技能配置对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("技能管理")
        self.setMinimumSize(650, 450)
        self._skill_states: Dict[str, bool] = {}
        self._skills_data: Dict[str, Dict[str, Any]] = {}
        self._setup_ui()
        self._load_skills()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        label = QLabel("可用技能列表")
        label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(label)
        
        self._skills_list = QListWidget()
        self._skills_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #D4A574;
                border-radius: 4px;
                background-color: #FFFBF5;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #E0D0C0;
                color: #3D2C2E;
            }
            QListWidget::item:selected {
                background-color: #F5E6D3;
                color: #3D2C2E;
            }
            QListWidget::item:hover {
                background-color: #F5E6D3;
            }
        """)
        layout.addWidget(self._skills_list)
        
        button_layout = QHBoxLayout()
        
        self._toggle_btn = QPushButton("启用/禁用")
        self._toggle_btn.clicked.connect(self._toggle_skill)
        self._toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: #D4652F;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #C84B31;
            }
        """)
        button_layout.addWidget(self._toggle_btn)
        
        self._info_btn = QPushButton("查看详情")
        self._info_btn.clicked.connect(self._show_info)
        self._info_btn.setStyleSheet("""
            QPushButton {
                background-color: #5C3D3A;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #6B4D4A;
            }
        """)
        button_layout.addWidget(self._info_btn)
        
        button_layout.addStretch()
        
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #D4A574;
                color: #3D2C2E;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #C49464;
            }
        """)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def _load_skills(self):
        from llm_chat.skills.web_search.skill import WebSearchSkill
        from llm_chat.skills.calculator.skill import CalculatorSkill
        from llm_chat.skills.web_fetch.skill import WebFetchSkill
        from llm_chat.skills.manager import SkillManager
        from llm_chat.config import Config
        
        config = Config()
        manager = SkillManager()
        manager.register_skill_class(WebSearchSkill)
        manager.register_skill_class(CalculatorSkill)
        manager.register_skill_class(WebFetchSkill)
        
        for name, skill_class in manager.get_all_skill_classes().items():
            skill = skill_class()
            tools = skill.get_tools()
            tool_names = ", ".join([t.name for t in tools])
            
            enabled = True
            if hasattr(config.skills, name):
                skill_config = getattr(config.skills, name, None)
                if skill_config and hasattr(skill_config, 'enabled'):
                    enabled = skill_config.enabled
            
            self._skill_states[name] = enabled
            
            status = "✓ 已启用" if enabled else "○ 已禁用"
            item = QListWidgetItem()
            item.setText(f"{status}  {name}\n      版本: {skill.version} | 工具: {tool_names}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setForeground(Qt.GlobalColor.darkGray)
            self._skills_list.addItem(item)
            
            self._skills_data[name] = {
                'version': skill.version,
                'description': skill.description,
                'dependencies': skill.dependencies,
                'tools': tools
            }
    
    def _toggle_skill(self):
        current_item = self._skills_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "提示", "请先选择一个技能")
            return
        
        skill_name = current_item.data(Qt.ItemDataRole.UserRole)
        self._skill_states[skill_name] = not self._skill_states[skill_name]
        
        data = self._skills_data[skill_name]
        tool_names = ", ".join([t.name for t in data['tools']])
        status = "✓ 已启用" if self._skill_states[skill_name] else "○ 已禁用"
        current_item.setText(f"{status}  {skill_name}\n      版本: {data['version']} | 工具: {tool_names}")
        
        logger.info(f"技能 {skill_name} 状态切换为: {'启用' if self._skill_states[skill_name] else '禁用'}")
    
    def _show_info(self):
        current_item = self._skills_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "提示", "请先选择一个技能")
            return
        
        skill_name = current_item.data(Qt.ItemDataRole.UserRole)
        data = self._skills_data.get(skill_name, {})
        
        info_text = f"""技能名称: {skill_name}
版本: {data.get('version', 'N/A')}
描述: {data.get('description', 'N/A')}
依赖: {', '.join(data.get('dependencies', [])) or '无'}

工具列表:"""
        
        for tool in data.get('tools', []):
            info_text += f"\n\n  【{tool.name}】\n  描述: {tool.description}"
            params = tool.get_parameters_schema()
            if params.get('properties'):
                info_text += "\n  参数:"
                for prop, schema in params['properties'].items():
                    required = prop in params.get('required', [])
                    req_mark = "*" if required else ""
                    desc = schema.get('description', '')
                    default = schema.get('default', '无')
                    info_text += f"\n    - {prop}{req_mark}: {desc} (默认: {default})"
        
        QMessageBox.information(self, f"技能详情 - {skill_name}", info_text)
