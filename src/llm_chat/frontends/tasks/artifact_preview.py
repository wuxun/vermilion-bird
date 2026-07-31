"""In-app Artifact preview and immutable version comparison."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Optional

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QFontDatabase
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from llm_chat.frontends.theme import Colors


class ArtifactPreviewDialog(QDialog):
    """Preview an Artifact locally and compare it with its previous version."""

    def __init__(self, app: Any, artifact: Any, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._app = app
        self._initial_artifact = artifact
        self._versions = self._load_versions(artifact)
        self._versions_by_id = {version.id: version for version in self._versions}

        self.setWindowTitle(f"交付物 · {artifact.name}")
        self.resize(840, 650)
        self.setMinimumSize(620, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        heading = QLabel(artifact.name)
        heading.setStyleSheet("font-size: 17px; font-weight: 700;")
        root.addWidget(heading)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("版本"))
        self.version_combo = QComboBox()
        for version in self._versions:
            relation = getattr(version.relation, "value", str(version.relation))
            self.version_combo.addItem(f"v{version.version} · {relation}", version.id)
        controls.addWidget(self.version_combo)
        controls.addStretch(1)
        self.open_source_button = QPushButton("打开原文件")
        self.open_source_button.clicked.connect(self._open_source)
        controls.addWidget(self.open_source_button)
        root.addLayout(controls)

        self.metadata_label = QLabel()
        self.metadata_label.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        self.metadata_label.setWordWrap(True)
        root.addWidget(self.metadata_label)

        self.tabs = QTabWidget()
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.diff = QTextBrowser()
        self.diff.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.tabs.addTab(self.preview, "预览")
        self.tabs.addTab(self.diff, "与上一版本对比")
        root.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.version_combo.currentIndexChanged.connect(self._refresh)
        initial_index = next(
            (
                index
                for index, version in enumerate(self._versions)
                if version.id == artifact.id
            ),
            0,
        )
        self.version_combo.setCurrentIndex(initial_index)
        self._refresh()

    def _load_versions(self, artifact: Any) -> List[Any]:
        loader = getattr(self._app, "list_artifact_versions", None)
        if callable(loader):
            try:
                versions = list(loader(artifact.id))
                if versions:
                    return sorted(
                        versions,
                        key=lambda item: (item.version, item.created_at),
                        reverse=True,
                    )
            except Exception:
                pass
        return [artifact]

    def _selected_artifact(self):
        return self._versions_by_id.get(self.version_combo.currentData())

    def _refresh(self) -> None:
        artifact = self._selected_artifact()
        if artifact is None:
            return
        preview_loader = getattr(self._app, "preview_artifact", None)
        try:
            value = (
                preview_loader(artifact.id)
                if callable(preview_loader)
                else SimpleNamespace(
                    content=artifact.content
                    or artifact.content_preview
                    or "该交付物没有可预览内容。",
                    source="embedded",
                    truncated=False,
                )
            )
            self.preview.setPlainText(value.content)
            checksum = f" · SHA-256 {artifact.checksum[:12]}…" if artifact.checksum else ""
            truncated = " · 已截断" if value.truncated else ""
            self.metadata_label.setText(
                f"v{artifact.version} · {artifact.kind.value} · {value.source}"
                f"{checksum}{truncated}"
            )
        except Exception as exc:
            self.preview.setPlainText(f"预览失败：{exc}")
            self.metadata_label.setText(f"v{artifact.version}")

        self.open_source_button.setVisible(bool(artifact.uri))
        previous = next(
            (
                candidate
                for candidate in self._versions
                if candidate.version < artifact.version
            ),
            None,
        )
        if previous is None:
            self.diff.setPlainText("这是该交付物的初始版本。")
            self.tabs.setTabEnabled(1, False)
            return
        self.tabs.setTabEnabled(1, True)
        diff_loader = getattr(self._app, "diff_artifact_versions", None)
        if not callable(diff_loader):
            self.diff.setPlainText("当前应用实例不支持版本对比。")
            return
        try:
            value = diff_loader(previous.id, artifact.id)
            self.diff.setPlainText(value.content)
        except Exception as exc:
            self.diff.setPlainText(f"版本对比失败：{exc}")

    def _open_source(self) -> None:
        artifact = self._selected_artifact()
        if artifact is None or not artifact.uri:
            return
        url = (
            QUrl(artifact.uri)
            if artifact.uri.startswith(("http://", "https://"))
            else QUrl.fromLocalFile(artifact.uri)
        )
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(self, "无法打开", "系统无法打开该交付物来源。")
