# Changelog

## Unreleased

Changes after the 0.1.9 preview will be recorded here.

## 0.1.9 — 新作品自动生成精简创作约定

新建作品过去只写入工具协议与人称要求，创作模板需要手工合并。现在 `book_init` 会在作品根目录的 `AGENTS.md` 自动追加六条精简创作底线，让后续创作会话可以直接读取本书约定。

### 改动

- 先检查人物动机、选择、因果与后果，再调整场景详略与词句；对白服从身份、关系和当下压力。
- 清理重复解释与空泛升华，保护有效直述、心理、修辞、停顿与闲笔；不强制爽点间隔、章末悬崖、句长、禁词清零或删字比例。
- 去味保留剧情事实、伏笔、人物所知、揭露顺序与情绪承接；禁止靠新增微动作、粗话或后台核验仪式制造人味。
- 保留默认第三人称及作者明确指定的例外；采纳遵守作者已有授权与条件，自审不得冒称独立审查。
- 同步 skill 入口、作品约定说明和发布依赖检查，补充“重复升华应删、有效概述应留”的合成对照样例。

### 兼容与升级

- 仅使用新版运行时新建作品时自动写入；已有 `AGENTS.md` 作者文本保留，重复初始化不会重复追加。
- 已有作品不自动迁移；若希望补充旧书约定，需明确要求维护该作品。生成文件只是指导模型的规则，不是文学质量强制执行器。
- 工具请求字段、数据库结构与采纳事务保持兼容。发布不会自动安装或更新用户插件，不改写现有书稿或数据库。
- 发布附件提供插件 ZIP、Python wheel、源码包和 SHA-256 校验文件；安装或更新请按 README 操作。

### 验证

- 本地完整回归 171 项通过；锁文件、文档引用、插件打包及 wheel/源码包构建通过，确认 ZIP 与 wheel 均包含六条规则。详见本版本的[验证记录](https://github.com/wxofli/novel-weaver/blob/v0.1.9/docs/editorial-agents-init.md)。
- 对 C01–C13 合成样例进行了规则自审，保留慢场景、心理描写、有效直述和人物误判等边界。这不是盲评、独立文学审查或真实连载效果认证。

## 0.1.8 — Candidate snapshots and compact tool transport

- Remove automatic schema title annotations while preserving actual fields, literals and validation constraints.
- Persist disposable candidate-prefix snapshots with atomic cursor updates, corruption recovery and complete final evidence replay.
- Add an opt-in MCP summary text mode; keep complete structured results and retain full-text compatibility by default.
- Add an explicit bounded source-page cache for callers, snapshot/transport benchmarks and isolation/recovery tests. No installed plugin or book is updated automatically.
- Make the trace benchmark import its sibling analyzer by file path, including isolated Python processes launched outside the repository.

### 验证与收益

- 本地完整回归 169 项通过，包含仓库外隔离进程导入和新进程直接恢复快照而无需重放。10 个 skill 校验、文档引用和插件打包检查通过。
- MCP 工具声明由 55,503 降至 44,949 字符（减少 19.02%），保留字段和全部校验条件。
- 75 章、1,500 条事实的合成对照中，工具调用同为 216 次；增量应用 5,700 → 150 次，SQL 426,969 → 73,753 条，本地单次耗时 23.621 → 13.557 秒，最终五张记忆图表和正文哈希一致。轻负载不保证加速。
- 对 5,991 个历史结果模拟精简返回，序列化字符减少 46.62%；有界缓存模拟可减少 239 次读取。以上不是实际模型 token 或费用降幅。完整口径见[验证报告](https://github.com/wxofli/novel-weaver/blob/v0.1.8/docs/snapshot-transport-verification.md)。

### 兼容与升级

- 精简返回默认关闭。只有确认客户端消费完整 structuredContent 后，才显式配置 NOVEL_WEAVER_MCP_TEXT_MODE=summary；仅使用 text 的客户端继续使用默认 full。CLI 返回不变。
- 候选快照是按需创建的 revision_snapshots 派生表；与游标、增量同事务保存，失效可重建，提交和中止后清理。最终采纳仍完整重放，并保留版本、审查、证据与事务校验。
- 分页缓存仅供调用方显式使用，独立审查、版本变化、缺页或上下文丢失时仍须读取原文。活动 revision_batch 任务完成或中止前，不切换旧运行时。
- 发布不自动安装或更新已有插件，不改写任何小说项目；现有创作会话可继续使用原版本。

## 0.1.6 — Atomic batch revisions and leaner tool workflows

- Add resumable candidate batch revisions with ordered suffix extraction and atomic canon/memory commit; retain revision, context, review, hash and evidence checks.
- Add temporal entity ID resolution with ambiguity and conservative POV boundaries.
- Reduce repeat reads through explicit conditional source reads and bounded next-source content in replay responses.
- Advertise conditional input rules and a typed response envelope; return consistent, input-safe validation errors with actionable field/budget details.
- Add isolated transaction/regression tests, aggregate-only historical trace analysis and a synthetic replay benchmark. These source changes are not installed into existing book sessions automatically.

### 验证与收益

- 本地完整回归 146 项通过；10 个 skill 校验、文档引用和插件打包检查通过。
- 依据历史的 16 次修订顺序，在隔离合成的 75 章作品上运行真实接口：语义提取从 376 降至 75 章次（减少 80.05%），调用从 1,176 降至 141 次（减少 88.01%），最终正文哈希与事实图一致。
- 上述对照同时包含合批和减少往返，不代表真实创作的 token 费用或文学质量提升。候选校验内部仍会重建前缀；完整口径见 docs/optimization-verification.md。

### 兼容与升级

- 原单章工作流保持可用；批量流程复用现有存储，无数据库迁移。只有实际提供新 schema 的运行时才可调用新增工具和字段。
- 旧运行时不认识活动 revision_batch 任务；完成或中止该任务后再考虑降级。采纳授权、独立审查条件和证据校验继续保留。
- 发布不会自动安装、更新正在使用的插件或改写任何作品；已有创作会话可继续使用原版本。

## 0.1.5 — Writing, reading and editorial review

- Add a long-form reading skill with version coverage and separate reader-expectation notes.
- Expand writing and review guidance for scene value, repetition, voice, staged payoff and ending completeness; preserve genre differences and evidence/adoption boundaries.
- Add repository guidance, an optional book-instructions supplement, synthetic counterexamples and editorial validation. Runtime behavior, book initialization and hooks are unchanged; existing installed plugins and books are not migrated automatically.
- Document multi-source review, delegated adoption, context selection and batch revision as future backend work, not current API capabilities.

## 0.1.4 — Cross-cultural adaptation workflow

- Add a cross-cultural adaptation workflow that coordinates research, story planning, drafting and review while preserving source, rights, project and author-adoption boundaries.
- Route adaptation requests through the main novel entry and document how to combine it with other available skills.
- Clarify that local development installations should use an extracted release package to avoid copying workspace caches, virtual environments or manuscripts into the plugin cache.

## 0.1.3 — Third-person narration

- Default to third-person narration in samples, new drafts and revisions. Use a first-person narrator only where the author explicitly requests it. Dialogue, clearly marked direct thoughts and letters can use first person in character.
- Carry narrative person in the scene brief, correct unapproved shifts before saving, and cite the draft in review when narrative person changes unexpectedly.
- Include the same rules in `AGENTS.md` when initializing a book project.

## 0.1.2 — Scene context and lean hooks

- Add a scene brief for goal, story time, constraints and reveal limits. Drafting with an explicit POV uses that viewpoint's knowledge. Review uses author-level evidence and references the exact draft version.
- Keep the scene brief within the context budget and add optional evidence and style excerpts as space allows. Review, planning and query no longer write draft tickets.
- Ship three default hooks for session start, prompt submission and stop. Stop can only resume fresh candidate memory or review work from the current turn. Author adoption remains explicit.

## 0.1.1 — Codex desktop hooks

- Fixed an empty Hooks list in Codex desktop by packaging Novel Weaver with the Codex compatibility manifest. The installed plugin exposes all seven lifecycle hooks for review.
- Start MCP from the installed plugin directory using the environment prepared by the installer. Startup uses a cache inside that environment and skips dependency synchronization.
- Updated the installation and upgrade instructions. After upgrading, restart Codex and review the new installation in **Settings > Hooks**.

## 0.1.0 — Preview

First public preview: isolated book projects; immutable source versions; author adoption of reviewed drafts; quotation-backed graph memory; Chinese keyword search; optional vector search and reranking; TXT/Markdown import and sequential recovery; shared CLI/MCP core and lifecycle hooks.

Includes a portable Codex plugin, a pinned installer, original example manuscript, beginner guide and release checks. See [verification](docs/verification.md) for measured validation and host limitations.
