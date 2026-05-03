from typing import Optional, Dict, Any, List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QGroupBox, QLineEdit, QComboBox, QTextEdit, QCheckBox,
    QMessageBox, QWidget, QSplitter, QFrame, QTabWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

from llm_chat.mcp import (
    MCPManager, MCPServerConfig, MCPServerStatus,
    TransportType, MCPTool
)


class ConnectWorker(QThread):
    finished = pyqtSignal(bool, str)
    
    def __init__(self, manager: MCPManager, server_name: str, connect: bool = True):
        super().__init__()
        self.manager = manager
        self.server_name = server_name
        self.connect = connect
    
    def run(self):
        try:
            if self.connect:
                future = self.manager.connect_server(self.server_name)
                result = future.result(timeout=30)
                self.finished.emit(result, "")
            else:
                future = self.manager.disconnect_server(self.server_name)
                future.result(timeout=10)
                self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


class ServerEditDialog(QDialog):
    def __init__(self, parent=None, server_config: Optional[MCPServerConfig] = None):
        super().__init__(parent)
        self.server_config = server_config
        self.result_config: Optional[MCPServerConfig] = None
        
        self.setWindowTitle("编辑 MCP 服务器" if server_config else "添加 MCP 服务器")
        self.setMinimumWidth(500)
        
        self._setup_ui()
        
        if server_config:
            self._load_config(server_config)
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        form_layout = QVBoxLayout()
        
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("名称:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("服务器名称，如 weather")
        name_layout.addWidget(self._name_edit)
        form_layout.addLayout(name_layout)
        
        transport_layout = QHBoxLayout()
        transport_layout.addWidget(QLabel("传输方式:"))
        self._transport_combo = QComboBox()
        self._transport_combo.addItems(["stdio", "sse"])
        self._transport_combo.currentTextChanged.connect(self._on_transport_changed)
        transport_layout.addWidget(self._transport_combo)
        form_layout.addLayout(transport_layout)
        
        self._stdio_group = QGroupBox("Stdio 配置")
        stdio_layout = QVBoxLayout(self._stdio_group)
        
        cmd_layout = QHBoxLayout()
        cmd_layout.addWidget(QLabel("命令:"))
        self._command_edit = QLineEdit()
        self._command_edit.setPlaceholderText("如 npx, python, node")
        cmd_layout.addWidget(self._command_edit)
        stdio_layout.addLayout(cmd_layout)
        
        args_layout = QHBoxLayout()
        args_layout.addWidget(QLabel("参数:"))
        self._args_edit = QLineEdit()
        self._args_edit.setPlaceholderText("空格分隔的参数，如 -y @modelcontextprotocol/server-weather")
        args_layout.addWidget(self._args_edit)
        stdio_layout.addLayout(args_layout)
        
        form_layout.addWidget(self._stdio_group)
        
        self._sse_group = QGroupBox("SSE 配置")
        sse_layout = QVBoxLayout(self._sse_group)
        
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("URL:"))
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("如 http://localhost:8080/sse")
        url_layout.addWidget(self._url_edit)
        sse_layout.addLayout(url_layout)
        
        self._sse_group.hide()
        form_layout.addWidget(self._sse_group)
        
        env_group = QGroupBox("环境变量 (可选)")
        env_layout = QVBoxLayout(env_group)
        self._env_edit = QTextEdit()
        self._env_edit.setPlaceholderText("每行一个环境变量，格式: KEY=value\n如:\nAPI_KEY=your-key\nDEBUG=true")
        self._env_edit.setMaximumHeight(100)
        env_layout.addWidget(self._env_edit)
        form_layout.addWidget(env_group)
        
        desc_layout = QHBoxLayout()
        desc_layout.addWidget(QLabel("描述 (可选):"))
        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("服务器描述")
        desc_layout.addWidget(self._desc_edit)
        form_layout.addLayout(desc_layout)
        
        self._enabled_check = QCheckBox("启用")
        self._enabled_check.setChecked(True)
        form_layout.addWidget(self._enabled_check)
        
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
    
    def _on_transport_changed(self, transport: str):
        if transport == "stdio":
            self._stdio_group.show()
            self._sse_group.hide()
        else:
            self._stdio_group.hide()
            self._sse_group.show()
    
    def _load_config(self, config: MCPServerConfig):
        self._name_edit.setText(config.name)
        self._transport_combo.setCurrentText(config.transport)
        self._command_edit.setText(config.command or "")
        self._args_edit.setText(" ".join(config.args))
        self._url_edit.setText(config.url or "")
        self._desc_edit.setText(config.description or "")
        self._enabled_check.setChecked(config.enabled)
        
        env_text = "\n".join(f"{k}={v}" for k, v in config.env.items())
        self._env_edit.setPlainText(env_text)
        
        self._on_transport_changed(config.transport)
    
    def _on_save(self):
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "错误", "请输入服务器名称")
            return
        
        transport = self._transport_combo.currentText()
        
        if transport == "stdio":
            command = self._command_edit.text().strip()
            if not command:
                QMessageBox.warning(self, "错误", "请输入命令")
                return
            
            args = self._args_edit.text().strip().split()
            url = None
        else:
            url = self._url_edit.text().strip()
            if not url:
                QMessageBox.warning(self, "错误", "请输入 URL")
                return
            
            command = None
            args = []
        
        env = {}
        env_text = self._env_edit.toPlainText().strip()
        if env_text:
            for line in env_text.split("\n"):
                line = line.strip()
                if "=" in line:
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip()
        
        self.result_config = MCPServerConfig(
            name=name,
            transport=transport,
            command=command,
            args=args,
            url=url,
            env=env,
            description=self._desc_edit.text().strip() or None,
            enabled=self._enabled_check.isChecked()
        )
        
        self.accept()


class MCPConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MCP 工具配置")
        self.setMinimumSize(800, 600)
        
        self._manager = MCPManager.get_instance()
        self._workers: List[ConnectWorker] = []
        
        self._setup_ui()
        self._load_servers()
    
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        server_group = QGroupBox("MCP 服务器")
        server_layout = QVBoxLayout(server_group)
        
        self._server_table = QTableWidget()
        self._server_table.setColumnCount(4)
        self._server_table.setHorizontalHeaderLabels(["名称", "状态", "类型", "启用"])
        self._server_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._server_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._server_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._server_table.itemSelectionChanged.connect(self._on_server_selected)
        server_layout.addWidget(self._server_table)
        
        server_btn_layout = QHBoxLayout()
        
        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self._on_add_server)
        server_btn_layout.addWidget(add_btn)
        
        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(self._on_edit_server)
        server_btn_layout.addWidget(edit_btn)
        
        delete_btn = QPushButton("删除")
        delete_btn.clicked.connect(self._on_delete_server)
        server_btn_layout.addWidget(delete_btn)
        
        server_btn_layout.addStretch()
        
        connect_btn = QPushButton("连接")
        connect_btn.clicked.connect(self._on_connect_server)
        server_btn_layout.addWidget(connect_btn)
        
        disconnect_btn = QPushButton("断开")
        disconnect_btn.clicked.connect(self._on_disconnect_server)
        server_btn_layout.addWidget(disconnect_btn)
        
        server_layout.addLayout(server_btn_layout)
        left_layout.addWidget(server_group)
        
        splitter.addWidget(left_panel)
        
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        tools_group = QGroupBox("可用工具")
        tools_layout = QVBoxLayout(tools_group)
        
        self._tools_table = QTableWidget()
        self._tools_table.setColumnCount(2)
        self._tools_table.setHorizontalHeaderLabels(["工具名称", "描述"])
        self._tools_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._tools_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tools_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tools_layout.addWidget(self._tools_table)
        
        right_layout.addWidget(tools_group)
        
        splitter.addWidget(right_panel)
        splitter.setSizes([400, 400])
        
        layout.addWidget(splitter)
        
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
    
    def _load_servers(self):
        config = self._manager.get_config()
        self._server_table.setRowCount(len(config.servers))
        
        for row, server in enumerate(config.servers):
            self._server_table.setItem(row, 0, QTableWidgetItem(server.name))
            
            status_item = QTableWidgetItem("未连接")
            status_item.setForeground(QColor("#999999"))
            self._server_table.setItem(row, 1, status_item)
            
            self._server_table.setItem(row, 2, QTableWidgetItem(server.transport))
            
            enabled_item = QTableWidgetItem("是" if server.enabled else "否")
            self._server_table.setItem(row, 3, enabled_item)
    
    def _on_server_selected(self):
        selected = self._server_table.selectedItems()
        if not selected:
            self._tools_table.setRowCount(0)
            return
        
        row = selected[0].row()
        server_name = self._server_table.item(row, 0).text()
        
        server_info = self._manager.get_server_info(server_name)
        if server_info:
            self._update_tools_table(server_info.tools)
            
            status_item = self._server_table.item(row, 1)
            if server_info.status == MCPServerStatus.CONNECTED:
                status_item.setText("已连接")
                status_item.setForeground(QColor("#4CAF50"))
            elif server_info.status == MCPServerStatus.CONNECTING:
                status_item.setText("连接中...")
                status_item.setForeground(QColor("#FF9800"))
            elif server_info.status == MCPServerStatus.ERROR:
                status_item.setText("错误")
                status_item.setForeground(QColor("#F44336"))
            else:
                status_item.setText("未连接")
                status_item.setForeground(QColor("#999999"))
        else:
            self._tools_table.setRowCount(0)
    
    def _update_tools_table(self, tools: List[MCPTool]):
        self._tools_table.setRowCount(len(tools))
        for row, tool in enumerate(tools):
            self._tools_table.setItem(row, 0, QTableWidgetItem(tool.name))
            self._tools_table.setItem(row, 1, QTableWidgetItem(tool.description or ""))
    
    def _on_add_server(self):
        dialog = ServerEditDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_config:
            self._manager.add_server(dialog.result_config)
            self._load_servers()
    
    def _on_edit_server(self):
        selected = self._server_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "提示", "请先选择一个服务器")
            return
        
        row = selected[0].row()
        server_name = self._server_table.item(row, 0).text()
        server_config = self._manager.get_config().get_server(server_name)
        
        if not server_config:
            return
        
        dialog = ServerEditDialog(self, server_config)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_config:
            self._manager.remove_server(server_name)
            self._manager.add_server(dialog.result_config)
            self._load_servers()
    
    def _on_delete_server(self):
        selected = self._server_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "提示", "请先选择一个服务器")
            return
        
        row = selected[0].row()
        server_name = self._server_table.item(row, 0).text()
        
        reply = QMessageBox.question(
            self, "确认", f"确定要删除服务器 '{server_name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._manager.remove_server(server_name)
            self._load_servers()
    
    def _on_connect_server(self):
        selected = self._server_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "提示", "请先选择一个服务器")
            return
        
        row = selected[0].row()
        server_name = self._server_table.item(row, 0).text()
        
        status_item = self._server_table.item(row, 1)
        status_item.setText("连接中...")
        status_item.setForeground(QColor("#FF9800"))
        
        worker = ConnectWorker(self._manager, server_name, connect=True)
        worker.finished.connect(lambda success, msg: self._on_connect_finished(server_name, success, msg))
        worker.start()
        self._workers.append(worker)
    
    def _on_disconnect_server(self):
        selected = self._server_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "提示", "请先选择一个服务器")
            return
        
        row = selected[0].row()
        server_name = self._server_table.item(row, 0).text()
        
        worker = ConnectWorker(self._manager, server_name, connect=False)
        worker.finished.connect(lambda success, msg: self._on_disconnect_finished(server_name, success))
        worker.start()
        self._workers.append(worker)
    
    def _on_connect_finished(self, server_name: str, success: bool, error_msg: str):
        for row in range(self._server_table.rowCount()):
            if self._server_table.item(row, 0).text() == server_name:
                status_item = self._server_table.item(row, 1)
                if success:
                    status_item.setText("已连接")
                    status_item.setForeground(QColor("#4CAF50"))
                    self._on_server_selected()
                else:
                    status_item.setText("错误")
                    status_item.setForeground(QColor("#F44336"))
                    if error_msg:
                        QMessageBox.warning(self, "连接失败", f"连接服务器 '{server_name}' 失败:\n{error_msg}")
                break
    
    def _on_disconnect_finished(self, server_name: str, success: bool):
        for row in range(self._server_table.rowCount()):
            if self._server_table.item(row, 0).text() == server_name:
                status_item = self._server_table.item(row, 1)
                status_item.setText("未连接")
                status_item.setForeground(QColor("#999999"))
                self._tools_table.setRowCount(0)
                break
