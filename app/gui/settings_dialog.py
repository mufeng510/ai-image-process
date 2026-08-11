"""Full settings dialog: General / Processing / Advanced / About."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
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
    QSpinBox,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.config.manager import ConfigManager
from app.config.paths import phones_json_path, user_config_dir
from app.config.schema import AppConfig, default_config
from app.core.device_library import DeviceLibrary
from app.gui.naming_presets import NAMING_PRESETS, template_for_preset
from app.version import __version__

GITHUB_URL = "https://github.com/mufeng510/ai-image-process"


class SettingsDialog(QDialog):
    """Edit AppConfig with full tabs and import/export/reset."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(620, 560)
        self._config = deepcopy(config)
        self._devices: list[tuple[str, str]] = []  # (id, label)
        self._load_devices()

        root = QVBoxLayout(self)
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
        return page

    def _build_processing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

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
        layout.addWidget(prov)

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
        return page

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
        return page

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
        return page

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

        self.chk_prov.setChecked(cfg.steps.provenance_cleanup.enabled)
        midx = self.prov_mode.findData(cfg.steps.provenance_cleanup.mode)
        self.prov_mode.setCurrentIndex(max(0, midx))

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

        cfg.steps.provenance_cleanup.enabled = self.chk_prov.isChecked()
        cfg.steps.provenance_cleanup.mode = str(self.prov_mode.currentData() or "metadata")

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
