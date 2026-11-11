---
name: novel-review
description: 审查小说具体稿件的连续性、人物动机、知情边界、时间线、伏笔和语言问题，提供有原文依据的修改意见。适用于“检查这一章”“有没有吃设定”；审查不等于作者采纳，也不自动重写正文。
---

# 正文审查

先明确具体 `source_version` 与审查目标。已保存稿件通过 `source_get` 读取完整不可变原文，翻页直到 `next_offset=null`；不以 Markdown 投影、搜索摘要或曾经显示的旧稿替代。工具格式见[公共协议](../novel/references/workflow.md#调用与身份)。作者只粘贴一段文字要求建议时，先完成所请求的段落审查，不为此擅自建书。

在当前项目用 `context_build(task="review", chapter=N, draft_id=仅限被审的精确版本, query=审查目标)`，按需用 `search`、`graph_query(chapter=相应历史边界,pov=相关角色稳定ID或reader)` 核实。图查询和上下文的 POV 不解析名字/别名；不带 POV 的历史名字查询也只按当章已引入字典解析。审前文时不能把后续已发生信息当成当时人物已经知道的事；人物旧信念在知情更新或 `rejects` 前可能与作者事实不同，不直接判作连续性错误。未采纳候选仅作该稿工作覆盖层。

重点检查和任务有关的内容：因果与动机是否成立，时间与能力是否一致，角色或读者是否无依据获知秘密，伏笔是否有证据，叙述视角是否稳定，语言是否符合作者指定风格。把确定冲突、可能问题与审美建议分开；不以模板分数替作者判断。

每条 finding 使用 `severity="info"|"warning"|"critical"`、具体 `message` 和必要的原文 `quote`。引文逐字取自目标源；拿不准就说明证据不足。结构化 `Review` 必须含该章精确的 `source_version` 和 `source_hash`。在项目内需要保存审查或为正文闭环审查时，调用 `source_save(kind="review", logical_id=稳定审查ID, content=可读报告, review=该对象)`，保留返回的 `review_id`。

告诉作者最值得处理的问题及其影响。审查完成后不自动修改、不自动采纳。作者要求修订时走 [novel-write](../novel-write/SKILL.md)，并为新稿重新提取和审查；若作者已经明确采纳当前稿，则按该 Skill 的精确版本采纳流程提交，不再询问记忆授权。
