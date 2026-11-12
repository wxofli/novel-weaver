# Novel Weaver

让 Codex 帮作者构思、查资料、规划、写章与审查，并用**按书隔离、可追溯到原文的记忆**维持长篇连续性。创作由宿主模型完成；Python 核心只负责可靠的版本、事务、图记忆、检索、上下文与恢复，不额外调用一个写作模型。

正文先成为候选稿：自动保存、提取候选记忆、保存审查，随后等待作者明确采纳。采纳同一个具体版本时，正文和记忆一起提交，不再问一次“要不要记忆”。一句“想几个故事点子”只会得到点子，不会自动建书。

## 快速开始

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。在插件根目录运行：

```sh
uv sync --locked --extra dev
uv run --locked novelctl --help
uv run --locked novelctl book init --project "./作品/旧港" --title "旧港" --operation-id "init-old-port" --json
uv run --locked novelctl book status --project "./作品/旧港" --json
```

`book init` 返回新 `book_id`，并在目标目录建立 `.novel/project.json`、`.novel/memory.sqlite`，向该书的 `AGENTS.md` 追加工作约定。保留返回的真实 ID。所有写请求需要明确的 `project`、`book_id`、`operation_id`；初始化是例外，因为它创建书身份。

Windows PowerShell 可这样取得书身份再调用工具：

```powershell
$bookDir = (Resolve-Path -LiteralPath './作品/旧港').Path
$bookId = (Get-Content -LiteralPath (Join-Path $bookDir '.novel/project.json') -Raw -Encoding UTF8 | ConvertFrom-Json).book_id
uv run --locked novelctl book status --project "$bookDir" --book-id "$bookId" --json
uv run --locked novelctl context build --project "$bookDir" --book-id "$bookId" --task write --chapter 1 --query '沈青抵达旧港' --json
```

跨目录调用时，`uv run --project 插件根目录` 选择 Python 项目，`novelctl ... --project 书目录` 选择作品，二者含义不同。明确写出书 ID 可以防止目录和身份串用；核心会同时核对 marker 与数据库。

## 在 Codex 中安装

插件使用 Codex 兼容布局，包括 `.codex-plugin/plugin.json`、`.mcp.json`、`skills/` 与 `hooks/hooks.json`。在安装器已准备好依赖的插件目录，MCP 启动命令为：

```sh
uv run --project . --locked --no-sync --cache-dir .venv/.uv-cache novelctl mcp serve
```

MCP 从已安装的插件目录启动，需要能找到 `uv`。hooks 由标准库包装器启动，需要能找到 `python3`（Windows 为 `python`），优先使用插件 `.venv` 的 Python，缺失时仅尝试不安装依赖的离线 uv。运行环境需要能写入作者指定的书目录。

按[官方本地插件安装说明](https://developers.openai.com/plugins/build/plugins#install-a-local-plugin-manually)，可把整个插件放在一个工作仓库的 `plugins/novel-weaver/`，在该仓库 `.agents/plugins/marketplace.json` 合并以下条目，再重启桌面客户端，从 Plugins Directory 的对应本地来源安装：

```json
{
  "name": "local-novels",
  "interface": {"displayName": "小说工具"},
  "plugins": [{
    "name": "novel-weaver",
    "source": {"source": "local", "path": "./plugins/novel-weaver"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity"
  }]
}
```

路径相对于 marketplace 根目录。已有 marketplace 应合并条目，保留其他插件。通过界面安装后，在实际安装目录运行 `uv sync --locked` 准备依赖。源码更新后同步安装来源并重启客户端。生命周期 hooks 需要支持插件 hooks 的 Codex 本地宿主。

从开发工作区创建本地来源时，先用 `python scripts/package.py` 生成发布 ZIP，再解压到独立的干净目录并以该目录作为安装源。Codex 安装时会复制来源目录；直接指向含 `.cache`、`.venv` 或作者书稿的工作区可能占满磁盘或将不应打包的文件带入插件缓存。

安装后在 Codex 的 **Review hooks / Settings > Hooks**（CLI 为 `/hooks`）审阅并信任一次当前 hook 定义；更改定义或脚本后需重新信任。安装或启用插件不会自动赋予 hooks 信任。参见[官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks)。

## 作者如何使用

在书目录打开 Codex，自然表达目标即可，也可以显式调用对应 Skill：

| 请求示例 | Skill | 行为 |
| --- | --- | --- |
| “给我三个以旧港为背景的悬疑点子” | `novel-idea` | 讨论方案，不自动建书 |
| “查一下十九世纪港口检疫的资料” | `novel-research` | 有来源的参考笔记 |
| “把韩文小说的故事迁到中文网文背景” | `novel-adapt` | 编排选材、拆解、文化迁移、规划、试写与审校 |
| “规划下一卷，让沈青与船长决裂” | `novel-plan` | 计划与事实分离 |
| “继续写第 2 章，保持沈青的有限视角” | `novel-write` | 上下文、稿件、候选记忆与审查 |
| “检查这一章有没有提前泄密” | `novel-review` | 引文支持的审查记录 |
| “沈青到第 3 章知道谁是船主吗？” | `novel-memory` | 历史章与人物知情过滤 |
| “把这份旧稿导入，之后接着写” | `novel-import` | 预览映射、确认导入、顺序建记忆 |
| “现在这本书还有什么待办？” | `novel` | 项目状态与合适的下一步 |

`novel` 是通用路由入口，`novel-adapt` 是跨文化改编的专门编排入口：它按需读取上表中相关的子 Skill，携带来源、权利状态、用户决定和已生成材料，不需要一次加载全部 Skill。它也可以与当前环境中可用、且适合该步骤的其他 Skill 组合；这些 Skill 不改变 Novel Weaver 的身份、版本和采纳协议。调研和计划不能替代已发生的剧情，参考原作不能通过旧稿导入流程自动进入正史。

写作的实际闭环是：

1. `context_build` 构建该章上下文并返回新鲜 `context_id`。
2. `source_save(kind="chapter",logical_id="chapter:N")` 保存完整候选稿。
3. `source_get` 读回完整不可变源，模型提取有精确引文和偏移的 `MemoryDelta`，`memory_stage` 暂存。
4. 审查同一稿件，用 `source_save(kind="review",review=结构化Review)` 保存审查。
5. 进入 `awaiting_author`。作者“采用这一版”后，`source_accept` 同时绑定该 `source_version`、`batch_id`、`review_id` 与 `expected_revision`，提交正文与记忆。

正文只要再改一个字，就产生新版本，需要相应的新提取和审查。作者对旧稿的采纳不会转移给之后的稿件。作者尚未采纳时，自动化可以补齐提取/审查，不能替作者采用正文。

章节源与保存时的 `context_id` 绑定不可变。如果状态提示 `context.build` 或返回 `STALE_CONTEXT`，仅重建上下文不能让旧源恢复可采纳：须在新上下文中核对正文，再保存一个绑定新票据的章节版本，即使文字未改也如此，然后读新源、重新提取和审查，并按作者采纳边界提交。旧源不能重绑新票据，旧 batch/review 也不能借给新源。

## 记忆、检索与上下文

每本书独立保存实体与别名、双端关系或文本事实、事实生效/关闭章、故事内时间、角色/读者知情、伏笔状态和章节摘要。记忆不是一份不断覆盖的摘要：每个事实都有源版本、源哈希、原文引文与字符偏移。模型负责识别语义，核心严格验证引用与事务。

以下是合法的**章节增量** `MemoryDelta` 形状，假设源全文以 `沈青站在旧港。` 开头。`source_hash` 必须换成 `source_save/source_get` 返回的真实哈希：

```json
{
  "source_hash": "实际源SHA256",
  "entities": [{"id": "char:shen-qing", "name": "沈青", "kind": "character", "aliases": ["阿青"]}],
  "facts": [{
    "id": "fact:shen-qing:at-old-port:ch1",
    "subject": "char:shen-qing",
    "predicate": "位于",
    "value": "旧港",
    "certainty": "established",
    "valid_from": 1,
    "evidence": {"quote": "沈青站在旧港。", "offset": 0}
  }],
  "close_facts": [],
  "knowledge": [{
    "character": "reader",
    "fact": "fact:shen-qing:at-old-port:ch1",
    "state": "knows",
    "evidence": {"quote": "沈青站在旧港。", "offset": 0}
  }],
  "hooks": [],
  "summary": "沈青抵达旧港。"
}
```

fact 必须恰有 `object`（另一个实体 ID）或 `value` 其中之一。`offset` 是完整不可变源中从 0 开始的 Unicode 字符偏移，分页提取需加上页偏移；必须满足 `content[offset:offset+len(quote)] == quote`。章节增量中的状态变化关闭旧事实再添加新事实；推断使用 `certainty="candidate"`。`knows|believes|heard|rejects` 区分人物知情，`reader` 表示读者；事实成立不等于所有角色都知道。

旧信念持续到有证据的知情更新或 `rejects`，不随作者层事实变化自动消失；角色认识可以与当前作者事实不同。

`setting`/`decision` 使用该源全文的**完整声明快照**，不是章节增量或全书图快照。所有事实端点与知情角色引用的实体都必须在同一 delta 的 `entities` 中声明（`reader` 除外），即使实体已经存在；`knowledge.fact` 只能引用同一 delta 的 `facts`；`close_facts` 必须为空。其源章为 0，`valid_from` 省略或取 0。撤销旧断言须以原 `logical_id` 保存完整替代源、提取新快照再采纳，不能用另一个决定源关闭旧断言。

检索由本地中文分词、SQLite FTS5/BM25、证据图与可选语义向量组成。写第 N 章以 N−1 为历史界限。`scene_brief` 可传入本场目标、故事时间、作者约束和揭晓限制；可选的设定摘录、正文片段和风格样例按字符预算加入。显式指定 `pov` 的写作和修订使用该视角的知情记录，审查使用作者视图按需核实原文。模型还会看到聊天和主动读取的内容，有限视角工作流也应按相同的揭晓范围选取原文。

`graph_query.pov` 和 `context_build.pov` 必须传同书稳定实体 ID 或 `reader`，不通过角色名/别名解析，避免身份映射提前泄漏。不带 POV 的历史名字/别名查询只使用指定章已引入的字典。

检索范围明确分开：

- `canon`：已采纳正文。未采纳草稿不出现在正史检索中。
- `plan`：大纲、灵感、设定、风格与决定等材料。未来计划不是已发生事实，作者秘密也不是人物已知信息。
- `reference`：研究资料。外部事实不会直接进入剧情记忆。

修订或审查候选稿时，精确 `draft_id=source_version` 返回该稿的版本引用，正文由 `source_get` 分页读取。覆盖范围未到目标章时返回 `MEMORY_NOT_READY`。

## 导入、前文修订与设定替换

TXT/Markdown 导入先 `book import --mode preview`，展示分章映射并保留 `mapping_id`；作者确认后 `--mode start --mapping-id ...`。可指定编码或分章正则，默认按 UTF-8（含 BOM）再 GB18030 尝试。输入文件变动需重新预览；仅允许导入空书，避免覆盖已有章节。

确认导入会登记已采纳源，并创建一个冻结其版本清单的 sync job。修订已采纳前文会回退到相应前缀并重放后续源；替换已采纳 `setting`/`decision` 会撤回旧源声明，也可能从第 1 章重放全部已采纳正文。每次接受后检查响应 `job_id` 与 `book_status.active_job`，交 `novel-memory` 完成活动任务。每本书最多一个活动任务；它完成前冻结新的导入与采纳。

模型顺序执行 `memory_sync(next)` → `source_get` 全部分页 → 从原文提取 delta → `memory_sync(apply)`，一直到任务完成。不能跳章、并发重放、读 Markdown 替代不可变源，或直接复用依赖旧事实的后续 delta。导入、正文或设定/决定采纳已经授权这些已采纳源的记忆重建，无需再次逐章采纳或询问是否记忆。

中断后从 `book status` 返回的活动 `job_id` 和下一源继续；`memory_frontier` 表示可靠记忆覆盖到哪章。正文已登记而记忆未追上时，会报告进度与待办，不声称全部导入完成。

## 数据与恢复

书目录的主要内容：

```text
作品目录/
├── AGENTS.md
├── .novel/
│   ├── project.json        # 书 UUID 与 schema
│   └── memory.sqlite       # 权威源版本、采纳指针、证据图、账本、任务及派生索引
├── 草稿/                    # 精确候选版本的可读投影
├── 正文/                    # 已采纳正文投影
├── 大纲/                    # 已采纳计划材料的投影，按需生成
├── 设定/                    # 已采纳设定/风格/决定的投影，按需生成
├── 资料/                    # 已采纳研究材料的投影，按需生成
└── 灵感/                    # 已采纳灵感材料的投影，按需生成
```

数据库的不可变源版本是权威，Markdown 是可读、可编辑的投影。手改 Markdown 不会静默导入正史：先检查差异，有意修订再通过 `source_save` 保存新版本。数据库事务与文件落盘分开；文件被占用、权限或内容冲突可能留下 `partial`/投影待办，已提交的正文和记忆不会因此被假装回滚。投影写入使用临时文件与原子替换，冲突时保护用户手工内容。

用 `doctor check` 查健康、变动和投影待办，`doctor repair` 恢复可修复派生状态，`index status/update/rebuild` 管理索引。别直接编辑 SQLite 绕过版本和证据校验。备份时保留完整书目录，并使用一致的 SQLite 备份方式；正在运行的 WAL 数据库不宜只复制单个主文件。

## CLI 与 MCP 契约

全部 16 个业务操作共用 Python `novel_weaver.service.execute(action,payload)` 与 Pydantic 模型；MCP 直接调用核心，不启动 CLI 子进程。每个 MCP 工具只有一个有类型的嵌套 `request` 对象，例如：

```json
{"request":{"project":"/books/star","book_id":"book_实际ID","query":"沈青","scope":"canon","chapter":1}}
```

CLI 对应 `novelctl search --input request.json --json`，文件只放 `request` **里面的对象**。通用参数为 `--project --book-id --operation-id --run-id --input FILE|- --json`；只向支持该字段的请求传值。JSON 中未被显式 CLI 参数指定的值会保留，未知字段会拒绝。复杂内容用 UTF-8 JSON 文件或 stdin，避免 shell 引号损坏正文。

```sh
uv run --locked novelctl source save --input chapter-request.json --json
uv run --locked novelctl source get --input source-request.json --json
uv run --locked novelctl memory stage --input memory-request.json --json
uv run --locked novelctl source accept --input accept-request.json --json
```

每次写操作使用独立 `operation_id`；完全相同请求重试沿用原 ID，内容或参数变化必须新 ID。Hook 提供的 `session_id:turn_id` 原样用作支持字段的请求 `run_id`（写请求与 `context_build`），没有该字段的读取/初始化请求不额外传入。

响应含 `schema_version,status,book_id,revision,data,warnings,error,next_actions`。CLI JSON stdout 只有一个 envelope，stderr 为诊断；错误包含 code、message、retryable、exit_code。冲突需重读状态并重新构建对应候选，不能盲目重复旧 delta。`partial` 或还有记忆/索引/投影待办时应明确报告，成功保存不等于整个工作流完成。完整示例见 [Skill 公共协议](../skills/novel/references/workflow.md)，字段定义见 [schemas.py](../src/novel_weaver/schemas.py) 与[实现契约](implementation-contract.md)。

## 可选语义检索

没有向量服务也能使用图和 BM25。需要语义检索时安装可选依赖：

```sh
uv sync --locked --extra vector --extra dev
```

由用户选择并设置服务，不内置供应商、模型、推广链接或默认凭据：

| 环境变量 | 用途 |
| --- | --- |
| `NOVEL_EMBED_BASE_URL` | OpenAI 兼容嵌入 API 基地址，核心在其后加 `/embeddings` |
| `NOVEL_EMBED_MODEL` | 用户选择的嵌入模型 |
| `NOVEL_EMBED_API_KEY` | 可选 Bearer 密钥 |
| `NOVEL_RERANK_URL` | 完整重排 endpoint |
| `NOVEL_RERANK_MODEL` | 用户选择的重排模型 |
| `NOVEL_RERANK_API_KEY` | 可选 Bearer 密钥 |

配置嵌入后执行 `index update --embedding` 并给出书身份和操作 ID；改变服务、模型或维度时检查 profile 并重建。索引 profile 绑定服务、模型、维度与分块版本，不能把不同空间的向量混用。向量不可用时检索降级到图/BM25 并返回警告，不隐瞒语义检索未就绪。配置可选服务后会将对应文本发往用户指定的 endpoint；核心不会替用户选择服务或自动外发。

## Hooks

默认提供 `SessionStart`、`UserPromptSubmit` 和 `Stop`。它们读取最近作品的简要状态，跳过 Markdown 和索引扫描。`SessionStart` 给出作品身份和进度，压缩后也可恢复这些信息。`UserPromptSubmit` 提供本轮 ID、待作者采纳的版本或计划模式提示。

`Stop` 仅对本轮票据仍有效、只缺候选记忆或审查的草稿请求续跑一次。采纳由作者决定。导入、前文重放和中断恢复由对应 Skill 根据持久化任务处理。已自行配置 `PostToolUse` 的用户只会在本次修改了已跟踪的 Markdown 投影，或显式指定作品的 MCP 调用报告部分完成时收到提醒。

清单通过 `scripts/hook_runner.py` 启动处理器。包装器只用标准库，将 stdin 原字节传入子进程，并把子进程 `PYTHONPATH` 固定为插件 `src/`；优先运行 `.venv/Scripts/python.exe` 或 `.venv/bin/python -m novel_weaver.cli hook run EVENT`，缺失才尝试 `uv run --locked --offline --no-sync`，不下载 Python、不安装依赖、不更改书数据。超时、非零退出（包括 uv 的退出 2）以及无效或非 hook JSON 都转换为 stdout `{}`、退出 0，并在 stderr 诊断；只有成功子进程的有效 hook 输出会转发。外层 Python 本身缺失时宿主会标记启动失败，尚未启动的处理器不会写数据。Hooks 是工作流提醒，不是完整的权限或工具覆盖边界。

## 开发与验证

```sh
uv sync --locked --extra vector --extra dev
uv run --locked python -c "from pathlib import Path; Path('.cache').mkdir(exist_ok=True)"
uv run --locked pytest --basetemp .cache/pytest-local
```

CI 在 Windows/Linux 和 Python 3.11、3.12、3.13 运行锁定依赖的核心、CLI、MCP 和 hooks 测试。测试覆盖项目隔离、证据校验、上下文票据、采纳闭环、历史状态、导入重放、幂等及适配器；不要求外部模型密钥。MCP stdio 冒烟使用官方 SDK 客户端。

本地验收结果、合成基准与宿主安装边界见 [验收记录](verification.md)。

运行合成检索基准：

```sh
uv run --locked --extra vector python scripts/benchmark.py
```

默认固定生成 1000 章、200 万字符、5 万事实，源和事实直接装载以隔离检索测量，不代替写入、采纳与事务集成测试。报告输出到 `.cache/benchmarks/latest.json`；结果取决于机器与运行环境，不构成通用性能承诺。

生成本地插件发布包：

```sh
uv run --locked python scripts/package.py
```

产物为 `dist/novel-weaver-0.1.4.zip`。打包按发布文件白名单收集源码、Skills、清单与文档，不包含 `.venv`、缓存或作者书目录。

已有本地依赖时，也可 `python scripts/launch.py --help` 调试源码；它仅加载 `src/` 与可选 `.deps/`，不执行 pip 或下载。正式 MCP 使用 `uv` 和 `uv.lock`，hooks 使用上述标准库安全包装器。

当前导入格式为 TXT 和 Markdown。语义记忆与审查质量依赖宿主模型。Codex 安装、MCP 与 hooks 的实测范围见[验收记录](verification.md)。

## 调研参考

调研参考了 [Graphiti](https://github.com/getzep/graphiti)、[LightRAG](https://github.com/HKUDS/LightRAG)、[QMD](https://github.com/tobi/qmd)、[grit](https://github.com/bofeizhu/grit)、[InkOS](https://github.com/Narcooo/inkos)、[webnovel-writer](https://github.com/lingfengQAQ/webnovel-writer) 和 [ainovel-cli](https://github.com/voocel/ainovel-cli) 的记忆、检索及写作工作流思路。本项目独立实现共享核心与协议，没有直接复制这些项目的源码，也不把它们列为运行依赖。
