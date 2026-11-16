# Changelog

## Unreleased

Changes after the 0.1.6 preview will be recorded here.

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
