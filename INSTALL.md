# 给智能体的安装入口

用户把仓库网址交给你并要求安装或更新时，读取并执行 [完整安装规程](daily-article-video/references/INSTALL.md)。它覆盖识别当前宿主、安装依赖、安全配置 ASR 和验证，不限定某种 agent。

实际安装器：`daily-article-video/scripts/setup.py`。核心工作流：`daily-article-video/SKILL.md`。

完整安装规程也会随 skill 安装到 `references/INSTALL.md`，复制后可继续查阅；ASR 配置指南在相邻的 `references/ASR_SETUP.md`。使用者的登录、服务开通和密钥填写仍须由本人完成。

已有同名安装时，执行完整规程中的“已有安装的更新”，同步 `main` 的最新版本；不要直接重跑拒绝覆盖的安装命令。
