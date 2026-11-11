---
name: novel-review
description: 审查小说具体稿件的连续性、人物动机、知情边界、时间线、伏笔和语言问题，提供有原文依据的修改意见。适用于“检查这一章”“有没有吃设定”；审查不等于作者采纳，也不自动重写正文。
---

# 正文审查

先明确具体 `source_version` 与审查目标。本轮已完整读取且 ID、哈希一致时，复用原文；否则通过 `source_get` 翻页读到 `next_offset=null`。工具格式见[公共协议](../novel/references/workflow.md#调用与身份)。作者只粘贴一段文字要求建议时，直接审查该段。

在当前项目用 `context_build(task="review", chapter=N, draft_id=仅限被审的精确版本, query=审查目标)`，按需用 `search`、`graph_query(chapter=相应历史边界,pov=相关角色稳定ID或reader)` 核实。图查询和上下文的 POV 不解析名字/别名；不带 POV 的历史名字查询也只按当章已引入字典解析。审前文时不能把后续已发生信息当成当时人物已经知道的事；人物旧信念在知情更新或 `rejects` 前可能与作者事实不同，不直接判作连续性错误。未采纳候选仅作该稿工作覆盖层。

先检查作者指定的层面。综合审查时先看场景目的、因果、动机和信息揭晓，再看节奏、句子和作者声音。用作者层证据独立核对原文和人物知情，把确定的连续性冲突、需要作者判断的问题和审美建议分开。

每条 finding 使用 `severity="info"|"warning"|"critical"`、具体 `message` 和必要的原文 `quote`。引文逐字取自目标源；拿不准就说明证据不足。结构化 `Review` 必须含该章精确的 `source_version` 和 `source_hash`。在项目内需要保存审查或为正文闭环审查时，调用 `source_save(kind="review", logical_id=稳定审查ID, content=可读报告, review=该对象)`，保留返回的 `review_id`。

告诉作者最值得处理的问题及其影响。审查完成后不自动修改、不自动采纳。作者要求修订时走 [novel-write](../novel-write/SKILL.md)，并为新稿重新提取和审查；若作者已经明确采纳当前稿，则按该 Skill 的精确版本采纳流程提交，不再询问记忆授权。
