# Changelog

本文件记录面向用户的主要变更。版本号遵循语义化规则；破坏性/行为变更会单独列出迁移说明。
格式：Added / Changed / Fixed / Removed / Security。对应标签：`v0.5.9...v0.6.0`。

## 0.6.0 · 2026-11-07

### Added
- 主界面「输出」区新增 **「处理完成后删除原件」** 勾选框（默认关闭，危险操作）：任务真正跑完且产物已落盘后——输入是文件则删除该文件；输入是文件夹且其中没有处理失败的文件则整体删除（**含其中非图片文件**）。预检失败 / 取消 / 无落盘产物时不动；输入含本次产物、隐藏图片库时永不删除；配置项为 `input.delete_originals_after_run`。
- Live Photo 本地动态改为两段式：前 ~0.5s `ease-out cubic` 快速推近到 `1+motion_strength`，随后画面定住并叠加按 `seed` 随机相位的低幅正弦抖动；比匀速 Ken Burns 更接近真人手持。不改变 `local_motion` 的配置项与默认值。
- Windows 发布包内置 **ffprobe**（BtbN FFmpeg-Builds autobuild-2026-11-06-12-50, LGPL-9.0.2，sha256 已校验；`Tools/ffmpeg/SOURCE.txt` 记录来源）。

### Changed
- **默认开启除「去除可见水印」外的全部步骤**：新装/新配置下 `rotate_crop`、`hidden_image`、`live_photo` 默认开启（`visible_watermark` 仍默认关闭）。
- **缺少运行时环境一律拒绝，不再静默降级**：
  - 「清理 AI Metadata」在缺少 `remove-ai-watermarks` 时预检直接拦下（`rc=2`），不会以「复制原图」蒙混过关；
  - 「写入设备 Metadata」在 ExifTool 不可用时步骤失败（预检原本就会拦），移除「仅选机型、跳过写入还算成功」的旧行为；
  - 设置界面对应文案已同步。
- 「处理完成后删除原件」勾选框随配置持久化，仅 GUI 使用。

### Fixed
- 静默降级：provenance 缺包静默复制原图（`ok=True`）→ 现在明确失败并给出安装指引。
- Windows 下 `scripts/install_agent_skill.sh` 依赖 `python3`（git-bash 默认没有），装 skill 必然报 "frontmatter looks wrong" → 改为纯 `head/sed/grep` 校验，已实测安装/卸载均成功；同时把本仓库 17 项 Windows 专有测试失败全部修掉（454 passed / 9 skipped）。

### Migration notes（0.5.9 → 0.6.0）
- 已有配置**不受影响**（步骤的显式开/关于配置会原样保留）；只有全新配置/新安装才看到全部步骤默认开启。
- 新环境的**首次运行可能直接被预检拦下**：「隐藏图片」默认开启但未配素材库 → `rc=2`；Python 运行时没有 `remove-ai-watermarks` → `rc=2`；没有 FFmpeg → Live Photo `rc=2`。按提示配置素材库/安装依赖，或用 `--config` 局部关掉对应步骤即可。
- 「处理完成后删除原件」默认关闭；一旦开启，删除**不可恢复**，请先小批量验证。
- 之前发布的老配置升级时不会被重写（migration 版本仍是 2）。

## 0.5.9 及更早
见 Git 历史与各版本标签的发布说明（`v0.5.x`）。
