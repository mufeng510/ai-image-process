"""User-facing error mapping."""
from __future__ import annotations


def to_user_message(exc: BaseException, path: str | None = None) -> str:
    name = type(exc).__name__
    detail = str(exc).strip() or name
    target = f"\n文件：{path}" if path else ""
    if isinstance(exc, FileNotFoundError):
        return f"无法读取文件。{target}\n可能原因：文件不存在或路径无效。\n详情：{detail}"
    if isinstance(exc, PermissionError):
        return f"没有权限访问路径。{target}\n可能原因：目录不可写或权限不足。\n详情：{detail}"
    if isinstance(exc, IsADirectoryError):
        return f"期望文件但得到了目录。{target}"
    lower = detail.lower()
    if "cannot identify image" in lower:
        return f"无法处理图片。{target}\n可能原因：图片损坏或格式不受支持。\n详情：{detail}"
    return f"处理失败。{target}\n详情：{detail}"
