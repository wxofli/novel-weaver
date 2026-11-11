# Novel Weaver

[English](README.en.md) · [新手教程](docs/getting-started.md) · [技术文档](docs/advanced.md)

让 Codex 帮你构思、规划、写作和审查长篇小说，记住**哪些事已发生、谁知道什么、证据在哪一版原文中**。每本书独立保存资料；正文先存为候选稿，只有作者明确说“采用这一版”才进入正史并更新记忆。

**v0.1.0 是预览版。** 支持 TXT / Markdown 导入、本地证据记忆、检索和续写。写作与语义提取由 Codex 宿主模型完成；模型仍可能理解错误，请审阅候选稿。实际宿主安装与 hooks 激活的验证边界见[验收记录](docs/verification.md)。

## 安装

需要支持插件与 hooks 的 Codex、Python 3.11+、[uv](https://docs.astral.sh/uv/getting-started/installation/)，以及可访问 GitHub 和 Python 包源的网络。在下载或克隆的本项目根目录运行：

```sh
uv run --no-project python scripts/install.py
```

默认从 `wxofli/novel-weaver` 的 `v0.1.0` 标签注册来源，通过 Codex 安装插件，再在 **Codex 返回的实际安装目录**建立锁定环境并检查命令。标签发布前请用下述本地方式。加 `--dry-run` 可先查看计划。

使用解压后的 ZIP 或本地源码：

```sh
uv run --no-project python scripts/install.py --local .
```

完成后重启 Codex，在 **Settings > Hooks / Review hooks**（CLI 为 `/hooks`）审阅并信任当前 hooks；脚本变化后需要重新审阅。安装器不会自动信任 hooks、覆盖其他插件配置或删除作品。具体入口取决于 Codex 版本。

也可以把这段话复制给 Codex：

> 请帮我安装 https://github.com/wxofli/novel-weaver 的 v0.1.0 插件。先检查 Codex 和 uv，再按仓库 README 运行安装器，验证安装目录中的工具能启动，最后提示我审阅 hooks。如果我提供的是本地解压包，请使用 `--local` 加上该目录。

## 写第一本书

在专门存放作品的目录打开 Codex，说：

> 在这个目录新建一本叫《雾港来信》的悬疑小说，先给我三个故事方向，等我选定后再写第一章。

先选方向，再让 Codex 保存候选稿并审查。确认后说“采用刚刚审查的这一版”。下次说“继续写第二章，保持主角的有限视角”，插件会读取该书已有记忆。仅讨论点子不会自动建书。

导入旧稿可说：“先预览这份 TXT 的分章，等我确认后导入并建立记忆。”第一次可使用[原创示例](examples/雾港来信.txt)，具体步骤见[教程](docs/getting-started.md)。

## 数据与可选服务

每本书的 `.novel/memory.sqlite` 保存版本、记忆与恢复任务，`正文/`、`草稿/` 等目录提供可读稿件。备份整个作品目录；数据库使用 SQLite 一致性备份。不要把私密原稿、数据库、API 密钥提交到公开仓库。

默认图检索和中文关键词检索在本地运行，无需额外模型密钥。可选嵌入 / 重排服务由你选择；启用后会发送相应文本，见[可选服务说明](docs/advanced.md#可选语义检索)。

更新、卸载见[教程](docs/getting-started.md#更新与卸载)；卸载插件不会替你删除作品。开发、测试与 CLI 契约见[技术文档](docs/advanced.md)。欢迎通过 [Issues](https://github.com/wxofli/novel-weaver/issues) 提交可复现问题，贡献前请读 [CONTRIBUTING](CONTRIBUTING.md)。

[MIT License](LICENSE) · [更新记录](CHANGELOG.md) · [安全报告](SECURITY.md) · [第三方说明](THIRD_PARTY_NOTICES.md)
