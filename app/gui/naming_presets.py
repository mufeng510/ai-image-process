"""Filename naming presets shared by GUI settings (no Qt dependency)."""
from __future__ import annotations

# (key, label, template) — template empty means custom/user-provided
NAMING_PRESETS: list[tuple[str, str, str]] = [
    ("original", "保持原文件名", "{original_name}"),
    ("name_datetime", "原文件名 + 时间", "{original_name}_{date}_{time}"),
    ("date_name", "时间 + 原文件名", "{date}_{original_name}"),
    ("number", "序号", "IMG_{number}"),
    ("custom", "自定义", ""),
]


def template_for_preset(preset_key: str, custom_template: str = "") -> str:
    for key, _label, tmpl in NAMING_PRESETS:
        if key == preset_key:
            if key == "custom":
                return custom_template or "{original_name}"
            return tmpl or custom_template or "{original_name}"
    return custom_template or "{original_name}"
