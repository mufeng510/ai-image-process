"""Full settings dialog: General / Processing / Advanced / About."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.config.manager import ConfigManager
from app.config.paths import phones_json_path, user_config_dir
from app.config.schema import AppConfig, default_config
from app.core import dependency_installer, visible_models
from app.core.device_library import DeviceLibrary
from app.gui.naming_presets import NAMING_PRESETS, template_for_preset
from app.version import __version__

GITHUB_URL = "https://github.com/mufeng510/ai-image-process"


class ModelDownloadWorker(QObject):
    """Runs a user-initiated model download off the UI thread."""

    ok = Signal(str, str)  # backend, message
    failed = Signal(str, str)  # backend, error

    def __init__(self, backend: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._backend = backend

    @Slot()
    def run(self) -> None:
        try:
            visible_models.download_model(self._backend)
            self.ok.emit(self._backend, f"{self._backend} 模型下载完成")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self._backend, str(exc))


class PipInstallWorker(QObject):
    """Runs an in-app pip install of a feature dependency off the UI thread."""

    progress = Signal(str)  # one pip log line
    ok = Signal(str)  # feature
    failed = Signal(str, str)  # feature, error

    def __init__(
        self, feature: str, portable_mode: bool = False, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._feature = feature
        self._portable = portable_mode

    @Slot()
    def run(self) -> None:
        try:
            dependency_installer.install_feature(
                self._feature, log=self.progress.emit, portable_mode=self._portable
            )
            self.ok.emit(self._feature)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self._feature, str(exc))


class SettingsDialog(QDialog):
    """Edit AppConfig with full tabs and import/export/reset."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self._config = deepcopy(config)
        self._devices: list[tuple[str, str]] = []  # (id, label)
        self._dl_thread: QThread | None = None
        self._dl_worker: ModelDownloadWorker | None = None
        self._ins_thread: QThread | None = None
        self._ins_worker: PipInstallWorker | None = None
        self._ins_feature: str = ""
        self._ins_log: list[str] = []
        self._ins_error: str = ""
        self._load_devices()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self.tabs.addTab(self._build_general_tab(), "常规")
        self.tabs.addTab(self._build_processing_tab(), "处理")
        self.tabs.addTab(self._build_advanced_tab(), "高级")
        self.tabs.addTab(self._build_about_tab(), "关于")

        self._apply_config_to_ui(self._config)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._fit_to_screen()

    # ----- data helpers -----
    def _load_devices(self) -> None:
        self._devices = []
        path = phones_json_path()
        if not path.exists():
            return
        try:
            lib = DeviceLibrary.load(path)
            for d in lib.devices:
                self._devices.append((d.id, f"{d.make} {d.model}"))
        except Exception:  # noqa: BLE001
            self._devices = []

    def config(self) -> AppConfig:
        return self._config

    def _fit_to_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geometry = screen.geometry()
            max_w = int(geometry.width() * 0.85)
            max_h = int(geometry.height() * 0.85)
        else:  # no screen (offscreen tests); keep sane defaults
            max_w, max_h = 620, 560
        self.resize(min(620, max_w), min(560, max_h))
        self.setMaximumSize(max_w, max_h)

    def _make_scrollable(self, widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        return scroll

    # ----- tabs -----
    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        out_box = QGroupBox("输出")
        form = QFormLayout(out_box)
        self.out_dir = QLineEdit()
        browse_out = QPushButton("浏览…")
        browse_out.clicked.connect(self._browse_output)
        row = QHBoxLayout()
        row.addWidget(self.out_dir, 1)
        row.addWidget(browse_out)
        form.addRow("默认输出目录", row)
        self.chk_auto_create = QCheckBox("自动创建不存在的输出目录")
        form.addRow(self.chk_auto_create)
        self.chk_preserve = QCheckBox("保留原始图片（不覆盖原文件）")
        form.addRow(self.chk_preserve)
        self.chk_use_source = QCheckBox("默认输出到原图所在目录")
        form.addRow(self.chk_use_source)
        layout.addWidget(out_box)

        name_box = QGroupBox("文件命名")
        nform = QFormLayout(name_box)
        self.preset = QComboBox()
        for key, label, _tmpl in NAMING_PRESETS:
            self.preset.addItem(label, key)
        self.preset.currentIndexChanged.connect(self._on_preset_changed)
        nform.addRow("命名预设", self.preset)
        self.template = QLineEdit()
        self.template.setPlaceholderText("{original_name}_{date}_{time}")
        nform.addRow("自定义模板", self.template)
        help_lbl = QLabel(
            "可用变量：{original_name} {original_ext} {date} {time} {datetime} "
            "{number} {year} {month} {day} {hour} {minute} {second}"
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("color: #555; font-size: 11px;")
        nform.addRow(help_lbl)
        self.number_start = QSpinBox()
        self.number_start.setRange(0, 999999)
        self.number_width = QSpinBox()
        self.number_width.setRange(1, 8)
        nform.addRow("序号起始", self.number_start)
        nform.addRow("序号位数", self.number_width)
        layout.addWidget(name_box)

        conflict_box = QGroupBox("文件冲突")
        cform = QFormLayout(conflict_box)
        self.conflict = QComboBox()
        self.conflict.addItem("自动重命名（推荐）", "rename")
        self.conflict.addItem("自动跳过", "skip")
        self.conflict.addItem("自动覆盖", "overwrite")
        cform.addRow("文件已存在时", self.conflict)
        layout.addWidget(conflict_box)

        clean_box = QGroupBox("清理")
        cl = QVBoxLayout(clean_box)
        self.chk_cleanup_success = QCheckBox("处理成功后自动清理临时文件")
        self.chk_cleanup_startup = QCheckBox("启动时清理异常退出残留临时文件")
        cl.addWidget(self.chk_cleanup_success)
        cl.addWidget(self.chk_cleanup_startup)
        layout.addWidget(clean_box)

        layout.addStretch(1)
        return self._make_scrollable(page)

    def _build_processing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        # Deduplication
        dedup = QGroupBox("文件去重")
        dpf = QFormLayout(dedup)
        self.chk_dedup = QCheckBox("启用此步骤")
        dpf.addRow(self.chk_dedup)
        self.dedup_algorithm = QComboBox()
        self.dedup_algorithm.addItem("MD5（推荐，速度快）", "md5")
        self.dedup_algorithm.addItem("SHA-1", "sha1")
        self.dedup_algorithm.addItem("SHA-256（最安全，较慢）", "sha256")
        dpf.addRow("哈希算法", self.dedup_algorithm)
        dedup_note = QLabel("通过文件内容哈希去重，重复文件仅保留第一张。")
        dedup_note.setWordWrap(True)
        dedup_note.setStyleSheet("color:#666;font-size:11px;")
        dpf.addRow(dedup_note)
        layout.addWidget(dedup)

        # Provenance
        prov = QGroupBox("清理 AI Metadata")
        pf = QFormLayout(prov)
        self.chk_prov = QCheckBox("启用此步骤")
        pf.addRow(self.chk_prov)
        self.prov_mode = QComboBox()
        self.prov_mode.addItem("metadata（推荐，轻量）", "metadata")
        pf.addRow("模式", self.prov_mode)
        note = QLabel("需要安装 remove-ai-watermarks 时才会实际清理；否则自动降级为复制原图。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#666;font-size:11px;")
        pf.addRow(note)
        self.prov_status = QLabel()
        self.prov_status.setWordWrap(True)
        self.prov_status.setStyleSheet("color:#666;font-size:11px;")
        pf.addRow("状态", self.prov_status)
        prov_dep_row = QHBoxLayout()
        self.btn_install_prov = QPushButton("安装依赖")
        self.btn_install_prov.setToolTip(
            f'在线安装 {dependency_installer.FEATURE_SPECS["provenance"]}（本功能所需）'
        )
        self.btn_install_prov.clicked.connect(lambda: self._install_dependency("provenance"))
        prov_dep_row.addWidget(self.btn_install_prov)
        prov_dep_row.addStretch(1)
        pf.addRow("依赖安装", prov_dep_row)
        layout.addWidget(prov)

        # Visible watermark removal
        vis = QGroupBox("去除可见水印（AI 标记，如 Gemini/豆包/即梦角标）")
        vf = QFormLayout(vis)
        self.chk_visible = QCheckBox("启用此步骤")
        vf.addRow(self.chk_visible)
        self.visible_backend = QComboBox()
        self.visible_backend.addItem("auto（自动选择最佳可用后端）", "auto")
        self.visible_backend.addItem("cv2（OpenCV 修复，无需模型）", "cv2")
        self.visible_backend.addItem("migan（MI-GAN，约 28 MB 模型）", "migan")
        self.visible_backend.addItem("lama（big-LaMa，质量优先，体积较大）", "lama")
        vf.addRow("填充后端", self.visible_backend)
        self.visible_status = QLabel()
        self.visible_status.setWordWrap(True)
        self.visible_status.setStyleSheet("color:#666;font-size:11px;")
        vf.addRow("状态", self.visible_status)
        dl_row = QHBoxLayout()
        self.btn_dl_migan = QPushButton("下载 migan 模型")
        self.btn_dl_lama = QPushButton("下载 lama 模型")
        self.btn_dl_migan.clicked.connect(lambda: self._download_visible_model("migan"))
        self.btn_dl_lama.clicked.connect(lambda: self._download_visible_model("lama"))
        dl_row.addWidget(self.btn_dl_migan)
        dl_row.addWidget(self.btn_dl_lama)
        dl_row.addStretch(1)
        vf.addRow("模型下载", dl_row)
        vis_dep_row = QHBoxLayout()
        self.btn_install_visible = QPushButton("安装依赖")
        self.btn_install_visible.setToolTip(
            f'在线安装 {dependency_installer.FEATURE_SPECS["visible"]}（本功能所需，含 cv2 后端）'
        )
        self.btn_install_visible.clicked.connect(lambda: self._install_dependency("visible"))
        self.btn_install_onnx = QPushButton("安装 migan/lama 支持")
        self.btn_install_onnx.setToolTip(
            f'在线安装 {dependency_installer.FEATURE_SPECS["onnxruntime"]}'
            "（migan/lama 填充后端所需：onnxruntime + 模型下载支持）"
        )
        self.btn_install_onnx.clicked.connect(lambda: self._install_dependency("onnxruntime"))
        vis_dep_row.addWidget(self.btn_install_visible)
        vis_dep_row.addWidget(self.btn_install_onnx)
        vis_dep_row.addStretch(1)
        vf.addRow("依赖安装", vis_dep_row)
        vis_note = QLabel(
            "软件不预置任何模型；默认 cv2 后端无需模型即可工作。"
            "本功能依赖 remove-ai-watermarks，可点击上方“安装依赖”在线安装；"
            "migan/lama 为可选的神经网络修复后端，需先安装 onnxruntime 再下载模型，"
            "模型缓存于本机（Hugging Face 缓存目录），首次使用也会自动下载。"
        )
        vis_note.setWordWrap(True)
        vis_note.setStyleSheet("color:#666;font-size:11px;")
        vf.addRow(vis_note)
        layout.addWidget(vis)

        # Reencode
        reenc = QGroupBox("图片重编码")
        rf = QFormLayout(reenc)
        self.chk_reenc = QCheckBox("启用此步骤")
        rf.addRow(self.chk_reenc)
        self.qmin = QSpinBox()
        self.qmin.setRange(1, 100)
        self.qmax = QSpinBox()
        self.qmax.setRange(1, 100)
        rf.addRow("JPEG 质量最小值", self.qmin)
        rf.addRow("JPEG 质量最大值", self.qmax)
        self.chk_icc = QCheckBox("嵌入 sRGB ICC 配置")
        rf.addRow(self.chk_icc)
        layout.addWidget(reenc)

        # Device metadata
        dev = QGroupBox("写入设备 Metadata")
        df = QFormLayout(dev)
        self.chk_device = QCheckBox("启用此步骤")
        df.addRow(self.chk_device)
        self.device_selection = QComboBox()
        self.device_selection.addItem("随机设备", "random")
        self.device_selection.addItem("固定设备", "fixed")
        self.device_selection.currentIndexChanged.connect(self._on_device_selection_changed)
        df.addRow("设备选择", self.device_selection)
        self.device_fixed = QComboBox()
        self.device_fixed.addItem("（未加载设备库）", "")
        for did, label in self._devices:
            self.device_fixed.addItem(label, did)
        df.addRow("固定设备", self.device_fixed)
        self.chk_rand_time = QCheckBox("随机化拍摄时间")
        df.addRow(self.chk_rand_time)
        self.offset_min = QSpinBox()
        self.offset_min.setRange(0, 100000)
        self.offset_max = QSpinBox()
        self.offset_max.setRange(1, 200000)
        df.addRow("时间偏移最小（分钟）", self.offset_min)
        df.addRow("时间偏移最大（分钟）", self.offset_max)
        self.software = QLineEdit()
        df.addRow("Software 标签", self.software)
        layout.addWidget(dev)

        # Rename / output simple enables
        other = QGroupBox("其他步骤")
        of = QVBoxLayout(other)
        self.chk_rename = QCheckBox("启用文件命名")
        self.chk_output_write = QCheckBox("启用输出写入")
        of.addWidget(self.chk_rename)
        of.addWidget(self.chk_output_write)
        layout.addWidget(other)

        # Input options
        inp = QGroupBox("输入")
        inf = QFormLayout(inp)
        self.chk_recurse = QCheckBox("递归扫描子文件夹")
        inf.addRow(self.chk_recurse)
        self.extensions = QLineEdit()
        self.extensions.setPlaceholderText("jpg,jpeg,png,webp,tif,tiff,bmp")
        inf.addRow("扩展名（逗号分隔）", self.extensions)
        layout.addWidget(inp)

        layout.addStretch(1)
        return self._make_scrollable(page)

    def _build_advanced_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        paths = QGroupBox("路径")
        pf = QFormLayout(paths)
        self.temp_dir = QLineEdit()
        self.log_dir = QLineEdit()
        tbtn = QPushButton("浏览…")
        tbtn.clicked.connect(lambda: self._browse_into(self.temp_dir))
        lbtn = QPushButton("浏览…")
        lbtn.clicked.connect(lambda: self._browse_into(self.log_dir))
        trow = QHBoxLayout()
        trow.addWidget(self.temp_dir, 1)
        trow.addWidget(tbtn)
        lrow = QHBoxLayout()
        lrow.addWidget(self.log_dir, 1)
        lrow.addWidget(lbtn)
        pf.addRow("临时目录（空=默认）", trow)
        pf.addRow("日志目录（空=默认）", lrow)
        layout.addWidget(paths)

        runtime = QGroupBox("运行时")
        rf = QFormLayout(runtime)
        self.workers = QSpinBox()
        self.workers.setRange(1, 1)
        self.workers.setValue(1)
        self.workers.setToolTip("v1 固定串行处理，避免复杂竞态")
        rf.addRow("并发数量", self.workers)
        self.log_level = QComboBox()
        for level in ("debug", "info", "warning", "error"):
            self.log_level.addItem(level, level)
        rf.addRow("日志级别", self.log_level)
        self.chk_portable = QCheckBox("便携模式（配置/数据跟随程序目录）")
        rf.addRow(self.chk_portable)
        layout.addWidget(runtime)

        cfg_box = QGroupBox("配置管理")
        cb = QHBoxLayout(cfg_box)
        btn_export = QPushButton("导出配置")
        btn_import = QPushButton("导入配置")
        btn_reset = QPushButton("恢复默认")
        btn_export.clicked.connect(self._export_config)
        btn_import.clicked.connect(self._import_config)
        btn_reset.clicked.connect(self._reset_config)
        cb.addWidget(btn_export)
        cb.addWidget(btn_import)
        cb.addWidget(btn_reset)
        layout.addWidget(cfg_box)

        tip = QLabel(f"当前配置文件目录：{user_config_dir()}")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#666;font-size:11px;")
        layout.addWidget(tip)
        layout.addStretch(1)
        return self._make_scrollable(page)

    def _build_about_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(
            f"""
            <h2>AI Image Process</h2>
            <p><b>Version</b> {__version__}</p>
            <p>跨平台 AI 图片处理桌面客户端。</p>
            <p><b>GitHub</b>：
            <a href="{GITHUB_URL}">{GITHUB_URL}</a></p>
            <p><b>License</b>：MIT</p>
            <p>核心与 GUI 解耦；处理逻辑可在无 GUI 的 CLI 下独立运行与测试。</p>
            """
        )
        layout.addWidget(browser)
        btn = QPushButton("打开 GitHub 页面")
        btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        layout.addWidget(btn)
        return self._make_scrollable(page)

    # ----- UI events -----
    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择默认输出目录")
        if folder:
            self.out_dir.setText(folder)

    def _browse_into(self, target: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择目录")
        if folder:
            target.setText(folder)

    def _on_preset_changed(self, _index: int = 0) -> None:
        key = str(self.preset.currentData() or "custom")
        for k, _label, tmpl in NAMING_PRESETS:
            if k == key and k != "custom":
                self.template.setText(tmpl)
                self.template.setEnabled(False)
                return
        self.template.setEnabled(True)

    def _on_device_selection_changed(self, _index: int = 0) -> None:
        fixed = str(self.device_selection.currentData()) == "fixed"
        self.device_fixed.setEnabled(fixed)

    # ----- visible watermark model management -----
    _MODEL_STATUS_TEXT = {
        "downloaded": "模型已下载",
        "not_downloaded": "模型未下载",
        "not_installed": "依赖未安装",
        "unknown": "状态未知",
    }

    def _refresh_prov_status(self) -> None:
        st = visible_models.package_status()
        if st.importable:
            self.prov_status.setText(
                f"remove-ai-watermarks v{st.version or '?'} 已安装，本功能可用。"
            )
        else:
            self.prov_status.setText(
                "remove-ai-watermarks 未安装：未启用本功能时该步骤自动跳过；"
                "启用后将仅复制原图。点击“安装依赖”在线安装。"
            )

    def _refresh_visible_status(self) -> None:
        st = visible_models.package_status()
        if not st.importable:
            self.visible_status.setText(
                "remove-ai-watermarks 未安装，启用后该步骤会失败。点击“安装依赖”在线安装。"
            )
        elif not st.visible_ready:
            ver = st.version or "?"
            self.visible_status.setText(
                f"已安装 v{ver}，但缺少像素运行时。请点击“安装依赖”重新安装完整依赖。"
            )
        else:
            ver = st.version or "?"
            parts = [f"remove-ai-watermarks v{ver} 可用"]
            for backend in visible_models.LEARNED_BACKENDS:
                ms = visible_models.model_status(backend)
                parts.append(f"{backend}: {self._MODEL_STATUS_TEXT.get(ms, ms)}")
            if not st.onnx_ready:
                parts.append("migan/lama 需先安装后端支持（点击下方按钮）")
            self.visible_status.setText("；".join(parts))
        self.btn_install_onnx.setEnabled(st.importable and not st.onnx_ready)
        ready = st.visible_ready and st.onnx_ready
        self.btn_dl_migan.setEnabled(ready)
        self.btn_dl_lama.setEnabled(ready)

    def _refresh_dependency_status(self) -> None:
        self._refresh_prov_status()
        self._refresh_visible_status()

    # ----- in-app dependency installation -----
    def _install_status_label(self, feature: str) -> QLabel:
        return self.prov_status if feature == "provenance" else self.visible_status

    def _busy(self) -> bool:
        return bool(
            (self._dl_thread is not None and self._dl_thread.isRunning())
            or (self._ins_thread is not None and self._ins_thread.isRunning())
        )

    def _set_install_busy(self, busy: bool) -> None:
        # Never run pip and the model download concurrently: pip may be
        # (re)installing the very package the download imports.
        for btn in (
            self.btn_install_prov,
            self.btn_install_visible,
            self.btn_install_onnx,
            self.btn_dl_migan,
            self.btn_dl_lama,
        ):
            btn.setEnabled(not busy)
        if not busy:
            self._refresh_dependency_status()

    def _install_dependency(self, feature: str) -> None:
        if self._busy():
            QMessageBox.information(self, "任务进行中", "已有安装/下载任务正在进行，请稍候。")
            return
        self._ins_feature = feature
        self._ins_log = []
        self._ins_error = ""
        self._set_install_busy(True)
        label = dependency_installer.feature_label(feature)
        spec = dependency_installer.feature_spec(feature)
        self._install_status_label(feature).setText(
            f"正在安装 {spec} …（完成后自动刷新状态，期间可关闭本窗口）"
        )
        self._ins_thread = QThread(self)
        self._ins_worker = PipInstallWorker(feature, self._config.runtime.portable_mode)
        self._ins_worker.moveToThread(self._ins_thread)
        self._ins_thread.started.connect(self._ins_worker.run)
        self._ins_worker.progress.connect(self._on_install_progress)
        self._ins_worker.ok.connect(self._on_install_ok)
        self._ins_worker.failed.connect(self._on_install_failed)
        self._ins_worker.ok.connect(self._ins_thread.quit)
        self._ins_worker.failed.connect(self._ins_thread.quit)
        self._ins_thread.finished.connect(self._ins_worker.deleteLater)
        self._ins_thread.finished.connect(self._on_install_thread_finished)
        self._ins_thread.start()

    @Slot(str)
    def _on_install_progress(self, line: str) -> None:
        text = line.strip()
        if text:
            self._ins_log.append(text)
            if len(self._ins_log) > 500:
                del self._ins_log[0]
        self._install_status_label(self._ins_feature).setText(f"正在安装：{text}")

    @Slot(str)
    def _on_install_ok(self, feature: str) -> None:
        self._ins_error = ""
        label = dependency_installer.feature_label(feature)
        self._install_status_label(feature).setText(f"{label} 依赖安装完成，无需重启即可使用。")
        QMessageBox.information(self, "安装成功", f"{label} 依赖已安装完成，现在即可使用对应功能。")

    @Slot(str, str)
    def _on_install_failed(self, feature: str, error: str) -> None:
        label = dependency_installer.feature_label(feature)
        spec = dependency_installer.feature_spec(feature)
        manual = dependency_installer.manual_install_command([spec])
        self._ins_error = error.strip() or "未知错误"
        short = self._ins_error if len(self._ins_error) <= 500 else self._ins_error[:500] + "…"
        self._install_status_label(feature).setText(
            f"{label} 依赖安装失败：{short}\n手动安装：{manual}"
        )
        log_text = "\n".join(self._ins_log[-100:])
        detail_parts = []
        if log_text:
            detail_parts.append("---- pip 输出（最后 100 行）----\n" + log_text)
        detail_parts.append("---- 错误 ----\n" + self._ins_error)
        detail_parts.append("---- 手动安装 ----\n" + manual)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("依赖安装失败")
        box.setText(f"{label} 依赖安装失败。")
        box.setInformativeText(
            f"原因：{short}\n\n手动安装方法：\n{manual}\n\n（完整日志见下方“显示详情”，可选中复制）"
        )
        box.setDetailedText("\n\n".join(detail_parts))
        copy_btn = box.addButton("复制手动安装命令", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() == copy_btn:
            clipboard = QGuiApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(manual)

    @Slot()
    def _on_install_thread_finished(self) -> None:
        self._ins_thread = None
        self._ins_worker = None
        self._set_install_busy(False)
        if self._ins_error:
            label = dependency_installer.feature_label(self._ins_feature)
            try:
                spec = dependency_installer.feature_spec(self._ins_feature)
                manual = dependency_installer.manual_install_command([spec])
            except ValueError:
                manual = ""
            short = self._ins_error if len(self._ins_error) <= 500 else self._ins_error[:500] + "…"
            text = f"{label} 依赖安装失败：{short}"
            if manual:
                text += f"\n手动安装：{manual}"
            self._install_status_label(self._ins_feature).setText(text)

    def _download_visible_model(self, backend: str) -> None:
        if self._busy():
            QMessageBox.information(self, "任务进行中", "已有安装/下载任务正在进行，请稍候。")
            return
        self._set_download_busy(backend, True)
        self.visible_status.setText(f"正在下载 {backend} 模型…（完成后可关闭本窗口）")
        self._dl_thread = QThread(self)
        self._dl_worker = ModelDownloadWorker(backend)
        self._dl_worker.moveToThread(self._dl_thread)
        self._dl_thread.started.connect(self._dl_worker.run)
        self._dl_worker.ok.connect(self._on_model_download_ok)
        self._dl_worker.failed.connect(self._on_model_download_failed)
        self._dl_worker.ok.connect(self._dl_thread.quit)
        self._dl_worker.failed.connect(self._dl_thread.quit)
        self._dl_thread.finished.connect(self._dl_worker.deleteLater)
        self._dl_thread.finished.connect(self._on_dl_thread_finished)
        self._dl_thread.start()

    def _set_download_busy(self, backend: str, busy: bool) -> None:
        self.btn_dl_migan.setEnabled(not busy)
        self.btn_dl_lama.setEnabled(not busy)

    @Slot(str, str)
    def _on_model_download_ok(self, backend: str, message: str) -> None:
        self.visible_status.setText(message)
        self._refresh_visible_status()

    @Slot(str, str)
    def _on_model_download_failed(self, backend: str, error: str) -> None:
        hint = visible_models.install_hint(backend)
        self.visible_status.setText(f"{backend} 模型下载失败：{error}\n提示：{hint}")
        self._refresh_visible_status()

    @Slot()
    def _on_dl_thread_finished(self) -> None:
        self._dl_thread = None
        self._dl_worker = None
        self._refresh_visible_status()

    def _export_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", str(Path.home() / "ai-image-process-config.json"), "JSON (*.json)"
        )
        if not path:
            return
        try:
            cfg = self._collect_ui_config()
            ConfigManager().export_to(Path(path), cfg)
            QMessageBox.information(self, "导出成功", f"已导出到：\n{path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(exc))

    def _import_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入配置", "", "JSON (*.json)")
        if not path:
            return
        try:
            import json

            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            cfg = AppConfig.from_dict(raw)
            self._config = cfg
            self._apply_config_to_ui(cfg)
            QMessageBox.information(self, "导入成功", "配置已加载到设置页，点击“保存”后生效。")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "导入失败", str(exc))

    def _reset_config(self) -> None:
        reply = QMessageBox.question(
            self,
            "恢复默认",
            "确定恢复默认配置吗？当前未保存的修改将丢失。",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._config = default_config()
        self._apply_config_to_ui(self._config)

    def _on_accept(self) -> None:
        try:
            self._config = self._collect_ui_config()
        except ValueError as exc:
            QMessageBox.warning(self, "设置无效", str(exc))
            return
        self.accept()

    # ----- bind -----
    def _apply_config_to_ui(self, cfg: AppConfig) -> None:
        self.out_dir.setText(cfg.output.directory)
        self.chk_auto_create.setChecked(cfg.output.auto_create_directory)
        self.chk_preserve.setChecked(cfg.output.preserve_originals)
        self.chk_use_source.setChecked(cfg.output.use_source_directory)

        preset_key = cfg.naming.preset or "custom"
        pidx = self.preset.findData(preset_key)
        if pidx < 0:
            # match by template
            pidx = 0
            for i, (key, _label, tmpl) in enumerate(NAMING_PRESETS):
                if tmpl and tmpl == cfg.naming.template:
                    pidx = i
                    break
            else:
                pidx = self.preset.findData("custom")
        self.preset.setCurrentIndex(max(0, pidx))
        self.template.setText(cfg.naming.template)
        self._on_preset_changed()
        if str(self.preset.currentData()) == "custom":
            self.template.setText(cfg.naming.template)
            self.template.setEnabled(True)
        self.number_start.setValue(cfg.naming.number_start)
        self.number_width.setValue(cfg.naming.number_width)

        cidx = self.conflict.findData(cfg.output.conflict_policy)
        self.conflict.setCurrentIndex(max(0, cidx))

        self.chk_cleanup_success.setChecked(cfg.runtime.cleanup_temp_on_success)
        self.chk_cleanup_startup.setChecked(cfg.runtime.cleanup_temp_on_startup)

        self.chk_dedup.setChecked(cfg.steps.deduplicate.enabled)
        daidx = self.dedup_algorithm.findData(cfg.steps.deduplicate.algorithm)
        self.dedup_algorithm.setCurrentIndex(max(0, daidx))

        self.chk_prov.setChecked(cfg.steps.provenance_cleanup.enabled)
        midx = self.prov_mode.findData(cfg.steps.provenance_cleanup.mode)
        self.prov_mode.setCurrentIndex(max(0, midx))

        self.chk_visible.setChecked(cfg.steps.visible_watermark.enabled)
        vbidx = self.visible_backend.findData(cfg.steps.visible_watermark.backend)
        self.visible_backend.setCurrentIndex(max(0, vbidx))
        self._refresh_dependency_status()

        self.chk_reenc.setChecked(cfg.steps.reencode.enabled)
        self.qmin.setValue(cfg.steps.reencode.quality_min)
        self.qmax.setValue(cfg.steps.reencode.quality_max)
        self.chk_icc.setChecked(cfg.steps.reencode.apply_srgb_icc)

        self.chk_device.setChecked(cfg.steps.device_metadata.enabled)
        sidx = self.device_selection.findData(cfg.steps.device_metadata.selection)
        self.device_selection.setCurrentIndex(max(0, sidx))
        if cfg.steps.device_metadata.fixed_device_id:
            didx = self.device_fixed.findData(cfg.steps.device_metadata.fixed_device_id)
            if didx >= 0:
                self.device_fixed.setCurrentIndex(didx)
        self._on_device_selection_changed()
        self.chk_rand_time.setChecked(cfg.steps.device_metadata.randomize_datetime)
        self.offset_min.setValue(cfg.steps.device_metadata.offset_min_minutes)
        self.offset_max.setValue(cfg.steps.device_metadata.offset_max_minutes)
        self.software.setText(cfg.steps.device_metadata.software_tag)

        self.chk_rename.setChecked(cfg.steps.rename.enabled)
        self.chk_output_write.setChecked(cfg.steps.output_write.enabled)

        self.chk_recurse.setChecked(cfg.input.recurse_folders)
        self.extensions.setText(",".join(cfg.input.extensions))

        self.temp_dir.setText(cfg.paths.temp_dir)
        self.log_dir.setText(cfg.paths.log_dir)
        self.workers.setValue(1)
        lidx = self.log_level.findData(cfg.runtime.log_level)
        self.log_level.setCurrentIndex(max(0, lidx))
        self.chk_portable.setChecked(cfg.runtime.portable_mode)

    def _collect_ui_config(self) -> AppConfig:
        cfg = deepcopy(self._config)
        cfg.output.directory = self.out_dir.text().strip()
        cfg.output.auto_create_directory = self.chk_auto_create.isChecked()
        cfg.output.preserve_originals = self.chk_preserve.isChecked()
        cfg.output.use_source_directory = self.chk_use_source.isChecked()
        cfg.output.conflict_policy = str(self.conflict.currentData() or "rename")

        preset = str(self.preset.currentData() or "custom")
        cfg.naming.preset = preset
        tmpl = self.template.text().strip()
        if preset != "custom":
            for key, _label, t in NAMING_PRESETS:
                if key == preset and t:
                    tmpl = t
                    break
        if not tmpl:
            raise ValueError("命名模板不能为空")
        cfg.naming.template = tmpl
        cfg.naming.number_start = int(self.number_start.value())
        cfg.naming.number_width = int(self.number_width.value())

        cfg.runtime.cleanup_temp_on_success = self.chk_cleanup_success.isChecked()
        cfg.runtime.cleanup_temp_on_startup = self.chk_cleanup_startup.isChecked()
        cfg.runtime.portable_mode = self.chk_portable.isChecked()
        cfg.runtime.worker_count = 1
        cfg.runtime.log_level = str(self.log_level.currentData() or "info")

        cfg.steps.deduplicate.enabled = self.chk_dedup.isChecked()
        cfg.steps.deduplicate.algorithm = str(self.dedup_algorithm.currentData() or "md5")

        cfg.steps.provenance_cleanup.enabled = self.chk_prov.isChecked()
        cfg.steps.provenance_cleanup.mode = str(self.prov_mode.currentData() or "metadata")

        cfg.steps.visible_watermark.enabled = self.chk_visible.isChecked()
        cfg.steps.visible_watermark.backend = str(self.visible_backend.currentData() or "auto")

        qmin = int(self.qmin.value())
        qmax = int(self.qmax.value())
        if qmin > qmax:
            raise ValueError("JPEG 质量最小值不能大于最大值")
        cfg.steps.reencode.enabled = self.chk_reenc.isChecked()
        cfg.steps.reencode.quality_min = qmin
        cfg.steps.reencode.quality_max = qmax
        cfg.steps.reencode.apply_srgb_icc = self.chk_icc.isChecked()

        cfg.steps.device_metadata.enabled = self.chk_device.isChecked()
        cfg.steps.device_metadata.selection = str(self.device_selection.currentData() or "random")
        fixed_id = self.device_fixed.currentData()
        cfg.steps.device_metadata.fixed_device_id = str(fixed_id) if fixed_id else None
        if cfg.steps.device_metadata.selection == "fixed" and not cfg.steps.device_metadata.fixed_device_id:
            raise ValueError("选择“固定设备”时请指定设备")
        cfg.steps.device_metadata.randomize_datetime = self.chk_rand_time.isChecked()
        omin = int(self.offset_min.value())
        omax = int(self.offset_max.value())
        if omin >= omax:
            raise ValueError("时间偏移最小值必须小于最大值")
        cfg.steps.device_metadata.offset_min_minutes = omin
        cfg.steps.device_metadata.offset_max_minutes = omax
        cfg.steps.device_metadata.software_tag = self.software.text().strip() or "iOS Camera"

        cfg.steps.rename.enabled = self.chk_rename.isChecked()
        cfg.steps.output_write.enabled = self.chk_output_write.isChecked()

        cfg.input.recurse_folders = self.chk_recurse.isChecked()
        exts = [e.strip().lstrip(".").lower() for e in self.extensions.text().split(",") if e.strip()]
        if not exts:
            raise ValueError("至少需要一个输入扩展名")
        cfg.input.extensions = exts

        cfg.paths.temp_dir = self.temp_dir.text().strip()
        cfg.paths.log_dir = self.log_dir.text().strip()
        return cfg
