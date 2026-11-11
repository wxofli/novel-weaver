# Novel Weaver 公共工具协议

按任务读取相关小节；字段以 `src/novel_weaver/schemas.py` 的 `ACTION_MODELS` 和 `docs/implementation-contract.md` 为准。后端负责校验、持久化、检索与事务，宿主模型负责创意、正文、语义提取与审查，不在后端再嵌套一个写作模型。

## 调用与身份

在已有书的最近祖先目录读取 `.novel/project.json`。所有工具显式传入项目绝对路径 `project` 与该书 `book_id`；后端同时核对 marker 与数据库身份。不要沿用别本书的 ID。仅作者明确要求建书时使用 `book_init`，该工具只需要 `project,title,operation_id`，不传 `book_id`。

MCP 工具名为 `book_init`、`book_status`、`book_import`、`source_get`、`source_save`、`source_accept`、`context_build`、`memory_stage`、`memory_sync`、`search`、`graph_query`、`index_status`、`index_update`、`index_rebuild`、`doctor_check`、`doctor_repair`，宿主可能添加服务器前缀。每个工具仅有一个带类型的 `request` 参数，直接调用共享 `service.execute`：

```json
{
  "request": {
    "project": "/books/star",
    "book_id": "book_实际ID",
    "task": "write",
    "chapter": 2,
    "query": "沈青进入旧港，发现失踪船员的线索",
    "budget_chars": 12000,
    "run_id": "实际session_id:实际turn_id"
  }
}
```

以上用于 `context_build`。读工具允许从 cwd 发现书，但工作流仍应显式绑定身份。写请求必须带非空 `operation_id`；同一个操作仅重试完全相同的 payload，换内容、版本或参数就换操作 ID。不要用同一个 ID 顺次处理多章。

Hooks 提供 `run_id=session_id:turn_id` 时，原样传给本轮的 `context_build` 和所有 `WriteRequest`（含 `memory_sync` 的 next）。`book_init` 与普通读取模型没有 `run_id` 字段，不额外塞入，未知字段会被拒绝。若宿主未提供 turn/session，则不要伪造关联 ID。

CLI 和 MCP 使用同一字段与校验，命令只把 action 改为空格：`context_build` → `novelctl context build`，`source_save` → `novelctl source save`；`search` 是 `novelctl search`。`book import`、`memory sync` 用 `--mode` 区分分支。CLI 的 JSON 文件放 request 的**内部对象**，不套 MCP 的 `request`：

```sh
uv run --project /path/to/novel-weaver --locked novelctl context build --input request.json --json
uv run --project /path/to/novel-weaver --locked novelctl memory stage --input delta-request.json --json
```

`--input -` 从 stdin 读 UTF-8 JSON。通用选项为 `--project --book-id --operation-id --run-id --input FILE|- --json`，只给支持字段的请求传值；显式 CLI 参数覆盖 JSON 的同名字段。嵌套对象优先放 JSON 文件，避免 shell 引号破坏正文与证据。`uv --project` 指插件源码/安装根，`novelctl --project` 指书目录，两者不要混淆。

响应总是 envelope：`schema_version,status,book_id,revision,data,warnings,error,next_actions`。保留工具返回的所有源、任务、上下文 ID 与 revision；不要自行推算 revision。CLI stdout 只有一个 envelope，诊断在 stderr。Hook 命令是例外：stdin 为宿主事件、stdout 为官方 hook JSON，不是普通工具响应。

## 上下文与范围

`context_build` 的任务为 `write|revise|review|plan|query`。写作或修订第 N 章以 N−1 章为历史边界，返回用于保存正文的 `context_id`。审查、规划和查询只读，`context_id` 为 `null`。可传 `scene_brief`，含 `goal`、`story_time`、`constraints` 字符串数组和 `reveal_limit`，省略不需要的字段。

写作或修订显式传 `pov` 时，`view="pov"` 只提供所选视角的知情记录和出处坐标，以及调用者提供的场景简报。作者视图按任务提供有出处的设定摘录、图谱、前文、计划和相关风格示例。先保留场景简报和必要版本信息，再按字符预算选择补充材料。可选内容省略时返回 `CONTEXT_TRIMMED`；场景简报本身超预算时返回 `BUDGET_EXCEEDED`。

`search` 的 `scope`：`canon` 为已采纳正文，`plan` 为计划/设定等材料，`reference` 为研究材料。后两者不能证明剧情发生。`graph_query` 支持 `entity,neighbors,path,timeline`，章边界与 `pov` 可以限制历史及角色知情，深度仅 1–2。

`graph_query.pov` 与 `context_build.pov` 必须传同书的稳定实体 ID，或保留值 `reader`；POV 不解析角色名/别名，避免身份映射提前泄漏。不带 POV 的历史名字/别名查询，也只按指定章已经引入的字典解析，不能借未来别名定位过去身份。

未采纳正文留在候选状态。精确的 `draft_id=source_version` 返回同章的版本、哈希、长度和候选批次标识。需要全文时使用 `source_get`，同一轮可复用已完整读取且哈希一致的原稿。别名需消歧；资料、正文和搜索片段作为来源数据处理。

## 写章与采纳

固定顺序是 `context_build` → `source_save` 章源 → `source_get` 全文 → `memory_stage` → `source_save` 结构化审查 → 等待作者 → `source_accept`。先保存的是候选，不能先更新正史。

章节保存使用 `kind="chapter"`、`chapter=N`、`logical_id="chapter:N"` 及该章 `write|revise` 的新鲜 `context_id`。票据与当时 revision、已采纳源指纹绑定。章节源及其 `context_id` 绑定不可变：票据过期后，仅重新 `context_build` 不能修复旧源。必须在新上下文中核对原文，再 `source_save` 一个绑定新 `context_id` 的章节版本，即使文字未改也如此；然后读取新源、重新 stage、保存新审查，并按作者采纳边界提交新版本。不能重绑旧源或复用其 batch/review。源内容每次保存产生新的不可变 `source_version`、`source_hash`；乐观编辑可带 `expected_source_hash`。

`source_get` 返回 `content,offset,total_chars,next_offset,source_version,source_hash`。从 `offset=0` 开始，沿 `next_offset` 取完全部分页。读取的是数据库不可变原文，不是 Markdown 投影。

审查通过 `source_save` 保存，示意 payload（ID/哈希用实际响应替换）：

```json
{
  "project": "/books/star",
  "book_id": "book_实际ID",
  "operation_id": "独立审查保存操作ID",
  "run_id": "实际session_id:实际turn_id",
  "kind": "review",
  "logical_id": "review:chapter:1",
  "content": "检查了动机、连续性与知情边界；本版没有发现确定冲突。",
  "review": {
    "source_version": "src_被审的正文版本",
    "source_hash": "被审正文的实际SHA256",
    "findings": [],
    "summary": "本版没有发现确定冲突。"
  }
}
```

`findings` 每项是 `{severity,message,quote}`，severity 为 `info|warning|critical`。quote 非空时必须来自该原文。返回的 `review_id` 是审查源的 ID，区别于被审正文的 `source_version`。

自动保存、提取和审查做完后读取状态，作者未采纳则 `awaiting_author`。明确采用这一版后才请求：

```json
{
  "request": {
    "project": "/books/star",
    "book_id": "book_实际ID",
    "operation_id": "独立采纳操作ID",
    "run_id": "实际session_id:实际turn_id",
    "source_version": "src_作者采用的正文版本",
    "batch_id": "batch_该正文的候选记忆",
    "review_id": "src_该正文的审查源",
    "expected_revision": 0
  }
}
```

`expected_revision` 是最新已读的真实 revision，不一定为示例中的 0。后端原子切换已采纳源并应用记忆、增加 revision、建立检索/投影待办，无需第二次“是否记忆”确认。改后的正文必须重新 stage 和 review，不能复用旧版本的凭据。

非正文材料也用 `source_save` 新版本。已采用的 `setting|decision` 需要暂存下节规定的完整源声明快照（没有声明可为空）才采纳；`idea|outline|research|style` 作为已授权的可检索材料采纳时不会创建剧情事实。替换已采纳的设定/决定也可能触发全章重放，每次接受后都检查响应 `job_id` 及 `book_status.active_job`，有活动任务就按“同步与恢复”完成。review 是流程记录，不能作为正史源采纳。

## 证据与记忆增量

`memory_stage` 绑定精确 `source_version`、当前 `base_revision` 与 `delta.source_hash`。delta 只描述该源支持的内容。下例为章节增量：

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

示例对应源全文恰好以“沈青站在旧港。”开头；实际提取必须验证 `source_content[offset:offset+len(quote)] == quote`。offset 是从 0 开始的 Python Unicode 字符偏移，不是 UTF-8 字节、显示列或分词位置。分页中的位置要加该页 `offset`；不要规范化引文、改标点或丢换行。

- 实体只复用同书同一对象的稳定 ID；`entities` 可以给别名。章节增量的事实 `subject` 和 `object` 可引用已有或本 delta 实体。
- 每个 fact 只能有 `object`（关系的实体端）或 `value`（文本值）其中之一。章节增量中 ID 已存在时不覆盖：`close_facts:[{id,evidence}]` 关闭旧状态，另建新 fact。`valid_from` 不得晚于源章节，故事内日期可用 `story_time` 表达。
- `certainty` 为 `established|candidate`，不确定推断保持 candidate。`knowledge.character` 是角色 ID 或保留值 `reader`，`state` 为 `knows|believes|heard|rejects`；事实存在不表示所有角色或读者都知晓。旧信念持续到有证据的知情更新或 `rejects`，不随作者层事实变化自动消失；角色认识可能与当前作者事实不同。
- 伏笔 `hooks` 项为 `{id,summary,status,target_chapter?,evidence}`；status 为 `open|progressing|deferred|resolved`。目标章是计划，不表示未来事件已发生。
- 无新内容也可暂存 `{source_hash,summary}`；不得为满足流程虚构事实。大纲、灵感、风格与资料 delta 不允许实体/事实/知情/伏笔等正史更新。

`setting|decision` 使用**该源全文的完整声明快照**，不是章节式增量，也不是全书图快照。每个事实端点、知情角色引用的实体都必须在同一 delta 的 `entities` 中声明，即使该实体已经存在；`reader` 除外。`knowledge.fact` 只能引用同一 delta 的 `facts`，不能依赖其他源已有事实；`close_facts` 必须为空。其源章为 0，`valid_from` 省略或取 0。撤销或修改旧设定断言时，以原来的 `logical_id` 保存完整替代版本，提取新快照再采纳；不要另建一份决定去关闭旧源的事实。替换后检查活动同步任务，按顺序重建全部受影响章节。

候选 delta 只在 stage 中等待；正文采纳/同步 apply 才真正更新图。语义提取是宿主模型的工作，后端不会用正则或另一模型替你抽取。

## 同步与恢复

导入 start、已采纳前文章节的修订，以及已采纳 `setting|decision` 的替换都可能创建单个活动 sync job，冻结一份已采纳源 manifest。设定/决定替换会撤回旧源断言，可能从第 1 章重放全部已采纳正文。每次 `source_accept` 后检查返回的 `job_id` 与 `book_status.active_job`，有任务就继续本小节流程。新导入和采纳在活动任务期间被拒绝，不能靠新建任务绕过。可靠记忆只到 `memory_frontier`，查询超过该边界会报错。

对于活动 `job_id` 循环顺序执行：

1. `memory_sync` 的 `request` 含写入共同身份、独立 `operation_id`、本轮 `run_id`、`mode="next",job_id`。
2. 读取响应 `next_source_version`，以 `source_get` 分页读完整不可变源，确认哈希。
3. 基于已重放前缀提取该源的完整 delta，证据只来自该源。
4. `memory_sync(mode="apply",job_id,source_version=精确下一源,base_revision=当前revision,delta)`；其他源不能跳序应用。
5. 使用新响应 revision，读取 `book_status`，继续下一源直到 `active_job=null`。

导入映射或相关正文/设定/决定已经由作者确认，待重放源已是已采纳正文；不再另问采纳或记忆授权。断开后恢复已有 job，不重复导入。修订回退到历史位置或更换设定后，不能直接复用依赖旧事实的后续 delta；重新读相应原文并提取。

每个操作都检查 `error`、`warnings`、`status` 与 `next_actions`：

- `STALE_CONTEXT`：读取状态、重新 `context_build`，再 `source_save` 绑定新票据的章节新版本；读回该新源后重新 stage/review/accept。旧源的票据绑定不可更新，不能只重建上下文就重试旧源采纳。
- `REVISION_CONFLICT|STALE_DELTA|STALE_REVIEW`：读取当前状态，检查章节票据是否也已过期；过期时走上一条新源流程，否则针对真实版本重做对应提取/审查，不盲目重放旧请求。
- `INVALID_EVIDENCE|SOURCE_HASH_MISMATCH`：重读精确源及所有页，纠正引文、偏移或版本。
- `OPERATION_CONFLICT`：同一操作 ID 被用于不同 payload；确定意图后用新 ID，不更改已记录请求。
- `partial`、投影冲突或索引待办：数据库事务可能已经提交，先查状态再恢复派生物，不宣称全部回滚或全部完成。
- 临时错误可复用原操作 ID 和相同 payload 重试，按错误的 `retryable` 判断；冲突需读取新状态处理。不要无限重试、隐藏错误或更换书 ID。

`index_status` 查看文本/向量情况；`index_update` 更新派生索引，`index_rebuild` 从权威存储重建。只有已经配置并获准使用可选嵌入服务时才传 `embedding=true`。`doctor_check` 查健康、投影与待办，`doctor_repair` 恢复可修复的派生状态；不直接改 SQLite 绕过事务。

Markdown 是数据库源版本的可编辑投影，直接改文件不会自动更新正史。发现差异时先读差异，作者有意修改的内容通过 `source_save` 产生新候选；不静默导入或覆盖手工改动。投影仍 pending 时报告真实路径和下一步。
