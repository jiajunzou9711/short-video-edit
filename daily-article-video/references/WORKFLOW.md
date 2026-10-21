# 每日口播视频工作流

入口：聊天中给视频路径，可附 PDF 路径。当前 agent 执行 ASR、源文校对、剪停顿、字幕烧录、视频帧标题封面、平台文案、小红书发布前准备和视频号手动上传交付。

发布边界：只准备并上传至最后发布前的界面，绝不自行点击发布；状态使用 awaiting_user_publish。发布需用户明确放行本次视频。 小红书须填好标题、摘要/正文、正式非活动话题和适用声明，自主选择相关的已发布视频作为引用链接，并加入最合适的一个已有合集；核对封面小图、原创声明和未关联任何活动，保留页面供用户最后点击发布。没有相关视频/合集或真实信息不足时如实说明，不虚构，不添加无关组件。具体操作标准见 skill 执行第5步。

不是独立无人值守 daemon：字幕校对、文案和实时网页操作由当前 agent 完成；脚本负责可重复的媒体处理。不需要额外 LLM API key。

本 skill 使用相对目录：`scripts/` 存放媒体处理与清理脚本。执行时将 `<skill-dir>` 替换为安装目录，输出目录位于当前工作区。所有 `<venv-python>` 使用安装器返回的虚拟环境 Python 绝对路径。

## 执行

```sh
<venv-python> <skill-dir>/scripts/pipeline.py prepare /绝对路径/video.MOV output/daily-video/本期名
# Agent 读转写、核对 PDF、审听疑句，写 editorial.json
<venv-python> <skill-dir>/scripts/pipeline.py render output/daily-video/本期名
<venv-python> <skill-dir>/scripts/pipeline.py check output/daily-video/本期名
```

依赖：Python 3.10+/Pillow、FFmpeg/ffprobe；PDF 提取可使用 pdftotext。HDR 封面的原生 SDR 导出另需 macOS 15及以上、可运行 Swift 的开发工具链（AVFoundation/AppKit）以及 Pillow 的 ImageCms 色彩管理支持；操作见“封面表情与色彩”。ASR 使用豆包语音录音文件识别极速版接口和 `~/.config/volc.env`，可用 VOLC_RESOURCE_ID 覆盖资源配置。凭据由使用者自行配置，不能把真实凭据、请求转写或输入媒体提交到仓库。

## editorial.json

所有 caption 和 cut 使用**原视频秒数**，输出字幕由脚本统一映射至剪后时间。caption 不得与删除区间相交。文字和时间由 agent 基于词时间戳校对后填写，不是 ASR 自动结果直接发布。

```json
{
  "reviewed": true,
  "source_evidence": [{"pdf": "/原始文章.pdf", "pages": [12, 13], "checked": "人名、术语与数字"}],
  "review_notes": ["实际更正与仍存在的不确定项"],
  "cuts": [[5.2, 6.3]],
  "captions": [{"start": 0.3, "end": 2.1, "text": "本期实际口播内容"}],
  "cover_title": "简短内容标题",
  "cover_time": 1.0,
  "annotation_y_fraction": 0.54,
  "annotations": [{"start": 38.37, "end": 49.8, "title": "下丘脑视前区", "english": "preoptic hypothalamus", "text": "位于下丘脑前部，参与体温及生殖行为调节。本研究发现，其中一群小鼠神经元可能参与胚胎着床。", "checked_sources": ["对应原文及核查来源"]}],
  "platforms": {
    "xiaohongshu": {"title": "发布标题", "description": "正文", "tags": ["科普知识"]},
    "wechat_channels": {"title": "发布标题", "description": "正文", "tags": ["科普"]}
  }
}
```

`render`先生成并校验全部字幕/解释框叠加帧与封面（布局冲突在编码前报错），再一次编码生成video.mp4，另生成cover.jpg、subtitles.srt、publish.json和含editorial.json哈希的render-check.json；`check`生成qa-check.json、work/qa-contact-sheet.jpg、小红书发布文案.txt和视频号发布文案.txt。editorial.json、源文校对说明及最终publish-status.json由agent完成；source.json及ASR/候选剪切文件由prepare生成：pause-candidates.json列出字级≥0.9秒停顿及声学静音重叠秒数，suggested-cuts.json只含声学确认的剪切。每次 render 都重置两平台发布状态，并移除旧质检与文案记录；编码失败也不能沿用旧记录。重新运行 check 并核对、上传本次成片后再更新发布状态。render 初始化的发布状态是占位状态，不代表已上传或已完成手动交付，须在页面核对后更新。

封面独立上传，不插入视频开头。work/存放制作缓存与检查帧；两平台上传成功且用户回来说“清理”后，连同成品及所有记录删除。

## 制作参数

- 字幕、cuts及annotations均使用原视频秒数，由render统一映射。每期检测长停顿：约1秒以上作为候选，与声学静音和ASR无口播区间交叉核对，按上下文决定剪除，两侧通常各留0.2秒；保留呼吸与强调，不能截词。
- 术语解释包含中文、english、1–2个完整句子及checked_sources；源文优先校核术语和科学表述，长英文自动另起一行。annotation_y_fraction默认0.54（胸前起点），caption_y_fraction默认0.69，按构图调整；需顶部布局时显式写0.035。竖屏字幕进入底部25%平台UI区、解释框与字幕相压、超出画面或解释框时间重叠时，render报错。逐帧检查脸部、解释框与底部字幕。
- 解释框以正常手机尺寸下清晰可读为优先：字号和整体尺寸适当放大，背景增加一点透明度；允许轻微遮到脸部，避免大范围遮脸。不为完全避开低头时的下巴而持续缩小标注。先调整位置、精简解释和断行，再按构图调整 `annotation_scale`；不能与字幕相压或侵入平台UI区。
- 当前实现：`annotation_scale` 默认1.0，控制解释框字号和尺寸；背景透明度仍在 `pipeline.py` 的 `draw_overlay` 中固定为alpha 210/255（约82%不透明），尚无 `editorial.json` 配置项。后续调整背景透明度需要修改渲染样式并重新检查成片，不能仅填写一个未实现的参数就声称已生效。
- 两平台共用一个视频与cover.jpg（1080×1440、3:4、标题上方水平居中、两侧留白避开发布时间提示和右上角播放按钮）。cover_font_fraction默认88/1080，cover_y_fraction默认66/1440；面板与文字水平居中，宽度随标题调整。标题尽量避开脸，按构图调整。3:4为默认封面比例，居中布局须核对实际平台小图，避免与播放按钮重叠。

## 封面表情与色彩

封面单独检查两项：

- **表情**：从多个候选帧选择自然瞬间，优先正视镜头、眼睛睁开、嘴部平稳；排除眨眼、口播中扭曲嘴形、夸张手势、运动模糊。不要只按默认 `cover_time` 或第一帧交付。看原尺寸，也看实际平台小图，检查标题和播放按钮是否遮挡人物。
- **色彩**：与原片在正常支持HDR的播放器中播放时对照肤色、衣服和背景，排除发白、发灰、过曝和异常偏色。不加美颜、滤镜或审美调色；不能拿另一张同样错误解码的抽帧作为原片色彩基准。平台“封面质量通过”不替代人工检查。

已验证的 macOS HDR 封面操作：`AVAssetImageGenerator` 设置 `appliesPreferredTrackTransform = true`、精确帧时间容差为零，macOS 15及以上使用 `dynamicRangePolicy = .forceSDR`，通过 `NSBitmapImageRep` 导出保留ICC的PNG。以下一次性代码存放在本期 `work/`，输出也放本期目录；不要依赖已清理期次的脚本或图片：

```swift
import Foundation
import AVFoundation
import AppKit
// swift extract.swift <原视频绝对路径> <输出PNG绝对路径> <原视频秒数>
let asset = AVURLAsset(url: URL(fileURLWithPath: CommandLine.arguments[1]))
let generator = AVAssetImageGenerator(asset: asset)
generator.appliesPreferredTrackTransform = true
generator.requestedTimeToleranceBefore = .zero
generator.requestedTimeToleranceAfter = .zero
if #available(macOS 15.0, *) { generator.dynamicRangePolicy = .forceSDR }
let time = CMTime(seconds: Double(CommandLine.arguments[3])!, preferredTimescale: 600)
let image = try generator.copyCGImage(at: time, actualTime: nil)
let png = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:])!
try png.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
```

该PNG可能使用Display P3等ICC。用Pillow的 `ImageCms.profileToProfile` 按源 `icc_profile` 转到sRGB，再裁成1080×1440、添加原有标题并保存JPEG；保存时传入sRGB的 `icc_profile`。不要直接丢弃ICC后把原有RGB数值当成sRGB，否则仍可能偏色。若没有ICC或原生导出不可用，先确认源色彩空间，使用可正确处理HLG/PQ的等效色彩管理工具，再与原片对照；不能靠手动调整亮度、对比度或饱和度猜回颜色。

当前 `pipeline.py make_cover` 仍使用普通FFmpeg抽帧，不能视为HDR封面已经正确转换。未修改视频及字幕时，可在render/check后单独替换封面，无需重编码整段视频：保留旧版为本期work中的过期稿，将验收通过的新版同步到共用 `cover.jpg`，更新封面路径/hash、实际上传文件路径及检查记录；视频hash和音频检查结论保持实际状态。若修改了 `editorial.json`，仍按原有规则重新render/check。仅重新运行render会覆盖单独替换的封面，需要重新核对。

上传新封面后，核对平台小图使用的确为新帧、色彩正常、文字清晰；检查原创声明、正式非活动话题、合集、引用笔记和未关联活动状态，保存最新截图及publish-status.json。两平台继续共用同一张新版 `cover.jpg`，不改动原片色调。

## 成片检查与日常用量

`pipeline.py check <本期目录>`完整解码、核对时长和音轨存在性，并抽取开头/中段/结尾、每个解释框及每处剪切前后画面，生成拼图及带最终视频hash的qa-check.json。必须查看拼图和封面；疑点或文字过小时再看原尺寸帧/短片段。音轨存在不等于审听通过，技术检查不等于视觉通过。只在文件未改变时复用检查结果/hash；editorial.json在render后变化时check直接拒绝。HDR（HLG/PQ）输入：当前视频编码路径未实现HDR到SDR的色调映射，输出为带HDR标记的8-bit，须在平台预览核对色彩。上一节的原生SDR导出仅用于封面，不能据此认定视频也已完成转换。

日常按skill执行，需要字段时读schema、遇故障才读对应段落，不重复读取历史、脚本或全部ASR JSON。完整转写、相关文章、科学核查与疑点审听仍保留；只按需读取字级时间戳片段。长日志写work/，工具返回摘要。

先统一校对再渲染/上传，修改或缺陷只重查受影响部分，视频变化后重新完整解码。上传按进度间隔观察，不密集读取相同页面。代码不变时不重复开发回归测试，每条成片质量检查仍执行。

## 交付与清理

更新publish.json最终视频路径；publish-status.json记录实际上传文件SHA-256、标题/正式话题、引用笔记、所选合集、声明状态、未关联活动及awaiting_user_publish状态，保存最终页面截图。视频号记manual_upload_ready，保留具体交付路径，生成视频号发布文案.txt。

交付：“小红书已上传准备好，你可以点击最后的发布”；附本地文件夹、最终视频、共用封面与视频号文案链接。不得把准备完成说成已公开发布。必须提醒：“两边上传发布成功后，回来告诉我‘清理’，我会删除本期全部本地生成产物和原视频。”此时不执行自动清理。

用户之后说“清理”即确认两平台上传成功并要求删除本期产物及对应原视频（若明确有平台没成功，则保留）。脚本按source.json记录的路径与SHA-256核对原视频后与本期目录一并删除；哈希不符则全部不删。明确要求保留原视频时去掉 `--delete-original`：

```sh
<venv-python> <skill-dir>/scripts/finalize.py output/daily-video/本期名 --purge --uploads-confirmed --delete-original
<venv-python> <skill-dir>/scripts/finalize.py output/daily-video/本期名 --purge --uploads-confirmed --delete-original --apply
```

删除整个本期输出目录，包含最终视频、全部封面、字幕、文案、缓存、工作文件及全部记录；不留本地备份。检查目录已不存在。验证对应原视频已删除；保留原PDF、凭据、skill、流程代码和无关资料，平台作品不动。原视频删除必须依据source.json准确路径及内容核对，不使用通配符。工作流和skill不随单期清理删除。脚本拒绝范围外目录和包含原片/PDF的目录。

旧模式（无--purge）仅删中间文件，保留成品；不满足当前“全部产物清除”要求，新流程交付阶段不调用其--apply。

## 验证命令

```sh
python3 -m unittest discover -s tests -v
```

媒体测试验证合成媒体的剪切时间映射、字级停顿候选、字幕/解释框渲染与布局拒绝、render后改稿的check拒绝；清理测试验证清理必须有上传确认、预览不删除、实际清理完整删除、原视频哈希核对删除及原文件/目录边界保护。测试不调用ASR或上传平台。真实新视频仍须检查疑似剪切、字幕与封面预览。

## 浏览器故障与声明

登录检查先复用已有创作页，或从已登录主页读取“发布”链接并进入完整地址。后台根地址的登录页不足以判定会话失效，不同入口可能采用不同认证或跳转逻辑。应使用主页实时提供的发布入口。正式入口加载后仍明确要求认证，才请用户处理登录。

小红书正式话题需选平台下拉候选，直接粘贴#文字不一定是正式话题；平台自动关联活动时取消并核对。每期核对实时登录账号。上传失败时按实际错误和所用浏览器工具的文件上传文档诊断，不假定曾经的权限或登录状态仍然有效。替换视频可能重置原创声明，重新声明若要求同意平台须知则按工具协议确认要求处理。

## 安装目录与输出边界

脚本不写入 skill 安装目录。通常从媒体工作区运行，使用 `output/daily-video/<本期名>`；清理脚本默认只处理当前工作区该目录的直接子目录。如输出在别处，显式传入 `--output-root <已核对的输出父目录>`。不要仅为绕过边界检查而传入宽泛根目录。

默认字体为 macOS 系统中文字体。其他系统需设置 `DAILY_VIDEO_FONT`、`DAILY_VIDEO_CARD_FONT` 为支持中文的真实字体路径，并重新检查布局。

## 多段输入的边界

`prepare` 接收一个源文件，不会自动合并视频。若任务需要多段，agent 先核对输入顺序、音轨、旋转和编码参数，再在本期范围内拼接，保留全部原件。每个原片路径与 SHA-256 必须单独记录。当前清理脚本只处理 `source.json` 的单个 `path`，不会自动删除多个原片；不能把删除拼接文件说成多个原片已清理。多段清理须先核对全部原片及生成文件的准确路径和哈希，按用户授权的范围处理；有一项不匹配则不开始删除。

## 首次安装和 ASR 配置

从 [安装规程](INSTALL.md) 进入；使用 scripts/setup.py 安装并以返回的 Python 执行处理。配置字段、凭据存储和在线验证见 [ASR_SETUP.md](ASR_SETUP.md)。本地 doctor 检查通过不等同于真实转写服务已验证。
