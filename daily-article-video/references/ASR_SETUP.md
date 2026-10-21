# 语音转文字：首次配置与验证

当前脚本接入火山引擎/豆包语音的录音文件识别极速版 HTTP 接口。它会将音频发给该服务，可能计费。无需另配 LLM API；字幕校对由当前 agent 执行。

## 开通与字段

使用者在自己的豆包语音控制台开通录音文件识别极速版，并取得该服务的鉴权凭据。控制台入口可从[官方文档](https://docs.volcengine.com/docs/DoubaoVoice/recording-file-recognition-lite-http?lang=zh)进入；登录、实名、支付或协议由使用者自行完成。

支持两种配置，推荐新版：

| 模式 | 本地字段 | HTTP 请求头 |
| --- | --- | --- |
| 新版 API Key | `VOLC_API_KEY` | `X-Api-Key` |
| 旧版应用鉴权 | `VOLC_APP_ID` 和 `VOLC_ACCESS_KEY` | `X-Api-App-Key` 和 `X-Api-Access-Key` |

旧版 `VOLC_ACCESS_KEY` 在这里指豆包语音的 Access Token，不是云账号通用 AK/SK。若两种都配置，优先使用新版 API Key。空值和 `YOUR_…` 占位符不会被视为已配置。参考[官方旧版鉴权说明](https://docs.volcengine.com/docs/DoubaoVoice/old-version-console-authentication-reference-example?lang=zh)。

默认 `VOLC_RESOURCE_ID=volc.bigasr.auc_turbo`，对应极速版；标准版的资源 ID 与调用流程不同，不能随意混用。以使用者实际开通的服务和[官方模型列表](https://docs.volcengine.com/docs/DoubaoVoice/model-list?lang=zh)为准。脚本只实现极速版同步端点，不自动切换服务商或资源。

## 安全填写

优先运行安装后的 `scripts/setup.py configure-asr`，在本机交互终端隐藏输入凭据。也可在本地私密编辑器创建配置文件，示例字段见仓库 `.env.example`。不要把真实值粘贴到 agent 聊天或命令参数中。

默认文件为 `~/.config/volc.env`；可通过 `VOLC_CONFIG_FILE` 指向仓库外的其他本机文件。支持安全注入的 `VOLC_*` 环境变量；同名环境变量优先于文件。安装器拒绝覆盖已有文件，不修改使用者原来的服务配置。

字体环境变量也需要在后续处理进程中可见；仅在某个终端设置一次不代表所有 agent 进程都能继承。由当前宿主按其支持的方式注入环境或记录非敏感路径，不把密钥写入公开 skill。

## 两级检查

1. `setup.py doctor`：本地检查 Python、Pillow、FFmpeg、字体和凭据存在性。不调用 API，不能证明认证或额度有效。
2. `setup.py verify-asr --audio <短音频> --allow-upload`：在使用者授权后调用接口，检查转写结果和有效字级时间戳。最多 30 秒，只输出状态；不打印密钥和转写，临时文件离开命令时删除。

账号未开通或权限不足时，让使用者检查录音识别极速版的授权；认证失败先核对凭据种类及资源，不重复提交长视频。网络失败检查联网状态；字级时间戳缺失则尚未达到本工作流要求。凭据存在、接口成功和字幕准确分别是不同检查，不互相替代。
