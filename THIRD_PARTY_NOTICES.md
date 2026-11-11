# Third-party notices

Novel Weaver's own code, documentation and original example use the MIT license in LICENSE. Dependencies retain their own licenses; this repository does not relicense them. The plugin ZIP contains project files and a lockfile, not dependency distributions. Package installers retrieve dependencies separately.

Direct dependencies: Pydantic, Model Context Protocol Python SDK (mcp), jieba, HTTPX and setuptools. sqlite-vec is optional; pytest and pytest-asyncio are development tools. Consult each installed distribution's metadata and license files, and uv.lock for the resolved transitive dependency inventory. Review those licenses when redistributing dependency binaries or modified distributions.

Research references include Graphiti, LightRAG, QMD, grit, InkOS, webnovel-writer and ainovel-cli (links in docs/advanced.md). They informed workflow research; their source code is not vendored in this project. References are not runtime dependencies or endorsements.
