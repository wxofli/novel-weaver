# Contributing

欢迎提交问题和小范围改进。请在 Issues 说明场景、预期、实际结果、平台和复现步骤，删去原稿、数据库、个人路径与密钥。较大功能先讨论范围。

需要 Python 3.11+ 和 uv：

```sh
uv sync --locked --extra dev --extra vector
uv run --locked python -c "from pathlib import Path; Path('.cache').mkdir(exist_ok=True)"
uv run --locked pytest --basetemp .cache/pytest-local
uv run --locked python scripts/package.py
```

测试不需要外部模型密钥。为事务、身份校验、证据、恢复与安装失败补充有意义的测试，保持 CLI/MCP 共用核心，不提交作者作品和生成缓存。修改版本时同步 pyproject.toml、plugin.json 和 src/novel_weaver/__init__.py，更新 CHANGELOG；打包会验证三处版本一致。

PR 请说明具体问题、改动后行为和验证结果。贡献按本项目 MIT 许可提供。交流遵守[行为准则](CODE_OF_CONDUCT.md)，安全问题见 [SECURITY](SECURITY.md)。
