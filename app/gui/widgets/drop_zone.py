"""Drag-and-drop input zone for files/folders."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class DropZone(QWidget):
    paths_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(130)
        self.setObjectName("DropZone")
        layout = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.setStyleSheet(
            "QWidget#DropZone {"
            " border: 2px dashed #888;"
            " border-radius: 8px;"
            " background: #f7f7f7;"
            "}"
            "QWidget#DropZone[active=\"true\"] {"
            " border-color: #2b6cb0;"
            " background: #ebf4ff;"
            "}"
        )
        self.set_summary(0)

    def set_summary(self, count: int) -> None:
        if count <= 0:
            self.label.setText("拖入图片 / 文件夹\n或使用下方按钮添加")
        else:
            self.label.setText(f"已选择 {count} 个路径\n可继续拖入追加")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("active", True)
            self.style().unpolish(self)
            self.style().polish(self)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.setProperty("active", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.setProperty("active", False)
        self.style().unpolish(self)
        self.style().polish(self)
        paths: list[str] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(str(Path(local)))
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()
