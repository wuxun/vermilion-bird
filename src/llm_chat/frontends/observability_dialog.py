"""Token & 成本仪表盘 — 实时显示 LLM 调用统计。"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QGridLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont


class ObservabilityDialog(QDialog):
    """可观测性仪表盘 — Token 消耗、成本、工具调用统计。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Token & 成本仪表盘")
        self.setMinimumSize(550, 450)
        self.setModal(False)  # 非模态，可保留打开

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)  # 每 2 秒刷新

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 布局
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # -- 标题 --
        title = QLabel("📊 Token & 成本仪表盘")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 8px;")
        layout.addWidget(title)

        # -- 概览卡片 --
        self._card_group = QGroupBox("会话概览")
        card_grid = QGridLayout()
        self._lbl_tokens = QLabel("0")
        self._lbl_cost = QLabel("$0.00")
        self._lbl_calls = QLabel("0")
        self._lbl_avg_ms = QLabel("0 ms")
        self._lbl_tools = QLabel("0")

        card_grid.addWidget(QLabel("总 Token"), 0, 0)
        card_grid.addWidget(self._lbl_tokens, 0, 1)
        card_grid.addWidget(QLabel("估算成本"), 0, 2)
        card_grid.addWidget(self._lbl_cost, 0, 3)
        card_grid.addWidget(QLabel("LLM 调用"), 1, 0)
        card_grid.addWidget(self._lbl_calls, 1, 1)
        card_grid.addWidget(QLabel("平均延迟"), 1, 2)
        card_grid.addWidget(self._lbl_avg_ms, 1, 3)
        card_grid.addWidget(QLabel("工具调用"), 2, 0)
        card_grid.addWidget(self._lbl_tools, 2, 1)

        self._card_group.setLayout(card_grid)
        layout.addWidget(self._card_group)

        # -- 模型明细表 --
        self._model_group = QGroupBox("按模型")
        model_layout = QVBoxLayout()
        self._model_table = QTableWidget()
        self._model_table.setColumnCount(3)
        self._model_table.setHorizontalHeaderLabels(["模型", "Token 数", "估算成本"])
        self._model_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._model_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._model_table.verticalHeader().setVisible(False)
        model_layout.addWidget(self._model_table)
        self._model_group.setLayout(model_layout)
        layout.addWidget(self._model_group)

        # -- 工具统计表 --
        self._tool_group = QGroupBox("工具调用")
        tool_layout = QVBoxLayout()
        self._tool_table = QTableWidget()
        self._tool_table.setColumnCount(4)
        self._tool_table.setHorizontalHeaderLabels(["工具", "次数", "成功", "失败"])
        self._tool_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._tool_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tool_table.verticalHeader().setVisible(False)
        tool_layout.addWidget(self._tool_table)
        self._tool_group.setLayout(tool_layout)
        layout.addWidget(self._tool_group)

        # -- 按钮 --
        btn_layout = QHBoxLayout()
        reset_btn = QPushButton("重置统计")
        reset_btn.clicked.connect(self._reset)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_layout.addStretch()
        btn_layout.addWidget(reset_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self._refresh()

    # ------------------------------------------------------------------
    # 刷新 & 重置
    # ------------------------------------------------------------------

    def _refresh(self):
        """从全局可观测性实例拉取数据并更新 UI。"""
        from llm_chat.utils.observability import get_cost_summary, get_observability

        try:
            data = get_cost_summary()
        except Exception:
            return

        tokens = data["tokens"]
        cost = data["cost"]
        calls = data["calls"]
        tools = data["tools"]
        avg_ms = data.get("avg_duration_ms", 0)

        # 概览卡片
        self._lbl_tokens.setText(f"{tokens['total']:,}")
        self._lbl_cost.setText(f"${cost['total_usd']:.4f}")
        self._lbl_calls.setText(str(calls["total"]))
        self._lbl_avg_ms.setText(f"{avg_ms:.0f} ms")
        self._lbl_tools.setText(str(sum(tools.values()) if tools else 0))

        # 模型表
        models = cost["by_model"]
        self._model_table.setRowCount(len(models))
        for i, m in enumerate(models):
            self._model_table.setItem(i, 0, QTableWidgetItem(m["model"]))
            self._model_table.setItem(
                i, 1, QTableWidgetItem(f"{m['tokens']:,}")
            )
            self._model_table.setItem(
                i, 2, QTableWidgetItem(f"${m['cost_usd']:.6f}")
            )

        # 工具表
        tool_items = sorted(tools.items(), key=lambda x: -x[1])
        self._tool_table.setRowCount(len(tool_items))
        for i, (name, count) in enumerate(tool_items):
            self._tool_table.setItem(i, 0, QTableWidgetItem(name))
            self._tool_table.setItem(i, 1, QTableWidgetItem(str(count)))
            if isinstance(count, dict):
                self._tool_table.setItem(
                    i, 2, QTableWidgetItem(str(count.get("success", 0)))
                )
                self._tool_table.setItem(
                    i, 3, QTableWidgetItem(str(count.get("error", 0)))
                )
            else:
                self._tool_table.setItem(i, 2, QTableWidgetItem("—"))
                self._tool_table.setItem(i, 3, QTableWidgetItem("—"))

    def _reset(self):
        from llm_chat.utils.observability import get_observability

        get_observability().reset()
        self._refresh()

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
