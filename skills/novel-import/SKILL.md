---
name: novel-import
description: 把作者已有的 TXT 或 Markdown 小说导入 Novel Weaver，预览分章映射，逐章重建证据记忆以便接着写。适用于“导入旧稿”“接着这本小说写”；先确认映射，不覆盖非空作品。
---

# 导入既有正文

导入只接受作者指定的本地 TXT/Markdown 文件。确认目标项目为空；需要新作品时仅按作者明确给定的标题与目录 `book_init`。已有书的修订走 [novel-write](../novel-write/SKILL.md)，不能借导入覆盖。

按[公共协议](../novel/references/workflow.md#调用与身份)调用 `book_import(mode="preview",files=明确文件列表,encoding=必要时,split_rule=必要时)`。保留 `mapping_id`，向作者展示检测到的编码/分章结果、章序、标题、前后片段，特别标明序言、错分或无标题整稿。默认尝试 UTF-8（含 BOM），再尝试 GB18030；自定义分章使用正则，不猜测未知编码。

先让作者确认具体映射及导入范围，再 `book_import(mode="start",mapping_id=该预览, mapping=仅在作者修正映射时传入)`。mapping 每项为 `{title,content,chapter}`，章号必须从 1 连续。输入文件内容变动后重新预览，不使用旧的确认。

导入启动会把确认的正文登记为已采纳版本，并返回冻结的活动 `job_id`；这时正文登记与记忆完成是不同状态。立即按 [novel-memory](../novel-memory/SKILL.md) 的 next → 完整 source_get → 模型提取 → apply 循环逐章同步。已确认的导入不再逐章要求采纳或另问记忆授权。

同一本书只运行一个同步任务；活动任务期间不新启动导入或采纳。故障/中断后读取状态并恢复原任务，不重新导入。报告已经登记的章数、可靠 `memory_frontier` 与剩余任务；同步、索引或投影仍待处理时不能称导入全部完成。

完成后才根据作者后续要求构建写作上下文。导入正文不等于授权自动续写下一章或改写旧文。
