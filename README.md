# short-video-edit

一个用于 2–15 分钟中文口播、杂志或论文解读视频的 Codex skill：转写、逐条校对、剪长停顿、烧录字幕、添加术语解释框、制作共用封面、准备平台文案，并把小红书页面准备到最后发布前。视频号提供手动上传文件。

这是 **agent 配合脚本** 的工作流。脚本负责媒体处理；原文核查、疑句判断、视觉检查和浏览器填表由当前 agent 完成。不是无人值守发布工具。

## 安装

仓库中的 `daily-article-video/` 是完整 skill 文件夹。将它复制到你的 Codex skills 目录，例如：

```sh
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R daily-article-video "${CODEX_HOME:-$HOME/.codex}/skills/"
```

如果已经安装同名 skill，先比较内容，不要直接覆盖个人版本。

依赖：Python 3.10+、Pillow、FFmpeg、ffprobe；读取源 PDF 时可使用环境中的 PDF 工具或 Poppler。默认字体使用 macOS 系统中文字体。macOS HDR 封面原生导出还需要 macOS 15+ 和 Swift 开发工具链。其他系统可配置中文字体，但需要自行验证字体、布局与 HDR 转换。

```sh
python3 -m pip install -r requirements.txt
```

转写使用火山引擎 Seed-ASR flash 服务，**会把音频发送到该服务，可能产生费用**。使用者需要自行开通并授权该服务。将 `.env.example` 中的字段填入本机 `~/.config/volc.env`，或通过 `VOLC_CONFIG_FILE` 指定其他本地文件。不要把真实凭据放进仓库，也不要在日志中打印。

浏览器需要使用者自己的登录会话。没有登录或缺少权限时，由使用者完成认证；不能假定模板自带账号或授权。浏览器工具的协议确认规则仍然适用。

## 使用

在 Codex 中提供视频路径，可附源文章路径，并调用 `$daily-article-video`。例如：

> 按 daily-article-video 处理这个口播视频，校对字幕，剪掉长停顿；小红书停在最终发布前，视频号给手动上传文件。

从你的媒体工作区执行脚本；`SKILL_DIR` 指向安装后的 `daily-article-video` 文件夹，`JOB` 指向本期输出目录：

```sh
SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/daily-article-video"
JOB="output/daily-video/example"
python3 "$SKILL_DIR/scripts/pipeline.py" prepare /path/to/input.MOV "$JOB"
# Agent 阅读完整转写、核对原文和疑句，然后填写 editorial.json。
python3 "$SKILL_DIR/scripts/pipeline.py" render "$JOB"
python3 "$SKILL_DIR/scripts/pipeline.py" check "$JOB"
```

`editorial.json` 的字段和完整操作见 [工作流参考](daily-article-video/references/WORKFLOW.md)，入口指令见 [SKILL.md](daily-article-video/SKILL.md)。处理完成后通常包含 `video.mp4`、`cover.jpg`、`subtitles.srt`、两平台文案和质检记录。

## 工作流边界

- 两平台共用一个视频和一张 1080×1440、3:4 封面；保留视频原画幅，不添加美颜或审美调色。
- 字幕按字级时间断句，科学术语、人名和数字需核对来源。没有音频感知能力时记录“未审听”，重要疑点向使用者确认。
- 长停顿结合字级空白、声学证据和语境判断；底噪较高时不能把 ASR 漏词当静音。
- HDR 封面必须正确转换并保留色彩管理。当前视频脚本不执行 HDR→SDR 色调映射；不能把封面转换成功当作成片已经转换，必须检查实际播放器和平台预览。
- 小红书需核对标题、正文、正式非活动话题、适用声明、相关旧笔记引用与已有合集，取消活动关联。**默认不点击最终发布。** 自动生成章节只有核对并应用后才算已设置。
- 平台改版可能需要调整浏览器操作；脚本不内置账号、Cookie 或绕过后台限制的代码。

## 清理

只有使用者确认两平台已上传发布成功，并明确请求清理后，才执行删除。先预览，再加 `--apply`。以下操作将删除整期输出；加 `--delete-original` 还会按记录的准确路径和 SHA-256 删除原视频：

```sh
python3 "$SKILL_DIR/scripts/finalize.py" "$JOB" --purge --uploads-confirmed --delete-original
python3 "$SKILL_DIR/scripts/finalize.py" "$JOB" --purge --uploads-confirmed --delete-original --apply
```

清理默认只接受当前工作区 `output/daily-video/` 的直接子目录；非默认位置需显式传 `--output-root`。保留原视频时省略 `--delete-original`。源 PDF、凭据、skill 和无关文件始终保留。

## 开发验证

在仓库根目录运行：

```sh
python3 -m unittest discover -s tests -v
```

测试使用临时合成媒体，不调用 ASR，不操作账号，不上传，不删除使用者的真实文件。技术测试不能替代每期字幕校对、音频审听与视觉检查。

本仓库仅包含通用指令、代码、合成测试和空凭据示例，不附带任何真实媒体、转写、平台截图、个人账号记录或历史任务。
