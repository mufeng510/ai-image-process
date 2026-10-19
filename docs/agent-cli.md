# AI Image Process —— CLI 自动化参考

面向脚本与 AI Agent。**唯一权威的参数定义是 `--help`**，本文档补充的是
`--help` 不会告诉你的东西：配置项、退出码语义、以及几处会静默出错的默认行为。

配置项的权威来源是 `app/config/schema.py`（`default_config()`）。改动配置项时
请同步本文档，`tests/core/test_agent_cli_docs.py` 会检查文档里提到的每个配置键
都真实存在。

---

## 1. 两个入口，先选对

| 场景 | 命令 |
| --- | --- |
| 打包后的便携包 | `AI-Image-Process-CLI <参数>` |
| 源码仓库 | `.venv/bin/python -m app cli <参数>` |

**打包版的 GUI 入口不接受 CLI 参数。** 传了不会报错、不会打印帮助，只会弹出一个
窗口然后安静退出（退出码 0）——这是最容易误判的一种情况。始终用 `-CLI` 那个。

源码仓库里也可以省略 `cli` 子命令：`.venv/bin/python -m app ./photos -o ./out`
会自动分派到 CLI；但显式写 `cli` 更清晰，也避免和「路径恰好以 `-` 开头」打架。

---

## 2. 标准工作流

```bash
# 1) 先看计划：--dry-run 只跑预检，不写任何文件，连输出目录都不会创建
AI-Image-Process-CLI ./photos -o ./out --dry-run --json-summary | jq .

# 2) 确认无误后实跑
AI-Image-Process-CLI ./photos -o ./out --json-summary > result.json

# 3) 从 JSON 读产出，不要去扫目录
jq -r '.outputs[].output' result.json
```

`--json-summary` 打开时，**stdout 只有 JSON 文档**，所有进度与日志都走 stderr，
可以直接管道给 `jq`。不带这个参数时 stdout 是人类可读的进度行，不能解析。

批量任务（几百张以上）建议先跑 `--dry-run`：`planned_input_count` 能立刻暴露
「我以为放了 200 张，其实只扫到 12 张」这类问题。

---

## 3. 退出码

| 码 | 含义 | Agent 该怎么做 |
| --- | --- | --- |
| `0` | 全部成功 | 仍建议读 `failed` 字段确认为 0 |
| `1` | **部分**失败 | 有文件没处理成功，读 `failures[]` 里的 `file` 与 `error` |
| `2` | 预检未通过 | 任务根本没开始，**零产出**。错误在 `preflight_error` |

`rc=0` 不等于「每张都成功」以外的任何含义，但它确实等于「有产出且没有失败项」。
反过来，`rc=1` 时绝不能当作成功。

预检失败（`rc=2`）涵盖：输入路径不存在、目录里没有可处理的图片、非 JPG 输入但
没有会重编码的步骤、ExifTool / FFmpeg 不可用、Live Photo 的 AI Provider 未配置等。

---

## 4. 摘要 JSON 的结构

```jsonc
{
  "job_id": "9dfad9aab1f7",
  "success": 7,              // 成功文件数
  "failed": 0,
  "cancelled": false,
  "preflight_failed": false,
  "preflight_error": null,   // 预检失败时的中文说明，含修复指引
  "steps": ["deduplicate", "rename", "..."],   // 本次执行的步骤顺序
  "outputs": [               // 每条给出输入 → 产出，产物恒为 .JPG
    { "source": "/abs/in/a.jpg", "output": "/abs/out/20261019-101500/a.JPG" }
  ],
  "failures": [              // 只有失败项
    { "file": "/abs/in/b.tif", "error": "LivePhoto Stage-1 validation failed: ..." }
  ],
  "dry_run": true,                        // 仅 --dry-run 时出现
  "planned_output_dir": "/abs/out/..."    // 仅 --dry-run 时出现
  "planned_input_count": 12               // 仅 --dry-run 时出现
}
```

---

## 5. 会静默出错的默认行为

这几条是「看起来成功、实际不符合预期」的高发点：

| 行为 | 默认 | 后果 |
| --- | --- | --- |
| 目录**不递归** | `input.recurse_folders=false` | 子目录里的图片被**静默跳过** |
| 精确重复被删除 | `steps.deduplicate.enabled=true` | 内容完全相同的文件只保留一个 |
| 每次建时间戳子目录 | `output.subfolder_per_run=true` | 产出在 `out/20261019-101500/` 下，不在 `out/` 根 |
| 同名冲突重命名 | `output.conflict_policy='rename'` | 不覆盖，改为加后缀 |
| `--seed` **不保证字节复现** | — | 像素一致，但 EXIF 时间戳写的是运行时刻；别拿它做校验和比对 |

前三条是批量场景最常见的「图去哪了」。用 `--dry-run` 的 `planned_input_count`
对一眼即可确认。

---

## 6. 参数

以 `--help` 为准，这里只列语义与坑：

| 参数 | 说明 |
| --- | --- |
| `-o, --output` | 输出根目录。必填（除 `--list-steps`/`--version`） |
| `--config` | 配置 JSON 路径。**部分覆盖**：未提及的字段沿用默认值 |
| `--seed` | 机型/质量的随机种子。见上面的复现性警告 |
| `--no-provenance` | 关闭「清理 AI Metadata」 |
| `--enable-rotate-crop` + `--min-angle` / `--max-angle` | 旋转裁剪 |
| `--hidden-library` + `--hidden-opacity` | 隐藏图片（`opacity` 取值 0–0.5） |
| `--enable-live-photo` + `--video-source` | `local_motion` 本地生成；`ai_video` **必须**先配 Provider |
| `--dry-run` | 只跑预检，不落盘 |
| `--json-summary` | stdout 只输出 JSON |

步骤执行顺序固定为：
`deduplicate → rename → provenance_cleanup → visible_watermark → reencode →
device_metadata → rotate_crop → hidden_image → live_photo → output_write`

产物恒为 `.JPG`（大写：爱思助手对扩展名做区分大小写的检查，小写会被直接跳过）：
如果输入里有 TIFF/PNG 而没有启用任何会重编码的步骤，预检会
直接拒绝（`rc=2`），而不是产出一个后缀骗人的文件。

---

## 7. 配置项

只有 `--config` 能设置的项。JSON 是**局部覆盖**——写什么改什么，其余用默认值。

```jsonc
{
  "input":  { "recurse_folders": true, "extensions": ["jpg", "jpeg", "png"] },
  "output": { "subfolder_per_run": false, "conflict_policy": "skip" },
  "runtime":{ "worker_count": 4 },
  "naming": { "preset": "original", "template": "{original_name}" },
  "steps": {
    "live_photo": {
      "enabled": true,
      "video_source": "ai_video",
      "ai_video": { "provider": "...", "model": "...", "endpoint": "...", "api_key": "..." }
    }
  }
}
```

### 全部配置键与默认值

| 键 | 默认 | 含义 |
| --- | --- | --- |
| `config_version` | `2` | 配置结构版本，旧版本会被自动迁移 |
| `ui_language` | `zh-CN` | 界面语言（仅 GUI，CLI 不使用） |
| `input.recurse_folders` | `false` | **是否递归扫描子目录** |
| `input.extensions` | `jpg,jpeg,png,webp,tif,tiff,bmp` | 接受的扩展名白名单 |
| `output.directory` | `""` | 输出目录（`-o` 会覆盖它） |
| `output.subfolder_per_run` | `true` | 每次任务建时间戳子文件夹 |
| `output.conflict_policy` | `rename` | `overwrite` / `skip` / `rename` |
| `output.auto_create_directory` | `true` | 自动创建输出目录 |
| `output.use_source_directory` | `false` | 输出到源目录 |
| `output.preserve_originals` | `true` | 保留原图 |
| `output.allow_overwrite_originals` | `false` | 是否允许覆盖原图 |
| `naming.preset` / `naming.template` | `original` / `{original_name}` | 命名规则 |
| `naming.number_start` / `number_width` | `1` / `3` | 编号起点与位数 |
| `runtime.worker_count` | `1` | **并发数**，>1 明显更快 |
| `runtime.log_level` | `info` | 日志级别 |
| `runtime.portable_mode` | `false` | 便携模式（数据目录随程序走） |
| `runtime.cleanup_temp_on_success` / `_on_startup` | `true` | 临时目录清理 |
| `paths.temp_dir` / `paths.log_dir` | `""` | 自定义临时/日志目录 |
| `steps.deduplicate.enabled` | `true` | 去重 |
| `steps.deduplicate.algorithm` | `md5` | `md5` / `sha1` / `sha256` |
| `steps.rename.enabled` | `true` | 改名步骤 |
| `steps.provenance_cleanup.enabled` | `true` | 清理 AI Metadata |
| `steps.provenance_cleanup.mode` | `metadata` | 清理模式 |
| `steps.visible_watermark.enabled` | `false` | 去可见水印（需额外依赖） |
| `steps.visible_watermark.backend` | `auto` | `auto` / `cv2` / `migan` / `lama` |
| `steps.reencode.enabled` | `true` | 重编码 |
| `steps.reencode.format` | `jpeg` | 输出格式 |
| `steps.reencode.quality_min` / `quality_max` | `96` / `99` | JPEG 质量区间 |
| `steps.reencode.apply_srgb_icc` | `true` | 套用 sRGB ICC |
| `steps.device_metadata.enabled` | `true` | 写设备 EXIF（**需要 ExifTool**） |
| `steps.device_metadata.selection` | `random` | `random` / `fixed` |
| `steps.device_metadata.fixed_device_id` | `null` | `fixed` 时指定机型 |
| `steps.device_metadata.randomize_datetime` | `true` | 拍摄时间随机化 |
| `steps.device_metadata.offset_min_minutes` / `offset_max_minutes` | `10` / `10000` | 时间偏移范围 |
| `steps.device_metadata.software_tag` | `iOS Camera` | Software 标签 |
| `steps.rotate_crop.enabled` | `false` | 旋转裁剪 |
| `steps.rotate_crop.min_angle` / `max_angle` | `-2.0` / `2.0` | 角度范围 |
| `steps.hidden_image.enabled` | `false` | 隐藏图片 |
| `steps.hidden_image.library_dir` | `""` | 素材库目录 |
| `steps.hidden_image.opacity` | `0.02` | 不透明度，0–0.5 |
| `steps.live_photo.enabled` | `false` | Live Photo |
| `steps.live_photo.video_source` | `local_motion` | `local_motion` / `ai_video` |
| `steps.live_photo.local_motion.duration_seconds` / `fps` / `motion_strength` | `3.0` / `30` / `0.06` | 本地动态参数 |
| `steps.live_photo.ai_video.provider` / `model` / `endpoint` / `api_key` | `""` | **AI Provider，缺一不可** |
| `steps.live_photo.ai_video.prompt` / `extra_prompt` | 见 schema | 提示词 |
| `steps.live_photo.ai_video.duration_seconds` / `timeout_seconds` / `retry_count` | `3.0` / `300` / `2` | 超时与重试 |
| `steps.output_write.enabled` | `true` | 写出产物 |

`--video-source ai_video` 在 Provider 未配置时**必然** `rc=2`——这是设计如此，
不要试图绕过。

---

## 8. 可复制的配方

```bash
# 递归处理整个目录树，产出平铺（不建时间戳子目录）
cfg=$(mktemp); printf '{"input":{"recurse_folders":true},"output":{"subfolder_per_run":false}}' > "$cfg"
AI-Image-Process-CLI ./photos -o ./out --config "$cfg" --json-summary | jq '[.outputs[].output]'

# 4 路并发（默认是 1，批量场景收益最大的一步）
printf '{"runtime":{"worker_count":4}}' > "$cfg"

# Live Photo：本地动态
AI-Image-Process-CLI ./photos -o ./out --enable-live-photo

# Live Photo：AI 视频（必须先配 Provider）
printf '{"steps":{"live_photo":{"enabled":true,"video_source":"ai_video",
  "ai_video":{"provider":"openai","model":"gpt-image-1","endpoint":"https://...","api_key":"..."}}}}' > "$cfg"
AI-Image-Process-CLI ./photos -o ./out --config "$cfg"

# 只要 JPEG，不要动原始 EXIF
AI-Image-Process-CLI ./photos -o ./out --no-provenance

# 判断"跑成功没有"（注意 rc=1 是部分失败）
out=$(AI-Image-Process-CLI ./photos -o ./out --json-summary); rc=$?
echo "$out" | jq -e '.failed == 0 and (.outputs|length) > 0' >/dev/null && echo OK || echo "rc=$rc"
```

---

## 9. 排查

| 现象 | 原因 |
| --- | --- |
| 弹出窗口、无输出、退出码 0 | 用了 GUI 入口，改用 `AI-Image-Process-CLI` |
| `rc=2`，`preflight_error` 提到 ExifTool | 运行时不可用。正式安装包已内置（含 unix 的 perl）；开发环境跑 `scripts/fetch_exiftool.sh` 与 `scripts/fetch_perl.sh`，或用设置面板里的「安装」按钮 |
| `rc=2`，`preflight_error` 提到 FFmpeg | 同上，缺 FFmpeg 时 Live Photo 不可用 |
| 产出比预期少 | 先看 `--dry-run` 的 `planned_input_count`；多半是没递归（`input.recurse_folders`）或被去重了 |
| 输出目录里找不到文件 | `output.subfolder_per_run` 默认为 `true`，产物在时间戳子目录里 |
| 非 JPG 输入被拒（`rc=2`） | 没有启用任何会重编码的步骤。启用 `reencode`（默认已开）或 `--enable-rotate-crop` |
| `--config` 里的设置没生效 | 配置文件是**局部覆盖**；确认键名与 `app/config/schema.py` 完全一致，未知键会被静默丢弃 |
| 两次运行产物校验和不同 | `--seed` 不覆盖 EXIF 时间戳，属预期行为 |

---

## 10. 开发环境

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[gui,dev]"
scripts/fetch_perl.sh        # unix：自包含 perl（ExifTool 解释器）
scripts/fetch_exiftool.sh    # unix：原生 ExifTool
scripts/fetch_ffmpeg.sh      # FFmpeg
```

缺任何一个都会让预检在 unix 上拒绝启动，错误信息会指名缺的是哪一个。