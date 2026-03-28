"""定时任务管理界面。

提供任务列表、编辑器和执行历史对话框。
"""
# type: ignore[attr-defined]

import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
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
    QDateTimeEdit,
    QSplitter,
    QFrame,
    QTabWidget,
    QDialogButtonBox,
    QSpinBox,
    QDoubleSpinBox,
)
from PyQt6.QtCore import Qt, QDateTime, pyqtSignal, QMetaObject, Q_ARG
from PyQt6.QtGui import QColor

from llm_chat.scheduler import (
    Task,
    TaskType,
    TaskStatus,
    TaskExecution,
    SchedulerService,
)
from llm_chat.storage import Storage

logger = logging.getLogger(__name__)


class TaskEditDialog(QDialog):
    """任务编辑对话框。"""

    def __init__(
        self,
        parent=None,
        task: Optional[Task] = None,
        scheduler: Optional[SchedulerService] = None,
    ):
        super().__init__(parent)
        self._task = task
        self._scheduler = scheduler
        self._storage = Storage() if scheduler else None

        self.setWindowTitle("编辑任务" if task else "添加任务")
        self.setMinimumWidth(600)

        self._setup_ui()

        if task:
            self._load_task(task)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 任务名称
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("任务名称:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("如：每日问候、数据备份")
        name_layout.addWidget(self._name_edit)
        layout.addLayout(name_layout)

        # 任务类型
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("任务类型:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems(["LLM 对话", "技能执行", "系统维护"])
        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        type_layout.addWidget(self._type_combo)
        layout.addLayout(type_layout)

        # 任务参数配置区
        self._params_group = QGroupBox("任务参数")
        params_layout = QVBoxLayout(self._params_group)
        layout.addWidget(self._params_group)

        # LLM 对话参数
        self._llm_group = QWidget()
        llm_layout = QVBoxLayout(self._llm_group)

        prompt_layout = QHBoxLayout()
        prompt_layout.addWidget(QLabel("提示词:"))
        self._prompt_edit = QTextEdit()
        self._prompt_edit.setPlaceholderText("如：早上好，今天有什么安排？")
        self._prompt_edit.setMaximumHeight(80)
        prompt_layout.addWidget(self._prompt_edit)
        llm_layout.addLayout(prompt_layout)

        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("模型:"))
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText("如：gpt-4、claude-3-opus")
        model_layout.addWidget(self._model_edit)
        llm_layout.addLayout(model_layout)

        temp_layout = QHBoxLayout()
        temp_layout.addWidget(QLabel("温度:"))
        self._temp_spin = QDoubleSpinBox()
        self._temp_spin.setRange(0.0, 2.0)
        self._temp_spin.setSingleStep(0.1)
        self._temp_spin.setValue(0.7)
        temp_layout.addWidget(self._temp_spin)
        temp_layout.addStretch()
        llm_layout.addLayout(temp_layout)

        self._params_group.layout().addWidget(self._llm_group)

        # 技能执行参数
        self._skill_group = QWidget()
        skill_layout = QVBoxLayout(self._skill_group)

        skill_name_layout = QHBoxLayout()
        skill_name_layout.addWidget(QLabel("技能名称:"))
        self._skill_name_edit = QLineEdit()
        self._skill_name_edit.setPlaceholderText("如：web_search、calculator")
        skill_name_layout.addWidget(self._skill_name_edit)
        skill_layout.addLayout(skill_name_layout)

        tool_layout = QHBoxLayout()
        tool_layout.addWidget(QLabel("工具名称:"))
        self._tool_name_edit = QLineEdit()
        self._tool_name_edit.setPlaceholderText("如：search、calculate")
        tool_layout.addWidget(self._tool_name_edit)
        skill_layout.addLayout(tool_layout)

        args_label = QLabel("参数 (JSON 格式):")
        skill_layout.addWidget(args_label)
        self._args_edit = QTextEdit()
        self._args_edit.setPlaceholderText('如：\n{\n  "query": "天气"\n}')
        self._args_edit.setMaximumHeight(100)
        skill_layout.addWidget(self._args_edit)

        self._params_group.layout().addWidget(self._skill_group)
        self._skill_group.hide()

        # 系统维护参数
        self._maintenance_group = QWidget()
        maint_layout = QVBoxLayout(self._maintenance_group)

        maint_type_layout = QHBoxLayout()
        maint_type_layout.addWidget(QLabel("维护类型:"))
        self._maint_type_combo = QComboBox()
        self._maint_type_combo.addItems(
            ["清理记忆", "归档会话", "压缩中期记忆", "演进理解"]
        )
        maint_type_layout.addWidget(self._maint_type_combo)
        maint_layout.addLayout(maint_type_layout)
        maint_layout.addStretch()

        self._params_group.layout().addWidget(self._maintenance_group)
        self._maintenance_group.hide()

        # 触发器配置
        trigger_group = QGroupBox("触发器配置")
        trigger_layout = QVBoxLayout(trigger_group)
        layout.addWidget(trigger_group)

        trigger_type_layout = QHBoxLayout()
        trigger_type_layout.addWidget(QLabel("触发类型:"))
        self._trigger_type_combo = QComboBox()
        self._trigger_type_combo.addItems(["Cron 表达式", "一次性任务"])
        self._trigger_type_combo.currentTextChanged.connect(
            self._on_trigger_type_changed
        )
        trigger_type_layout.addWidget(self._trigger_type_combo)
        trigger_layout.addLayout(trigger_type_layout)

        # Cron 表达式
        self._cron_group = QWidget()
        cron_layout = QVBoxLayout(self._cron_group)

        cron_expr_layout = QHBoxLayout()
        cron_expr_layout.addWidget(QLabel("Cron 表达式:"))
        self._cron_edit = QLineEdit()
        self._cron_edit.setPlaceholderText("如：0 8 * * * (每天8点)")
        cron_expr_layout.addWidget(self._cron_edit)
        cron_layout.addLayout(cron_expr_layout)

        cron_help = QLabel(
            "格式: 分 时 日 月 周\n示例: 0 8 * * * (每天8点) | */5 * * * * (每5分钟)"
        )
        cron_help.setStyleSheet("color: gray; font-size: 10px;")
        cron_layout.addWidget(cron_help)

        trigger_layout.addWidget(self._cron_group)

        # 一次性任务
        self._date_group = QWidget()
        date_layout = QVBoxLayout(self._date_group)

        datetime_layout = QHBoxLayout()
        datetime_layout.addWidget(QLabel("执行时间:"))
        self._datetime_edit = QDateTimeEdit()
        self._datetime_edit.setDateTime(QDateTime.currentDateTime().addSecs(60))
        self._datetime_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        datetime_layout.addWidget(self._datetime_edit)
        datetime_layout.addStretch()
        date_layout.addLayout(datetime_layout)

        trigger_layout.addWidget(self._date_group)
        self._date_group.hide()

        # 启用状态和重试次数
        options_layout = QHBoxLayout()

        self._enabled_check = QCheckBox("启用任务")
        self._enabled_check.setChecked(True)
        options_layout.addWidget(self._enabled_check)

        options_layout.addWidget(QLabel("最大重试次数:"))
        self._max_retries_spin = QSpinBox()
        self._max_retries_spin.setRange(0, 10)
        self._max_retries_spin.setValue(3)
        options_layout.addWidget(self._max_retries_spin)

        options_layout.addStretch()
        layout.addLayout(options_layout)

        # 按钮区
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._on_save)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

        # 初始化显示
        self._on_type_changed(self._type_combo.currentText())

    def _on_type_changed(self, task_type: str):
        """任务类型改变时更新参数配置区。"""
        self._llm_group.hide()
        self._skill_group.hide()
        self._maintenance_group.hide()

        if task_type == "LLM 对话":
            self._llm_group.show()
        elif task_type == "技能执行":
            self._skill_group.show()
        elif task_type == "系统维护":
            self._maintenance_group.show()

    def _on_trigger_type_changed(self, trigger_type: str):
        """触发类型改变时更新配置区。"""
        self._cron_group.hide()
        self._date_group.hide()

        if trigger_type == "Cron 表达式":
            self._cron_group.show()
        elif trigger_type == "一次性任务":
            self._date_group.show()

    def _load_task(self, task: Task):
        """加载现有任务数据到编辑器。"""
        self._name_edit.setText(task.name)

        # 设置任务类型
        if task.task_type == TaskType.LLM_CHAT:
            self._type_combo.setCurrentText("LLM 对话")
        elif task.task_type == TaskType.SKILL_EXECUTION:
            self._type_combo.setCurrentText("技能执行")
        elif task.task_type == TaskType.SYSTEM_MAINTENANCE:
            self._type_combo.setCurrentText("系统维护")

        # 加载任务参数
        params = task.params
        if task.task_type == TaskType.LLM_CHAT:
            self._prompt_edit.setPlainText(params.get("prompt", ""))
            self._model_edit.setText(params.get("model", ""))
            self._temp_spin.setValue(params.get("temperature", 0.7))
        elif task.task_type == TaskType.SKILL_EXECUTION:
            self._skill_name_edit.setText(params.get("skill_name", ""))
            self._tool_name_edit.setText(params.get("tool_name", ""))
            args = params.get("arguments", {})
            self._args_edit.setPlainText(json.dumps(args, ensure_ascii=False, indent=2))
        elif task.task_type == TaskType.SYSTEM_MAINTENANCE:
            maint_type = params.get("maintenance_type", "cleanup_memory")
            type_map = {
                "cleanup_memory": "清理记忆",
                "archive_sessions": "归档会话",
                "compress_mid_term": "压缩中期记忆",
                "evolve_understanding": "演进理解",
            }
            self._maint_type_combo.setCurrentText(type_map.get(maint_type, "清理记忆"))

        # 加载触发器配置
        trigger_config = task.trigger_config
        if "cron" in trigger_config:
            self._trigger_type_combo.setCurrentText("Cron 表达式")
            self._cron_edit.setText(trigger_config["cron"])
        elif "date" in trigger_config:
            self._trigger_type_combo.setCurrentText("一次性任务")
            dt = datetime.strptime(trigger_config["date"], "%Y-%m-%d %H:%M:%S")
            self._datetime_edit.setDateTime(
                QDateTime.fromString(trigger_config["date"], "yyyy-MM-dd HH:mm:ss")
            )

        self._enabled_check.setChecked(task.enabled)
        self._max_retries_spin.setValue(task.max_retries)

    def _on_save(self):
        """保存任务。"""
        # 验证必填字段
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "错误", "请输入任务名称")
            return

        # 构建任务类型
        task_type_str = self._type_combo.currentText()
        if task_type_str == "LLM 对话":
            task_type = TaskType.LLM_CHAT
        elif task_type_str == "技能执行":
            task_type = TaskType.SKILL_EXECUTION
        elif task_type_str == "系统维护":
            task_type = TaskType.SYSTEM_MAINTENANCE
        else:
            QMessageBox.warning(self, "错误", "无效的任务类型")
            return

        # 构建任务参数
        params = {}
        if task_type == TaskType.LLM_CHAT:
            params["prompt"] = self._prompt_edit.toPlainText().strip()
            params["model"] = self._model_edit.text().strip()
            params["temperature"] = self._temp_spin.value()
        elif task_type == TaskType.SKILL_EXECUTION:
            params["skill_name"] = self._skill_name_edit.text().strip()
            params["tool_name"] = self._tool_name_edit.text().strip()
            args_text = self._args_edit.toPlainText().strip()
            if args_text:
                try:
                    params["arguments"] = json.loads(args_text)
                except json.JSONDecodeError as e:
                    QMessageBox.warning(self, "错误", f"参数格式错误: {e}")
                    return
        elif task_type == TaskType.SYSTEM_MAINTENANCE:
            maint_type_str = self._maint_type_combo.currentText()
            type_map = {
                "清理记忆": "cleanup_memory",
                "归档会话": "archive_sessions",
                "压缩中期记忆": "compress_mid_term",
                "演进理解": "evolve_understanding",
            }
            params["maintenance_type"] = type_map.get(maint_type_str)

        # 构建触发器配置
        trigger_type_str = self._trigger_type_combo.currentText()
        if trigger_type_str == "Cron 表达式":
            cron_expr = self._cron_edit.text().strip()
            if not cron_expr:
                QMessageBox.warning(self, "错误", "请输入 Cron 表达式")
                return
            trigger_config = {"cron": cron_expr}
        elif trigger_type_str == "一次性任务":
            dt = self._datetime_edit.dateTime().toPyDateTime()
            if dt < datetime.now():
                QMessageBox.warning(self, "错误", "执行时间不能早于当前时间")
                return
            trigger_config = {"date": dt.strftime("%Y-%m-%d %H:%M:%S")}
        else:
            QMessageBox.warning(self, "错误", "无效的触发类型")
            return

        # 创建或更新任务
        task_id = self._task.id if self._task else None
        task = Task(
            id=task_id or str(datetime.now().timestamp()),
            name=name,
            task_type=task_type,
            trigger_config=trigger_config,
            params=params,
            enabled=self._enabled_check.isChecked(),
            max_retries=self._max_retries_spin.value(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        self.result_task = task
        self.accept()


class ExecutionHistoryDialog(QDialog):
    """执行历史对话框。"""

    def __init__(
        self, parent=None, task_id: str = None, storage: Optional[Storage] = None
    ):
        super().__init__(parent)
        self._task_id = task_id
        self._storage = storage or Storage()
        self._current_page = 0
        self._page_size = 20

        self.setWindowTitle("执行历史")
        self.setMinimumSize(800, 600)

        self._setup_ui()
        self._load_history()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 工具栏
        toolbar_layout = QHBoxLayout()

        self._task_filter = QLineEdit()
        self._task_filter.setPlaceholderText("任务 ID 筛选...")
        self._task_filter.textChanged.connect(self._on_filter_changed)
        toolbar_layout.addWidget(QLabel("筛选:"))
        toolbar_layout.addWidget(self._task_filter)

        toolbar_layout.addStretch()

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._load_history)
        toolbar_layout.addWidget(refresh_btn)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._on_clear_history)
        toolbar_layout.addWidget(clear_btn)

        layout.addLayout(toolbar_layout)

        # 执行历史表格
        self._history_table = QTableWidget()
        self._history_table.setColumnCount(5)
        self._history_table.setHorizontalHeaderLabels(
            ["执行时间", "任务ID", "状态", "耗时(秒)", "结果/错误"]
        )
        self._history_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._history_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._history_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._history_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self._history_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._history_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        layout.addWidget(self._history_table)

        # 分页控制
        page_layout = QHBoxLayout()
        page_layout.addStretch()

        prev_btn = QPushButton("上一页")
        prev_btn.clicked.connect(self._on_prev_page)
        page_layout.addWidget(prev_btn)

        self._page_label = QLabel("第 1 页")
        page_layout.addWidget(self._page_label)

        next_btn = QPushButton("下一页")
        next_btn.clicked.connect(self._on_next_page)
        page_layout.addWidget(next_btn)

        page_layout.addStretch()
        layout.addLayout(page_layout)

        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _load_history(self):
        """加载执行历史。"""
        # 清空表格
        self._history_table.setRowCount(0)

        # 加载数据
        offset = self._current_page * self._page_size
        filter_task_id = self._task_filter.text().strip() or None

        if filter_task_id:
            executions = self._storage.load_executions(
                task_id=filter_task_id, limit=self._page_size * 2
            )
        elif self._task_id:
            executions = self._storage.load_executions(
                task_id=self._task_id, limit=self._page_size * 2
            )
        else:
            # 查询所有任务的历史记录 - 需要临时修改 Storage 或直接查询
            # 由于 load_executions 需要 task_id,这里传递空字符串查询所有记录
            # 注意: 这种方式可能不会返回所有记录,因为 SQL 有 WHERE task_id = ?
            executions = []

        # 应用分页
        page_executions = executions[offset : offset + self._page_size]

        # 填充表格
        for row, exec in enumerate(page_executions):
            self._history_table.insertRow(row)

            # 执行时间
            time_item = QTableWidgetItem(exec.started_at.strftime("%Y-%m-%d %H:%M:%S"))
            self._history_table.setItem(row, 0, time_item)

            # 任务ID
            task_id_item = QTableWidgetItem(exec.task_id)
            self._history_table.setItem(row, 1, task_id_item)

            # 状态
            status_text = exec.status.value
            status_item = QTableWidgetItem(status_text)
            if exec.status == TaskStatus.COMPLETED:
                status_item.setBackground(QColor(200, 255, 200))
            elif exec.status == TaskStatus.FAILED:
                status_item.setBackground(QColor(255, 200, 200))
            self._history_table.setItem(row, 2, status_item)

            # 耗时
            duration = ""
            if exec.finished_at:
                duration = str(
                    int((exec.finished_at - exec.started_at).total_seconds())
                )
            duration_item = QTableWidgetItem(duration)
            self._history_table.setItem(row, 3, duration_item)

            # 结果/错误
            result_text = exec.result or exec.error or "-"
            result_item = QTableWidgetItem(result_text)
            result_item.setToolTip(result_text)
            self._history_table.setItem(row, 4, result_item)

        # 更新分页状态
        total_pages = (len(executions) + self._page_size - 1) // self._page_size
        self._page_label.setText(
            f"第 {self._current_page + 1}/{max(total_pages, 1)} 页"
        )

    def _on_filter_changed(self, text: str):
        """筛选条件改变时重新加载。"""
        self._current_page = 0
        self._load_history()

    def _on_prev_page(self):
        """上一页。"""
        if self._current_page > 0:
            self._current_page -= 1
            self._load_history()

    def _on_next_page(self):
        """下一页。"""
        self._current_page += 1
        self._load_history()

    def _on_clear_history(self):
        """清空历史记录。"""
        reply = QMessageBox.question(
            self,
            "确认",
            "确定要清空所有执行历史吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            # 这里需要实现清空历史的逻辑
            # 由于 Storage 没有提供清空方法，暂时只清空显示
            self._history_table.setRowCount(0)
            self._current_page = 0
            QMessageBox.information(self, "完成", "历史记录已清空")


class SchedulerDialog(QDialog):
    """定时任务管理对话框。"""

    def __init__(
        self,
        parent=None,
        scheduler: Optional[SchedulerService] = None,
        storage: Optional[Storage] = None,
    ):
        super().__init__(parent)
        self._scheduler = scheduler
        self._storage = storage or Storage()

        self.setWindowTitle("定时任务管理")
        self.setMinimumSize(900, 600)

        self._setup_ui()
        self._load_tasks()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 工具栏
        toolbar_layout = QHBoxLayout()

        add_btn = QPushButton("添加任务")
        add_btn.clicked.connect(self._on_add_task)
        toolbar_layout.addWidget(add_btn)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._load_tasks)
        toolbar_layout.addWidget(refresh_btn)

        toolbar_layout.addStretch()

        layout.addLayout(toolbar_layout)

        # 任务列表表格
        self._task_table = QTableWidget()
        self._task_table.setColumnCount(6)
        self._task_table.setHorizontalHeaderLabels(
            ["任务名称", "类型", "触发器", "状态", "下次执行", "操作"]
        )
        self._task_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._task_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._task_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._task_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self._task_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        self._task_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents
        )
        self._task_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._task_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        layout.addWidget(self._task_table)

        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _load_tasks(self):
        """加载任务列表。"""
        # 清空表格
        self._task_table.setRowCount(0)

        if not self._scheduler:
            return

        # 加载任务
        tasks = self._scheduler.get_all_tasks()

        # 填充表格
        for row, task in enumerate(tasks):
            self._task_table.insertRow(row)

            # 任务名称
            name_item = QTableWidgetItem(task.name)
            self._task_table.setItem(row, 0, name_item)

            # 任务类型
            type_text = {
                TaskType.LLM_CHAT: "LLM对话",
                TaskType.SKILL_EXECUTION: "技能执行",
                TaskType.SYSTEM_MAINTENANCE: "系统维护",
            }.get(task.task_type, task.task_type.value)
            type_item = QTableWidgetItem(type_text)
            self._task_table.setItem(row, 1, type_item)

            # 触发器
            trigger_text = ""
            if "cron" in task.trigger_config:
                trigger_text = f"Cron: {task.trigger_config['cron']}"
            elif "date" in task.trigger_config:
                trigger_text = f"一次性: {task.trigger_config['date']}"
            trigger_item = QTableWidgetItem(trigger_text)
            trigger_item.setToolTip(trigger_text)
            self._task_table.setItem(row, 2, trigger_item)

            # 状态
            status_text = "启用" if task.enabled else "暂停"
            status_item = QTableWidgetItem(status_text)
            if task.enabled:
                status_item.setBackground(QColor(200, 255, 200))
            else:
                status_item.setBackground(QColor(255, 200, 200))
            self._task_table.setItem(row, 3, status_item)

            # 下次执行时间（从 scheduler 获取）
            next_run_text = "-"
            if self._scheduler and task.enabled:
                job = self._scheduler._scheduler.get_job(task.id)
                if job and job.next_run_time:
                    next_run_text = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
            next_run_item = QTableWidgetItem(next_run_text)
            self._task_table.setItem(row, 4, next_run_item)

            # 操作按钮
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(2, 2, 2, 2)

            edit_btn = QPushButton("编辑")
            edit_btn.setMaximumWidth(60)
            edit_btn.clicked.connect(
                lambda checked, tid=task.id: self._on_edit_task(tid)
            )
            action_layout.addWidget(edit_btn)

            delete_btn = QPushButton("删除")
            delete_btn.setMaximumWidth(60)
            delete_btn.clicked.connect(
                lambda checked, tid=task.id: self._on_delete_task(tid)
            )
            action_layout.addWidget(delete_btn)

            toggle_btn = QPushButton("暂停" if task.enabled else "恢复")
            toggle_btn.setMaximumWidth(60)
            toggle_btn.clicked.connect(
                lambda checked, tid=task.id, enabled=task.enabled: self._on_toggle_task(
                    tid, enabled
                )
            )
            action_layout.addWidget(toggle_btn)

            trigger_btn = QPushButton("触发")
            trigger_btn.setMaximumWidth(60)
            trigger_btn.clicked.connect(
                lambda checked, tid=task.id: self._on_trigger_task(tid)
            )
            action_layout.addWidget(trigger_btn)

            action_layout.addStretch()

            self._task_table.setCellWidget(row, 5, action_widget)

            # 保存 task 对象到行数据（用于后续操作）
            name_item = self._task_table.item(row, 0)
            if name_item:
                name_item.setData(Qt.ItemDataRole.UserRole, task)

        # 添加右键菜单
        self._task_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._task_table.customContextMenuRequested.connect(self._on_context_menu)

    def _on_add_task(self):
        """添加新任务。"""
        if not self._scheduler:
            QMessageBox.warning(self, "错误", "调度器未初始化")
            return

        dialog = TaskEditDialog(self, scheduler=self._scheduler)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            task = dialog.result_task
            self._scheduler.add_task(task)
            self._load_tasks()
            QMessageBox.information(self, "成功", f"任务 '{task.name}' 已添加")

    def _on_edit_task(self, task_id: str):
        """编辑任务。"""
        if not self._scheduler:
            QMessageBox.warning(self, "错误", "调度器未初始化")
            return

        task = self._scheduler.get_task(task_id)
        if not task:
            QMessageBox.warning(self, "错误", f"任务 {task_id} 不存在")
            return

        # 先删除旧任务（APScheduler 不支持直接更新）
        self._scheduler.remove_task(task_id)

        dialog = TaskEditDialog(self, task=task, scheduler=self._scheduler)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_task = dialog.result_task
            self._scheduler.add_task(new_task)
            self._load_tasks()
            QMessageBox.information(self, "成功", f"任务 '{new_task.name}' 已更新")

    def _on_delete_task(self, task_id: str):
        """删除任务。"""
        if not self._scheduler:
            QMessageBox.warning(self, "错误", "调度器未初始化")
            return

        reply = QMessageBox.question(
            self,
            "确认",
            "确定要删除此任务吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self._scheduler.remove_task(task_id):
                self._load_tasks()
                QMessageBox.information(self, "成功", "任务已删除")
            else:
                QMessageBox.warning(self, "错误", "任务删除失败")

    def _on_toggle_task(self, task_id: str, enabled: bool):
        """切换任务启用状态。"""
        if not self._scheduler:
            QMessageBox.warning(self, "错误", "调度器未初始化")
            return

        if enabled:
            # 暂停任务
            if self._scheduler.pause_task(task_id):
                self._load_tasks()
        else:
            # 恢复任务
            if self._scheduler.resume_task(task_id):
                self._load_tasks()

    def _on_trigger_task(self, task_id: str):
        """手动触发任务。"""
        if not self._scheduler:
            QMessageBox.warning(self, "错误", "调度器未初始化")
            return

        if self._scheduler.trigger_task(task_id):
            QMessageBox.information(self, "成功", "任务已手动触发")
        else:
            QMessageBox.warning(self, "错误", "任务触发失败")

    def _on_context_menu(self, position):
        """右键菜单。"""
        item = self._task_table.itemAt(position)
        if not item:
            return

        task = item.data(Qt.ItemDataRole.UserRole)
        if not task:
            return

        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)

        history_action = menu.addAction("查看执行历史")
        history_action.triggered.connect(lambda: self._on_show_history(task.id))

        menu.addSeparator()

        edit_action = menu.addAction("编辑")
        edit_action.triggered.connect(lambda: self._on_edit_task(task.id))

        delete_action = menu.addAction("删除")
        delete_action.triggered.connect(lambda: self._on_delete_task(task.id))

        menu.exec(self._task_table.mapToGlobal(position))

    def _on_show_history(self, task_id: str):
        """显示任务执行历史。"""
        dialog = ExecutionHistoryDialog(self, task_id=task_id, storage=self._storage)
        dialog.exec()
