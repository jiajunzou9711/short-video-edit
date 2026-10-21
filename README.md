# short-video-edit

一个用于 2–15 分钟中文口播、杂志或论文解读视频的通用智能体 skill：转写、逐条校对、剪长停顿、烧录字幕、添加术语解释框、制作共用封面、准备平台文案，并把小红书页面准备到最后发布前。视频号提供手动上传文件。

这是 **agent 配合脚本** 的工作流。脚本负责媒体处理；原文核查、疑句判断、视觉检查和浏览器填表由当前 agent 完成。不是无人值守发布工具。

## 把这个网址交给你的智能体

复制下面这句话给你自己的 agent：

> 请读取 https://github.com/jiajunzou9711/short-video-edit ，按 INSTALL.md 为当前智能体安装并配置这个视频剪辑 skill，检查依赖，并引导我在本机安全配置语音转文字 API。需要登录、开通服务或填写凭据时提示我操作；不要让我把密钥发到聊天中。在线音频测试前先说明上传和费用并取得授权。

**给 agent 的入口：[INSTALL.md](INSTALL.md)。** 它包含获取文件、识别宿主技能目录、隔离安装依赖、ASR 配置、本地诊断和短音频验证的完整步骤。安装助手为 `daily-article-video/scripts/setup.py`，不是下载后自动执行的远程 shell。

流程使用通用 Markdown 指令和本地脚本。具有本地文件、命令执行和联网能力的智能体可以执行；支持 `SKILL.md` 的宿主装入自己的技能目录，其他宿主可读取指令并调用脚本。平台上传还需可操作的浏览器和使用者登录态；纯聊天界面不保证能在电脑上安装或操作网站。

### 最关键：语音转文字

支持新版豆包语音 API Key，也支持旧版 App ID + Access Token。安装向导使用隐藏输入，在仓库外保存本机配置；[ASR 指南](daily-article-video/references/ASR_SETUP.md)解释开通、字段和验证。真实凭据不包含在仓库中，也不需要发给 agent。

安装助手的几个命令：

```sh
python3 daily-article-video/scripts/setup.py install --skills-dir /path/to/agent/skills
# 后续使用安装器返回的虚拟环境 Python 和实际 skill 路径：
<venv-python> <installed-skill>/scripts/setup.py doctor
<venv-python> <installed-skill>/scripts/setup.py configure-asr
# 使用者明确授权上传该短音频及可能费用后：
<venv-python> <installed-skill>/scripts/setup.py verify-asr --audio /path/to/sample.wav --allow-upload
```

依赖为 Python 3.10+、Pillow、FFmpeg/ffprobe 和中文字体。安装器将 Pillow 放进 skill 自己的虚拟环境；FFmpeg 和字体由 agent 按当前系统检查并补齐。默认 macOS 中文字体；其他系统需配置字体并验证渲染。HDR 原生封面导出使用 macOS 15+ / Swift，其他系统需可用的等效色彩管理方案。

`doctor` 不发送音频；在线转写验证会发送音频到豆包语音，可能计费。账号注册、登录、服务开通、支付和凭据填写不能靠仓库网址自动完成；agent 会在这些步骤提示使用者操作。

## 使用

安装完成后，向你的 agent 提供视频路径，可附源文章路径。支持技能调用的宿主可调用 `daily-article-video`；其他宿主先读取 `SKILL.md`。例如：

> 按 daily-article-video 处理这个口播视频，校对字幕，剪掉长停顿；小红书停在最终发布前，视频号给手动上传文件。

从你的媒体工作区执行脚本；`SKILL_DIR` 指向安装后的 `daily-article-video` 文件夹，`JOB` 指向本期输出目录：

```sh
SKILL_DIR="/path/to/installed/daily-article-video"
PYTHON="/path/to/installed/daily-article-video/.venv/bin/python" # Windows 使用安装器返回的解释器路径
JOB="output/daily-video/example"
"$PYTHON" "$SKILL_DIR/scripts/pipeline.py" prepare /path/to/input.MOV "$JOB"
# Agent 阅读完整转写、核对原文和疑句，然后填写 editorial.json。
"$PYTHON" "$SKILL_DIR/scripts/pipeline.py" render "$JOB"
"$PYTHON" "$SKILL_DIR/scripts/pipeline.py" check "$JOB"
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
"$PYTHON" "$SKILL_DIR/scripts/finalize.py" "$JOB" --purge --uploads-confirmed --delete-original
"$PYTHON" "$SKILL_DIR/scripts/finalize.py" "$JOB" --purge --uploads-confirmed --delete-original --apply
```

清理默认只接受当前工作区 `output/daily-video/` 的直接子目录；非默认位置需显式传 `--output-root`。保留原视频时省略 `--delete-original`。源 PDF、凭据、skill 和无关文件始终保留。

## 开发验证

独立首次安装的验收指标、实测结果及未验证范围见 [VALIDATION.md](VALIDATION.md)。

在仓库根目录运行：

```sh
python3 -m unittest discover -s tests -v
```

测试使用临时合成媒体，不调用 ASR，不操作账号，不上传，不删除使用者的真实文件。技术测试不能替代每期字幕校对、音频审听与视觉检查。

本仓库仅包含通用指令、代码、合成测试和空凭据示例，不附带任何真实媒体、转写、平台截图、个人账号记录或历史任务。
