---
name: novel-write
description: 在 Novel Weaver 作品中写下一章、续写场景或修订现有正文，自动构建上下文、保存稿件、提取候选记忆并审查。适用于“继续写第几章”“修改这一章”；正文须经作者明确采纳才进入正史。
---

# 正文创作与修订

读取[公共协议](../novel/references/workflow.md)的“调用与身份”“写章与采纳”“证据与记忆增量”。先锁定项目、章节、任务范围和作者的具体修改意图，不把要求续写一章扩成自动写整本书。按 `book_status` 处理已有活动同步任务，记忆未覆盖所需章节时先完成已授权同步。

## 每个正文新版本的固定闭环

1. 调用 `context_build(task="write" 或 "revise", chapter=N, query=本章目标, entity_ids=相关稳定ID, pov=需要时的同书稳定实体ID或reader)`，保留返回的 `context_id`。上下文与图查询的 POV 不接受名字/别名解析，避免身份提前泄漏。修改具体候选稿时，仅用它的精确 `draft_id=source_version` 开工作覆盖层。不得自动混入其他未采纳稿件。
2. 在该上下文内写作。尊重作者约束、已确立事实、人物动机与知情边界。涉及新人物、规则、关系、时间状态或伏笔时，先用 `search`/`graph_query` 查重与核实；只有查无对应项后才引入一致的候选。检索不足时保留不确定性，不编造“数据库已有设定”。
3. 用 `source_save(kind="chapter", logical_id="chapter:N", chapter=N, context_id=刚取得的票据, content=最终正文)` 保存完整新版本。编辑既有稿时带 `expected_source_hash`。记录返回的 `source_version`、`source_hash` 和当前 revision；`run_id` 原样传入。
4. 对这个版本调用 `source_get`，读完所有分页，直至 `next_offset=null`。从实际保存的原文提取 `MemoryDelta`；证据 `quote` 必须与原文逐字匹配，`offset` 是完整源中从 0 开始的字符偏移。随后 `memory_stage(source_version, base_revision=当前revision, delta)` 并记录该版本的 `batch_id`。
5. 审查同一完整原文与相关上下文，按 [novel-review](../novel-review/SKILL.md) 的标准生成结构化 `Review`，再通过 `source_save(kind="review", review={source_version,source_hash,findings,summary}, content=可读审查报告)` 保存。记录返回的 `review_id`；口头审查不能替代此步骤。
6. 检查状态，向作者交付正文/位置、审查重点和候选状态，进入 `awaiting_author`。作者尚未明确采纳时停止，不调用 `source_accept`。本轮的保存、提取与审查无需逐项询问授权，也不要要求作者先确认是否更新记忆。

任意正文改动都产生新版本：重新构建必要上下文、保存、读取、提取和审查。旧 `batch_id`、`review_id`、哈希不能挪给改后的稿件。

若章节票据过期（`STALE_CONTEXT` 或状态要求 `context.build`），旧源绑定的 `context_id` 不可修改。只调用新的 `context_build` 不够：核对新上下文后，即使文字不变也要 `source_save` 一个绑定新票据的章节版本，再读新源、重新 stage 和保存审查，按作者采纳边界提交。不能给旧源换票据或继续使用旧 batch/review。

## 作者采纳后

作者“采用这一版”“这章定稿”等明确对应当前具体稿件的指示，授权采纳该稿及其记忆。读取当前状态，调用 `source_accept`，一次提交精确的 `source_version`、`batch_id`、`review_id`、`expected_revision`；自动更新记忆，不再问“是否记忆”。如果该源已被后来的稿件替代，说明版本差异并回到对应稿件流程，不把作者对旧稿的采纳外推给新稿。

每次接受后检查响应 `job_id` 与 `book_status.active_job`，有任务就转 [novel-memory](../novel-memory/SKILL.md) 顺序重放已采纳正文；前文章节修订和设定/决定替换都可能触发重放，不再要求逐章采纳。继续本轮已授权的索引更新与投影恢复；如果网络、冲突或作者输入使流程暂停，说明已完成到哪一步、保留哪些精确 ID 及待办。`partial` 或仍有同步/索引待办时不要声称全部完成。
