"""Main application window."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QTimer, Slot
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
from app.core.dependency_installer import ensure_runtime_site
from app.core.models import JobResult, ProgressEvent, ProgressKind
from app.gui.widgets.drop_zone import DropZone
from app.gui.workers.pipeline_worker import PipelineController
from app.version import __version__


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"AI Image Process  v{__version__}")
        try:
            from app.gui.icons import get_app_icon

            _icon = get_app_icon()
            if _icon is not None:
                self.setWindowIcon(_icon)
        except Exception:  # noqa: BLE001
            pass
        self.resize(880, 680)

        self._cfg_mgr = ConfigManager(user_config_dir() / "config.json")
        try:
            self._config = self._cfg_mgr.load()
        except Exception:  # noqa: BLE001
            self._config = default_config()
        # Pick up packages previously installed from within the app before
        # any lazy import of remove_ai_watermarks can happen.
        ensure_runtime_site(self._config.runtime.portable_mode)

        self._inputs: list[Path] = []
        self._last_output_dir: Path | None = None
        # 后台隐藏图片库扫描状态：避免构造时在 GUI 主线程同步完整解码
        # 整个图片库（导致窗口迟迟不显示）。扫描在 daemon 线程中进行，
        # 结果通过 QTimer 在 GUI 线程回填，避免跨线程 Signal/Slot 在窗口
        # 销毁时触发 PySide6 C++ 层面的 Aborted 崩溃。
        self._scan_thread: threading.Thread | None = None
        self._scan_timer: QTimer | None = None
        self._scan_result: tuple[int, object] | None = None  # (scan_id, result)
        self._scan_done = False
        self._scan_id = 0
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
        # Quick toggle next to the selection actions: clearing the picked
        # files/folders after every run is what most people want when
        # working through batches, but re-running the same batch after a
        # failure needs them kept - so it lives here, not in the settings.
        self.chk_clear_after = QCheckBox("处理后清空")
        self.chk_clear_after.setToolTip(
            "处理完成后自动清空已选择的文件/路径，方便直接添加下一批。\n"
            "取消勾选则保留选择，便于失败后重跑同一批。")
        btn_row.addWidget(self.btn_add_files)
        btn_row.addWidget(self.btn_add_folder)
        btn_row.addWidget(self.btn_clear)
        btn_row.addWidget(self.chk_clear_after)
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

        steps_box = QGroupBox("处理步骤（顺序见 Registry）")
        steps_layout = QVBoxLayout(steps_box)
        self.chk_provenance = QCheckBox("清理 AI Metadata / 溯源信息")
        self.chk_visible = QCheckBox("去除可见水印（AI 标记）")
        self.chk_reencode = QCheckBox("图片重编码（JPEG + sRGB）")
        self.chk_device = QCheckBox("写入设备 Metadata")
        self.chk_rename = QCheckBox("文件命名")
        self.chk_rotate = QCheckBox("图片旋转与裁剪")
        self.chk_hidden = QCheckBox("隐藏图片")
        self.chk_live = QCheckBox("生成 Apple Live Photo")
        self.chk_output = QCheckBox("输出处理结果")
        for w in (
            self.chk_provenance,
            self.chk_visible,
            self.chk_reencode,
            self.chk_device,
            self.chk_rename,
            self.chk_rotate,
            self.chk_hidden,
            self.chk_live,
            self.chk_output,
        ):
            w.setChecked(True)
            steps_layout.addWidget(w)
        # 可见水印去除需可选依赖，默认关闭；新功能默认关闭
        self.chk_visible.setChecked(False)
        self.chk_rotate.setChecked(False)
        self.chk_hidden.setChecked(False)
        self.chk_live.setChecked(False)
        # 隐藏图片库快捷行
        hidden_row = QHBoxLayout()
        self.hidden_edit = QLineEdit()
        self.hidden_edit.setPlaceholderText("隐藏图片库目录…")
        self.btn_hidden = QPushButton("浏览")
        self.btn_hidden.clicked.connect(self._choose_hidden)
        hidden_row.addWidget(self.hidden_edit, 1)
        hidden_row.addWidget(self.btn_hidden)
        steps_layout.addLayout(hidden_row)
        self.lbl_hidden_count = QLabel("可用图片：-")
        steps_layout.addWidget(self.lbl_hidden_count)
        self.lbl_runtime = QLabel()
        self.lbl_runtime.setWordWrap(True)
        self.lbl_runtime.setStyleSheet("color:#c53030;font-size:11px;")
        self.lbl_runtime.setVisible(False)
        steps_layout.addWidget(self.lbl_runtime)
        self.hidden_edit.textChanged.connect(lambda _t: self._refresh_hidden_count())
        # Enabling device EXIF / Live Photo changes which runtimes matter.
        self.chk_device.toggled.connect(lambda _t: self._refresh_runtime_warning())
        self.chk_live.toggled.connect(lambda _t: self._refresh_runtime_warning())
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
        self.btn_iphone = QPushButton("导入 iPhone…")
        self.btn_iphone.setToolTip(
            "唤起爱思助手并显示实况照片导入操作指引（不复制任何文件；"
            "在爱思助手中选择要导入的处理结果目录即可）")
        self.btn_iphone.clicked.connect(self._import_iphone)
        self.btn_settings = QPushButton("设置")
        self.btn_settings.clicked.connect(self._open_settings)
        action.addWidget(self.btn_start)
        action.addWidget(self.btn_cancel)
        action.addWidget(self.btn_iphone)
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
        self.chk_clear_after.setChecked(self._config.input.clear_after_run)
        self.chk_provenance.setChecked(self._config.steps.provenance_cleanup.enabled)
        self.chk_visible.setChecked(self._config.steps.visible_watermark.enabled)
        self.chk_reencode.setChecked(self._config.steps.reencode.enabled)
        self.chk_device.setChecked(self._config.steps.device_metadata.enabled)
        self.chk_rename.setChecked(self._config.steps.rename.enabled)
        self.chk_rotate.setChecked(self._config.steps.rotate_crop.enabled)
        self.chk_hidden.setChecked(self._config.steps.hidden_image.enabled)
        self.chk_live.setChecked(self._config.steps.live_photo.enabled)
        self.hidden_edit.setText(self._config.steps.hidden_image.library_dir or "")
        self._refresh_hidden_count()
        self._refresh_runtime_warning()
        self.chk_output.setChecked(self._config.steps.output_write.enabled)

    def _refresh_runtime_warning(self) -> None:
        """Warn about missing external runtimes before a job is started.

        Without this the only signal was a silently skipped device-EXIF step
        or a per-file Live Photo failure naming an identifier the user has
        never heard of.
        """
        from app.core.runtime_tools import runtime_summary

        # Availability only: probing versions spawns subprocesses (a perl
        # ExifTool start-up is ~200ms), and this runs while toggling checkboxes.
        tools = runtime_summary()
        missing = []
        if self.chk_device.isChecked() and not tools["exiftool"].available:
            missing.append("ExifTool（写入设备 Metadata）")
        if self.chk_live.isChecked() and not tools["ffmpeg"].available:
            missing.append("FFmpeg（Live Photo）")
        if missing:
            self.lbl_runtime.setText("⚠ 缺少运行时：" + "、".join(missing)
                                     + "；相关功能无法正常工作，请查看「设置 → 处理 → 外部运行时」。")
            self.lbl_runtime.setVisible(True)
        else:
            self.lbl_runtime.setVisible(False)

    def _ui_to_config(self) -> AppConfig:
        cfg = self._config
        cfg.output.directory = self.out_edit.text().strip()
        cfg.output.auto_create_directory = self.chk_auto_create.isChecked()
        cfg.output.preserve_originals = self.chk_preserve.isChecked()
        cfg.input.clear_after_run = self.chk_clear_after.isChecked()
        cfg.steps.provenance_cleanup.enabled = self.chk_provenance.isChecked()
        cfg.steps.visible_watermark.enabled = self.chk_visible.isChecked()
        cfg.steps.reencode.enabled = self.chk_reencode.isChecked()
        cfg.steps.device_metadata.enabled = self.chk_device.isChecked()
        cfg.steps.rename.enabled = self.chk_rename.isChecked()
        cfg.steps.rotate_crop.enabled = self.chk_rotate.isChecked()
        cfg.steps.hidden_image.enabled = self.chk_hidden.isChecked()
        cfg.steps.hidden_image.library_dir = self.hidden_edit.text().strip()
        cfg.steps.live_photo.enabled = self.chk_live.isChecked()
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

    def _clear_inputs_after_run(self) -> None:
        """Drop the selection once a run is over (if the toggle is on).

        Only called for runs that actually processed something: a refused
        preflight or a cancelled job leaves the selection alone, because the
        user is most likely to want to fix and re-run exactly that batch.
        """
        if not self.chk_clear_after.isChecked():
            return
        if not self._inputs:
            return
        count = len(self._inputs)
        self._inputs.clear()
        self.drop_zone.set_summary(0)
        self._append_log(f"已自动清空输入（{count} 个路径）")

    @Slot()
    def _choose_hidden(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择隐藏图片库")
        if folder:
            self.hidden_edit.setText(folder)
            self._refresh_hidden_count()

    def _refresh_hidden_count(self) -> None:
        """异步刷新隐藏图片库可用张数，不阻塞 GUI 主线程。

        完整解码每张图很重：库文件多时同步扫描会把 MainWindow 构造
        卡在主线程，导致双击打开后窗口迟迟不显示。因此扫描放在
        后台 daemon 线程，结果通过 QTimer 在 GUI 线程回填，完全避免
        跨线程 Signal/Slot 在窗口销毁时触发 PySide6 C++ 层面的崩溃。
        """
        lib = self.hidden_edit.text().strip()
        if not lib:
            self._cancel_scanner()
            self.lbl_hidden_count.setText("可用图片：-")
            self.lbl_hidden_count.setToolTip("")
            return
        exts = {e.lower().lstrip(".") for e in (self._config.input.extensions or ["jpg", "jpeg", "png", "webp"])}
        self.lbl_hidden_count.setText("可用图片：扫描中…")
        self.lbl_hidden_count.setToolTip("")
        # 已有扫描在进行时，textChanged 等高频触发不再重复提交任务。
        if self._scan_thread is not None and self._scan_thread.is_alive():
            return
        self._start_scanner(Path(lib), exts)

    def _start_scanner(self, library_dir: Path, exts: set[str]) -> None:
        """在后台 daemon 线程启动一次隐藏图片库扫描。

        扫描本身不碰任何 Qt 对象；完成后把 (scan_id, result) 存在实例
        属性上，由 _on_scan_timer 在 GUI 线程读取并回填到 UI。
        """
        self._cancel_scanner()
        self._scan_id += 1
        scan_id = self._scan_id
        self._scan_result = None
        self._scan_done = False

        def _run() -> None:
            from app.core.hidden_images import scan_hidden_library_detailed

            try:
                result = scan_hidden_library_detailed(library_dir, exts)
            except Exception:  # noqa: BLE001 - 扫描失败不应崩溃启动
                result = None
            self._scan_result = (scan_id, result)
            self._scan_done = True

        thread = threading.Thread(target=_run, daemon=True)
        self._scan_thread = thread
        thread.start()

        # 用 QTimer 在 GUI 线程轮询扫描结果：QTimer 以 self 为 parent，
        # 窗口销毁时定时器自动销毁，不会再触发回调，彻底规避跨线程
        # Signal/Slot 在窗口销毁时导致的 Aborted 崩溃。
        timer = QTimer(self)
        timer.setSingleShot(False)
        timer.timeout.connect(self._on_scan_timer)
        timer.start(100)
        self._scan_timer = timer

    @Slot()
    def _on_scan_timer(self) -> None:
        """GUI 线程回调：轮询后台扫描结果，完成后回填到 UI。

        QTimer 以 self 为 parent，窗口已销毁时定时器随之销毁，此槽
        不会再被调用；其余防护条件再次确认不过期、未取消。
        """
        if not self._scan_done:
            # 还未完成，继续轮询
            return
        scan_id, result = self._scan_result or (self._scan_id, None)
        # 过期结果（已切换库目录或已取消）直接丢弃
        if scan_id != self._scan_id:
            self._cancel_scanner()
            return
        self._cancel_scanner()
        if result is None or not isinstance(result, list):
            self.lbl_hidden_count.setText("可用图片：读取失败")
            self.lbl_hidden_count.setToolTip("")
            return
        usable = [e for e in result if e.usable]
        skipped = [e for e in result if not e.usable]
        if skipped:
            self.lbl_hidden_count.setText(
                f"可用图片：{len(usable)} 张（另有 {len(skipped)} 个不可用文件已过滤，悬停查看）")
            self.lbl_hidden_count.setToolTip(
                "已过滤：\n" + "\n".join(f"{e.path.name}：{e.reason}" for e in skipped[:20]))
        else:
            self.lbl_hidden_count.setText(f"可用图片：{len(usable)} 张")
            self.lbl_hidden_count.setToolTip("")

    def _cancel_scanner(self) -> None:
        """停止正在进行的后台扫描，并清理定时器与线程引用。

        扫描线程为 daemon，主进程退出时会随之结束；这里不 terminate
        （不安全），只是断开定时器信号、停止定时器并放弃引用，
        避免窗口销毁后已排队的 timeout 回调访问已销毁的 C++ 对象
        导致 PySide6 teardown 崩溃。
        """
        if self._scan_timer is not None:
            try:
                self._scan_timer.timeout.disconnect(self._on_scan_timer)
            except TypeError:  # 连接可能已不存在
                pass
            self._scan_timer.stop()
            self._scan_timer = None
        self._scan_thread = None

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

    @Slot()
    def _import_iphone(self) -> None:
        """iPhone import: wake 爱思助手 and show the click-by-click steps.

        Deliberately does nothing to the filesystem. A session may process
        several batches and the user still has to pick the folder inside
        爱思助手, so scanning, copying or staging files here would only
        duplicate bytes the user was going to select by hand anyway. The
        output paths below are shown as text; they are never opened.
        """
        from app.core.iphone_import.i4tools import I4ToolsImporter

        imp = I4ToolsImporter()
        hint = self._iphone_folder_hint()
        res = imp.guidance(folder_hint=hint)
        launch = str((res.extra or {}).get("launch_detail") or "")
        self._append_log("[iPhone] 已显示爱思助手实况导入指引"
                         + (f"，{launch}" if launch else "") + "（未复制任何文件）")
        box = QMessageBox(self)
        box.setWindowTitle("导入 iPhone")
        box.setText("本工具不会复制或修改任何文件。\n"
                    "请在爱思助手中选择要导入的处理结果目录，完成实况照片导入。")
        box.setInformativeText(res.message)
        box.setDetailedText(
            (f"参考目录：{hint}\n" if hint else "")
            + f"后端：{imp.name}\n" + res.message)
        box.exec()

    def _iphone_folder_hint(self) -> str | None:
        """Text to show as "where the results are", without touching the disk.

        The last finished run's folder is the most precise thing the window
        already knows; otherwise fall back to the configured output root.
        """
        if self._last_output_dir is not None:
            return str(self._last_output_dir)
        return self.out_edit.text().strip() or None

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
        # Tell the user where the run actually landed: with a per-run
        # timestamped folder the effective directory differs from the one
        # they picked, and finding it by hand is the first thing people do.
        out_dir = None
        for f in result.success:
            p = getattr(f, "output_path", None)
            if p is not None:
                out_dir = Path(p).parent
                break
        if out_dir is not None:
            self._last_output_dir = out_dir
            self._append_log(f"[输出] 本次结果目录：{out_dir}")
        # Deliberately NOT written back into out_edit: that field is the input
        # for the *next* run, and filling it with this run's timestamped folder
        # would make every subsequent run nest one level deeper.
        if getattr(result, "preflight_failed", False):
            text = f"预检未通过，任务未开始。\n\n{result.preflight_error or ''}"
            self.lbl_status.setText("预检未通过")
            self._append_log(text)
            QMessageBox.warning(self, "预检未通过", text)
            return
        if result.cancelled:
            text = f"已取消。成功 {result.success_count}，失败 {result.failure_count}"
            self.lbl_status.setText(text)
            self._append_log(text)
            return
        # The run really finished (files may have failed individually - that
        # is still "处理完"), so the selection can go.
        self._clear_inputs_after_run()
        self.progress.setValue(100)
        text = f"完成。成功 {result.success_count}，失败 {result.failure_count}"
        if out_dir is not None:
            # Surface the real destination: with the per-run folder on it is
            # not simply the directory the user typed.
            text += f"\n结果目录：{out_dir}"
        self.lbl_status.setText(text)
        self._append_log(text)
        where = f"\n\n结果目录：{out_dir}" if out_dir is not None else ""
        if result.failed:
            details = "\n".join(f"- {r.source_path.name}: {r.error}" for r in result.failed[:20])
            QMessageBox.warning(
                self,
                "处理完成（有失败）",
                f"成功 {result.success_count}，失败 {result.failure_count}{where}\n\n{details}",
            )
        else:
            QMessageBox.information(
                self, "处理完成", f"全部成功：{result.success_count} 张{where}")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.lbl_status.setText("任务异常")
        self._append_log(message)
        QMessageBox.critical(self, "任务失败", message)

    @Slot(bool)
    def _on_busy(self, busy: bool) -> None:
        self.btn_start.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)
        self.btn_iphone.setEnabled(not busy)
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
        self._cancel_scanner()
        try:
            self._cfg_mgr.save(self._ui_to_config())
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)
