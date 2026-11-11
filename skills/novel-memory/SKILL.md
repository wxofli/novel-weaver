---
name: novel-memory
description: 查询小说人物、关系、事实、时间线、角色知情与伏笔，提取有证据的记忆，或恢复导入、前文修订和设定替换后的同步。适用于“他当时知道吗”“伏笔还没收吗”“继续同步”；不把未采纳草稿当正史。
---

# 记忆查询与同步

先按[公共协议](../novel/references/workflow.md#调用与身份)读取 `book_status`，以 `memory_frontier` 为可靠覆盖边界。普通问答优先 `search(scope="canon",chapter=问题发生章)` 和 `graph_query(mode="entity"|"neighbors"|"path"|"timeline",entity=稳定ID,chapter=历史章,pov=需要时)`；邻接深度最多 2。名字可能有歧义时先消歧，不跨书合并同名人物。

图查询和 `context_build` 的 `pov` 只能传同书稳定实体 ID 或 `reader`，不能用角色名/别名解析，以免身份映射提前泄漏；不带 POV 的历史名字/别名查询只使用指定章已引入的字典。旧信念保留到知情更新或 `rejects`，角色可能仍相信与当前作者事实不同的内容。

回答携带可追溯的源版本和原文依据，区分事实、人物相信/听说/否认及未知。`scope="plan"` 是计划与约束，`reference` 是研究材料；两者不能证明剧情已经发生。查不到仅表示当前资料不足。工作稿只在显式精确 `draft_id` 的上下文中可见，不混入正史查询。

## 提取候选记忆

只从 `source_get` 读完的实际保存源提取，按[证据与记忆增量](../novel/references/workflow.md#证据与记忆增量)使用稳定实体/事实 ID、原文引文及全源字符偏移。章节增量中的状态改变关闭旧事实并建立新事实，不覆盖历史。`setting|decision` 则提取该源全文的完整声明快照：同批声明全部引用实体，知情仅指向本 delta 的事实，禁止 `close_facts`；撤销旧断言要替换原 `logical_id` 的完整源。`candidate` 事实与角色 `believes`/`heard` 不能当确定事实转述。作者秘密不自动成为角色或读者知情。

候选源用 `memory_stage` 暂存；它不改变正史。章节采纳须走 [novel-write](../novel-write/SKILL.md) 并绑定审查。作者已采用的设定/决定可用同样的 stage/accept 提交。不要从普通闲聊、研究或未来大纲构造正史 delta。

## 恢复一个活动同步任务

读取[同步与恢复](../novel/references/workflow.md#同步与恢复)。只处理 `book_status.active_job` 给出的 `job_id`，一次一个源，顺序不可并行：

1. `memory_sync(mode="next",job_id=活动任务)` 取得 `next_source_version`、哈希与章节。
2. `source_get` 读取该不可变源的全部分页，保留全源偏移；不要读投影，不从摘要推断缺失原文。
3. 模型根据当前已重放状态提取该源的完整 `MemoryDelta`，核实证据、实体引用与历史关系。
4. `memory_sync(mode="apply",job_id,source_version=刚取得的源,base_revision=当前revision,delta)`；使用新的操作 ID，保留响应 revision，然后读取状态/下一源。
5. 直到任务完成，确认 `memory_frontier` 追上目标并检查索引/投影待办。中断后从同一任务的下一源恢复，不重新启动导入或重新采纳章节。

导入确认或正文/设定/决定采纳已经授权这些已采纳源的记忆重建，不另问一次“要不要记忆”，也不逐章重问作者采纳。设定/决定替换可能从第 1 章重放全部正文，每次接受后都检查 `job_id` 与 `book_status.active_job`，不要只处理导入和旧章修订任务。活动任务冻结新的导入与采纳；如果原文/manifest 改变、版本冲突或证据失败，保持已提交进度，报告具体错误并读取状态恢复，不绕过校验。

索引和 Markdown 是派生状态。按授权用 `index_update`/`index_rebuild` 与 `doctor_check`/`doctor_repair` 恢复；可选向量配置必须由作者提供，不能擅自选择供应商、上传文本或虚报向量已就绪。
