"""Main application window."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config.manager import ConfigManager
from app.config.paths import user_config_dir
from app.config.schema import AppConfig, default_config
from app.core.models import JobResult, ProgressEvent, ProgressKind
from app.gui.widgets.drop_zone import DropZone
from app.gui.workers.pipeline_worker import PipelineController
from app.version import __version__


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"AI Image Process  v{__version__}")
        self.resize(880, 680)

        self._cfg_mgr = ConfigManager(user_config_dir() / "config.json")
        try:
            self._config = self._cfg_mgr.load()
        except Exception:  # noqa: BLE001
            self._config = default_config()

        self._inputs: list[Path] = []
        self._controller = PipelineController(self)
        self._controller.progress.connect(self._on_progress)
        self._controller.finished.connect(self._on_finished)
        self._controller.failed.connect(self._on_failed)
        self._controller.busy_changed.connect(self._on_busy)

        self._build_ui()
        self._build_menu()
        self._apply_config_to_ui()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        title = QLabel("AI Image Process")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(title)

        self.drop_zone = DropZone()
        self.drop_zone.paths_dropped.connect(self._on_paths_dropped)
        root.addWidget(self.drop_zone)

        btn_row = QHBoxLayout()
        self.btn_add_files = QPushButton("添加图片")
        self.btn_add_files.clicked.connect(self._add_files)
        self.btn_add_folder = QPushButton("添加文件夹")
        self.btn_add_folder.clicked.connect(self._add_folder)
        self.btn_clear = QPushButton("清空")
        self.btn_clear.clicked.connect(self._clear_inputs)
        btn_row.addWidget(self.btn_add_files)
        btn_row.addWidget(self.btn_add_folder)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        out_box = QGroupBox("输出")
        out_layout = QVBoxLayout(out_box)
        out_row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("选择输出目录…")
        self.btn_out = QPushButton("选择")
        self.btn_out.clicked.connect(self._choose_output)
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(self.btn_out)
        out_layout.addLayout(out_row)
        self.chk_auto_create = QCheckBox("自动创建输出目录")
        self.chk_preserve = QCheckBox("保留原始图片（推荐）")
        out_layout.addWidget(self.chk_auto_create)
        out_layout.addWidget(self.chk_preserve)
        root.addWidget(out_box)

        steps_box = QGroupBox("处理步骤")
        steps_layout = QVBoxLayout(steps_box)
        self.chk_provenance = QCheckBox("清理 AI Metadata / 溯源信息")
        self.chk_reencode = QCheckBox("图片重编码（JPEG + sRGB）")
        self.chk_device = QCheckBox("写入设备 Metadata")
        self.chk_rename = QCheckBox("文件命名")
        self.chk_output = QCheckBox("输出处理后的图片")
        for w in (
            self.chk_provenance,
            self.chk_reencode,
            self.chk_device,
            self.chk_rename,
            self.chk_output,
        ):
            w.setChecked(True)
            steps_layout.addWidget(w)
        root.addWidget(steps_box)

        action = QHBoxLayout()
        self.btn_start = QPushButton("开始处理")
        self.btn_start.setStyleSheet(
            "QPushButton { background:#2b6cb0; color:white; font-weight:600; padding:10px 16px; }"
        )
        self.btn_start.clicked.connect(self._start)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_settings = QPushButton("设置")
        self.btn_settings.clicked.connect(self._open_settings)
        action.addWidget(self.btn_start)
        action.addWidget(self.btn_cancel)
        action.addStretch(1)
        action.addWidget(self.btn_settings)
        root.addLayout(action)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.lbl_status = QLabel("就绪")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.log.setPlaceholderText("处理日志…")
        root.addWidget(self.log, 1)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        help_menu = self.menuBar().addMenu("帮助")
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._about)
        help_menu.addAction(act_about)

    def _apply_config_to_ui(self) -> None:
        self.out_edit.setText(self._config.output.directory)
        self.chk_auto_create.setChecked(self._config.output.auto_create_directory)
        self.chk_preserve.setChecked(self._config.output.preserve_originals)
        self.chk_provenance.setChecked(self._config.steps.provenance_cleanup.enabled)
        self.chk_reencode.setChecked(self._config.steps.reencode.enabled)
        self.chk_device.setChecked(self._config.steps.device_metadata.enabled)
        self.chk_rename.setChecked(self._config.steps.rename.enabled)
        self.chk_output.setChecked(self._config.steps.output_write.enabled)

    def _ui_to_config(self) -> AppConfig:
        cfg = self._config
        cfg.output.directory = self.out_edit.text().strip()
        cfg.output.auto_create_directory = self.chk_auto_create.isChecked()
        cfg.output.preserve_originals = self.chk_preserve.isChecked()
        cfg.steps.provenance_cleanup.enabled = self.chk_provenance.isChecked()
        cfg.steps.reencode.enabled = self.chk_reencode.isChecked()
        cfg.steps.device_metadata.enabled = self.chk_device.isChecked()
        cfg.steps.rename.enabled = self.chk_rename.isChecked()
        cfg.steps.output_write.enabled = self.chk_output.isChecked()
        return cfg

    def _append_log(self, text: str) -> None:
        self.log.appendPlainText(text)

    @Slot()
    def _on_paths_dropped(self, paths: list) -> None:
        added = 0
        for raw in paths:
            path = Path(str(raw))
            if path not in self._inputs:
                self._inputs.append(path)
                added += 1
        self.drop_zone.set_summary(len(self._inputs))
        self._append_log(f"新增 {added} 个路径，当前共 {len(self._inputs)} 个")

    @Slot()
    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择图片",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp);;All (*.*)",
        )
        if files:
            self._on_paths_dropped(files)

    @Slot()
    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            self._on_paths_dropped([folder])

    @Slot()
    def _clear_inputs(self) -> None:
        self._inputs.clear()
        self.drop_zone.set_summary(0)
        self._append_log("已清空输入")

    @Slot()
    def _choose_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if folder:
            self.out_edit.setText(folder)

    @Slot()
    def _start(self) -> None:
        if self._controller.is_busy:
            return
        if not self._inputs:
            QMessageBox.warning(self, "提示", "请先添加图片或文件夹。")
            return
        cfg = self._ui_to_config()
        out = cfg.output.directory.strip()
        if not out:
            QMessageBox.warning(self, "提示", "请选择输出目录。")
            return
        try:
            self._cfg_mgr.save(cfg)
        except Exception:  # noqa: BLE001
            pass
        self.log.clear()
        self._append_log("开始处理…")
        self.progress.setValue(0)
        self.lbl_status.setText("处理中…")
        try:
            self._controller.start(cfg, list(self._inputs), Path(out))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "无法开始", str(exc))

    @Slot()
    def _cancel(self) -> None:
        self._controller.cancel()
        self._append_log("已请求取消（将在当前文件完成后停止）…")

    @Slot(object)
    def _on_progress(self, ev: object) -> None:
        if not isinstance(ev, ProgressEvent):
            return
        if ev.total > 0:
            self.progress.setValue(max(0, min(100, int(ev.index * 100 / ev.total))))
        msg = ev.message or ev.kind.value
        if ev.file_path is not None:
            name = getattr(ev.file_path, "name", str(ev.file_path))
            msg = f"{name}: {msg}"
        status = f"{msg}  |  成功 {ev.success_count}  失败 {ev.failure_count}  ({ev.index}/{ev.total})"
        self.lbl_status.setText(status)
        if ev.kind in {
            ProgressKind.LOG,
            ProgressKind.FILE_STARTED,
            ProgressKind.FILE_FAILED,
            ProgressKind.FILE_SUCCEEDED,
            ProgressKind.JOB_FINISHED,
            ProgressKind.JOB_CANCELLED,
        }:
            self._append_log(status)

    @Slot(object)
    def _on_finished(self, result: object) -> None:
        if not isinstance(result, JobResult):
            return
        if result.cancelled:
            text = f"已取消。成功 {result.success_count}，失败 {result.failure_count}"
            self.lbl_status.setText(text)
            self._append_log(text)
            return
        self.progress.setValue(100)
        text = f"完成。成功 {result.success_count}，失败 {result.failure_count}"
        self.lbl_status.setText(text)
        self._append_log(text)
        if result.failed:
            details = "\n".join(f"- {r.source_path.name}: {r.error}" for r in result.failed[:20])
            QMessageBox.warning(
                self,
                "处理完成（有失败）",
                f"成功 {result.success_count}，失败 {result.failure_count}\n\n{details}",
            )
        else:
            QMessageBox.information(self, "处理完成", f"全部成功：{result.success_count} 张")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.lbl_status.setText("任务异常")
        self._append_log(message)
        QMessageBox.critical(self, "任务失败", message)

    @Slot(bool)
    def _on_busy(self, busy: bool) -> None:
        self.btn_start.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)
        self.btn_add_files.setEnabled(not busy)
        self.btn_add_folder.setEnabled(not busy)
        self.btn_clear.setEnabled(not busy)
        self.btn_out.setEnabled(not busy)
        self.btn_settings.setEnabled(not busy)

    @Slot()
    def _open_settings(self) -> None:
        from app.gui.settings_dialog import SettingsDialog

        dlg = SettingsDialog(self._config, self)
        if dlg.exec():
            self._config = dlg.config()
            self._apply_config_to_ui()
            try:
                self._cfg_mgr.save(self._config)
            except Exception:  # noqa: BLE001
                pass

    @Slot()
    def _about(self) -> None:
        QMessageBox.about(
            self,
            "关于",
            f"AI Image Process\nVersion {__version__}\n\n"
            "跨平台 AI 图片处理客户端\n"
            "GitHub: mufeng510/ai-image-process",
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._controller.is_busy:
            QMessageBox.warning(self, "提示", "任务仍在运行，请先取消。")
            event.ignore()
            return
        try:
            self._cfg_mgr.save(self._ui_to_config())
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)
