# AI Image Process

跨平台 AI 图片批量处理桌面客户端（Python / PySide6）。

当前版本：**0.3.0**（见 `app/version.py`）

## 功能

一条可配置的流水线按序处理图片，默认步骤（顺序固定，每步可独立开关）：

| 顺序 | 步骤 | 说明 |
|------|------|------|
| 1 | 去重 | 按文件内容哈希（MD5 / SHA-1 / SHA-256）去重，重复文件仅保留第一张 |
| 2 | 文件命名 | 模板化命名（预设或自定义模板，支持日期/时间/序号变量）；去重后立即确定 basename，后续 JPG/MOV 共享 |
| 3 | 清理 AI Metadata | 移除生成式 AI 痕迹元数据（可选依赖 [remove-ai-watermarks](https://github.com/wiltodelta/remove-ai-watermarks)） |
| 4 | 去除可见水印 | 移除 AI 生成角标（Gemini / 豆包 / 即梦等），后端：`auto` / `cv2` / `migan` / `lama` |
| 5 | 图片重编码 | JPEG 质量区间重编码，可嵌入 sRGB ICC 配置 |
| 6 | 写入设备 Metadata | 随机或固定机型 EXIF（内置 28 款 iPhone 机型库），随机化拍摄时间与 Software 标签；隐藏图片启用且有真实拍摄参数时可作为来源（缺字段回退原逻辑，GPS/UUID 永不继承） |
| 7 | 图片旋转与裁剪 | 每张图独立随机角度（默认 −2° ~ +2°），保持原宽高比的最大内接裁剪，无黑边不变形（默认关闭） |
| 8 | 隐藏图片 | 真实拍摄照片素材池 cover 覆盖合成（默认不透明度 2%）；数量不足时**禁止开始任务**，成功后**永久删除**对应素材（默认关闭） |
| 9 | 生成 Apple Live Photo | 最终静态图 + MOV（本地轻微动态 / AI Image-to-Video），统一 Content Identifier + still-image-time，Stage-1 本地校验通过才提交（默认关闭） |
| 10 | 输出处理结果 | 冲突策略：自动重命名 / 跳过 / 覆盖；Live Photo JPG+MOV 作为整体 Bundle 原子提交 |

任务开始前统一执行 Preflight 预检查（输入集合 → 去重后数量 → 隐藏图库数量/路径安全/分配 → Live Photo 资源检查），
失败时不产生任何输出、不删除任何隐藏图片，GUI 弹窗 / CLI 返回结构化错误。

其他能力：

- 拖拽/批量选择图片与文件夹，后台线程处理，进度 / 日志 / 取消
- **每次处理自动新建时间戳输出子文件夹**：只需指定一个输出目录，每次任务会在其下新建 `20261018-143052` 这样的文件夹，多批处理不会互相覆盖；同一秒内重复运行自动追加 `-2`；完成后主界面会显示本次实际的结果目录。不想这样可在「设置 → 常规」取消勾选，改为直接输出到指定目录
  - ⚠️ 这是唯一一个**默认开启**的新功能（其余新功能默认关闭），因此升级旧版本后产物落点会从「输出目录」变成「输出目录/时间戳」。老配置升级后想保持原行为，在「设置 → 常规」取消该勾选即可。
  - 附带影响：开启时每次运行都用全新目录，因此**文件冲突策略（自动重命名/跳过/覆盖）基本不会触发**，它只在关闭本功能时才有意义；同理，「保留原始图片」的拒写保护也不会被触发（产物天然不在源目录里）。
- 版本化配置（导入 / 导出 / 重置），便携模式（配置 v2，老配置自动迁移；除上一条外新功能默认关闭）
- 内置 ExifTool 与 FFmpeg（`Tools/`），**三个平台的发布包都自带**，开箱即用；缺失时按「内置 → 运行时安装目录 → 系统 PATH」顺序解析，并在「设置 → 处理 → 外部运行时」与主界面明示缺哪一个、影响哪个功能
- 输出恒为 JPEG：没有任何重新编码步骤时若混入非 JPG 输入，任务在预检阶段就会被拦下（零产出），提交前还会再校验文件内容，拒绝把非 JPEG 字节写成 `.jpg`
- iPhone 导入：**只是一个 GUI 提示入口**，不参与 Pipeline，也没有对应的 CLI 参数。点「导入 iPhone…」会尝试唤起**爱思助手**并弹出分步操作指引；除此之外**不读、不写、不复制任何文件**
  - 处理结果本身已经是爱思助手要的形状（同一目录内 `x.jpg` + `x.mov` 同名配对），一次会话处理多批时在爱思助手里选要导入的那一批即可，所以中间文件夹、预检查、复制都没有意义
  - 指引里会把当前输出目录（以及上一次任务的结果目录）作为文字提示显示出来，但不会去打开它
- 冻结版（安装包/便携包）内置 **纯 Python wheel 安装器**，无需本机 pip 即可在线安装可选依赖

## 下载安装

从 [Releases](https://github.com/mufeng510/ai-image-process/releases) 下载：

| 平台 | 产物 |
|------|------|
| Windows | `AI-Image-Process-windows-x64-setup.exe`（Inno Setup 安装包）、`…-portable.zip`（便携） |
| macOS | `AI-Image-Process-macos-arm64-portable.zip` |
| Linux | `AI-Image-Process-linux-x64-portable.zip` |

产物未签名：Windows 可能弹 SmartScreen，macOS 可能弹 Gatekeeper，属预期行为。

## 从源码运行

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[gui,dev]"

# GUI
.venv/bin/python -m app gui

# CLI
.venv/bin/python -m app path/to/images -o ./output --no-provenance --seed 1 --json-summary
```

CLI 主要参数：

```text
inputs                 输入文件和/或文件夹（必填，多个）
-o, --output           输出根目录（必填）；默认在其下新建时间戳子文件夹作为本次结果目录
--config               可选配置 JSON 路径
--seed                 RNG 种子（机型/质量随机可复现）
--no-provenance        关闭「清理 AI Metadata」步骤
--enable-rotate-crop   启用旋转裁剪（可配 --min-angle/--max-angle）
--hidden-library DIR   启用隐藏图片并指定素材库（可配 --hidden-opacity）
--enable-live-photo    启用 Live Photo（可配 --video-source local_motion|ai_video）
--list-steps           按顺序列出 Registry 步骤
--dry-run              只跑预检：报告将要处理的文件与输出目录，不写任何文件
--json-summary         输出任务摘要 JSON（含 preflight_failed/preflight_error/outputs）
--version              显示版本
```

退出码：`0` 全部成功 · `1` 部分失败 · `2` 预检拦截（含输入路径不存在或无可处理图片）。

### 给脚本 / Agent 调用

`--json-summary` 时 **stdout 只有 JSON 文档**，进度与日志走 stderr，可直接管道：

```bash
.venv/bin/python -m app ./photos -o ./out --dry-run            # 先看计划，不落盘
.venv/bin/python -m app ./photos -o ./out --json-summary \
  | jq '{ok: (.failed == 0), files: [.outputs[].output]}'
```

摘要里的 `outputs` 逐条给出 `source` → `output`，产物恒为 `.jpg`，无需再扫目录。
CLI 参数之外的配置（子目录递归 `input.recurse_folders`、并发 `runtime.worker_count`、
AI Provider `steps.live_photo.ai_video.*`、命名模板、冲突策略等）走 `--config` JSON 覆盖，
缺省字段沿用默认值。

### 打包版

解压后的便携包里有**两个**入口，共享同一份依赖：

| 入口 | 用途 |
| --- | --- |
| `AI-Image-Process` | 图形界面（Windows 为 console 子系统，不占控制台） |
| `AI-Image-Process-CLI` | 命令行，供脚本与自动化调用 |

```bash
./AI-Image-Process-CLI ./photos -o ./out --json-summary | jq '.outputs[].output'
```

Windows 上必须用 `-CLI` 这个入口：GUI 程序不持有控制台句柄，父级 shell
抓不到它的 stdout。Linux/macOS 上两者行为一致。

unix 版 ExifTool 是 perl 脚本，所以安装包**同时内置了一个自包含的 perl**
（`Tools/perl`，14 MB 压缩），`Tools/exiftool/exiftool` 是个 sh wrapper，
优先用它。因此 macOS 13+（苹果已移除 perl）和精简容器上也能开箱即用。
开发环境请先跑 `scripts/fetch_perl.sh` 与 `scripts/fetch_exiftool.sh`。

万一运行时仍不可用（手工删过文件、平台没有对应构建等），预检会**在写出任何
文件之前**拦下并说明原因；「设置 → 外部运行时」里有「安装」按钮，可一键把
便携 perl 与 ExifTool 装进用户目录，**不需要管理员权限**。

### 让 AI Agent 驱动 CLI

**图形界面里就有**：设置 →「AI Agent 集成」面板，两个按钮把指令复制到剪贴板——
「复制安装指令」给终端/Agent 执行，「复制给 Agent 的话」是一段可直接粘进对话框
的说明（含安装命令、校验步骤、以及之后该调用哪个入口）。

**软件不会自行往 Agent 的配置目录里写东西**——改不改是用户和 Agent 的决定，
设置页只负责把命令给你。

命令行等价物：

```bash
scripts/install_agent_skill.sh            # 装到 ~/.agents/skills/，跨 Agent 通用
scripts/install_agent_skill.sh --uninstall
scripts/install_agent_skill.sh --print    # 只打印 SKILL.md，不落盘
```

装完在 OpenCode 里问「用 AI Image Process 处理 ./photos」即可，描述匹配时会
自动加载；也可显式写 `@ai-image-process`。完整参考随 Skill 一起安装在
`references/agent-cli.md`（仓库里对应 `docs/agent-cli.md`）：退出码语义、
摘要 JSON 结构、全部配置键与默认值、可复制配方、排查表。
`tests/core/test_agent_cli_docs.py` 会检查文档里提到的配置键真实存在。

关于选型：本地工具就用 CLI + Skill，不需要再套一层 MCP——MCP 的位置是托管服务、
需要 OAuth、客户端没有 shell 或跨调用有状态的场景，这里一条都不占。想用生态
标准工具（需要 Node）也可以：`npx skills add <本地路径> -g -a opencode`。

版本来源：`app/version.py` 为唯一真实来源（当前 **0.3.0**），`pyproject.toml` 已对齐；
请勿以 README 缓存版本为准。

## GUI

```bash
.venv/bin/python -m app gui
```

- 主界面：拖拽区、输出目录、步骤开关、后台处理进度与日志
- 设置：常规 / 处理 / 高级 / 关于（配置导入导出、依赖安装、模型下载）

## 可选依赖（remove-ai-watermarks）

「清理 AI Metadata」与「去除可见水印」基于 remove-ai-watermarks，**默认不打包**：

- **软件内安装（推荐）**：「设置 → 处理」中对应功能旁的 **安装依赖** 按钮
  - 清理 Metadata：基础包
  - 去除可见水印：`[visible]` extra（含 cv2 后端）
  - migan/lama 支持：`[migan]` extra（onnxruntime + 模型下载）
  - 安装到用户可写目录并注入 `sys.path`，**无需重启**
- 源码运行时也可手动：`.venv/bin/pip install "remove-ai-watermarks[visible]"`
- 默认 `cv2` 后端无需模型；`migan` / `lama` 模型权重不预置，可在设置页手动下载或首次使用时自动拉取（缓存于本机 Hugging Face 缓存目录）

## 设备机型库

`assets/devices/phones.json` 内置 **28 款 iPhone**（iPhone 11 ~ 17 全系、iPhone Air、iPhone SE 3），供「写入设备 Metadata」步骤随机或固定选用；`make` / `model` / `lens` 写入 EXIF。可直接编辑该 JSON 扩展机型（`id` 需唯一）。

## 测试

```bash
.venv/bin/python -m pytest -q

# GUI 离屏冒烟（需已安装 PySide6）
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/gui
```

## 打包 / 发布

详见 [`build/README.md`](build/README.md)。GitHub Actions 全平台 release-blocking：

- 推送到 `main` → 自动构建并发布 **prerelease**（tag 形如 `v0.3.0-build.<运行号>`）
- 推送 tag `v*` → 构建并发布**正式 Release**
- 工作流：`.github/workflows/release.yml`（Windows / macOS / Ubuntu）；测试：`.github/workflows/ci.yml`

本地打包：

```powershell
# Windows 便携包 / 安装包（后者需 Inno Setup）
./scripts/build_windows.ps1
./scripts/build_windows_installer.ps1
```

```bash
# Linux / macOS 便携包
bash scripts/build_portable.sh
```

## 项目结构

```text
app/
  core/          流水线、步骤实现、设备库、wheel 安装器、ExifTool 封装
    live_photo/  LivePhotoBuilder/Validator/MovieNormalizer/providers（local_motion/ai_video）
    iphone_import/  爱思助手实况导入指引（i4tools 后端：检测 + 唤起 + 分步说明，不碰文件）
  gui/           PySide6 主界面、设置、后台 worker
  config/        版本化配置 schema 与路径（当前 v2）
  platform/      平台相关（Windows 静默子进程等）
assets/          设备机型库、ICC 配置
Tools/exiftool/  随仓库附带的 ExifTool
Tools/ffmpeg/    可选：自行放置 ffmpeg/ffprobe（注意许可证，见 build/README.md）
build/           PyInstaller spec 与打包说明
scripts/         本地构建脚本
tests/           pytest（core / config / gui / integration/live_photo）
docs/            live-photo-testing.md（Stage-1/Stage-2 验证手册）
```

## 计划

完整方案见 [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)；
Live Photo / iPhone 导入验证状态见 [`docs/live-photo-testing.md`](docs/live-photo-testing.md)
（Stage-2 真实设备验证尚未完成，相关能力标记为“未验证”）。

## 许可证

MIT
