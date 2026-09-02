# 核心记忆容量、路由与 Fact 日期规格

Status: Ready

## Problem

当前核心记忆模型把全部动态页面放进同一个 100 页额度，并在启动时注入完整 Route Catalog。随着 `people/` 等分区增长，启动上下文会持续膨胀，Agent 也无法按分区取得有界、可预测的路由信息。

页面和 Fact 的写入边界也不一致：动态页只有 8000 字符软提醒，Profile 另有 300 字符特殊硬限制，单 Fact 可达 4096 字符，页面超限后没有可安全完成拆分的单次操作。结构损坏时，读操作要么被其他分区牵连，要么缺少可由 Agent 安全执行的机械修复路径。

此外，Fact 没有日期，使用者无法判断一条记忆最后一次实际新增或更新的时间；现有 `observed` 和隐私写入规则又把可记录范围限制得过宽，无法覆盖用户希望 Agent 主动收集的、可见且长期有用的人物信息。

## Outcome

完成后，启动上下文只携带固定 Home Pages 和三个动态分区的产品级说明；Agent 按需对 `topics`、`areas` 或 `people` 单独调用 `list`，每次获得该分区全部页面的 `path + description + aliases`。

Agent 写入受到清晰、统一且可计算的页面数、页面字符、Fact 字符和批量大小限制。动态页超容量时，Agent 可在不删除、不截断、不依赖 Store 语义匹配的前提下，优先复用现有页面，必要时通过一次 `move` 创建新页面并原样转移 Facts。只有目标分区已满且无法复用现有页面时才需要用户整理。

新建或实际更新的 Fact 在 Markdown 行尾保存 Store 生成的本地 ISO 日期；旧的无日期 Fact 继续兼容读取，不迁移、不补写虚假日期。结构上可唯一确定的机械问题可由 Agent 调用现有 `update` 自动修复，其他问题明确失败并通知用户。

## Scope

### 路由与启动注入

- 保留 `profile.md` 与 `preferences.md` 作为 Home Pages，并在支持的会话边界注入其 Facts 与 version。
- 不再在启动时注入动态 Route Catalog。
- 启动上下文只额外注入 `topics`、`areas`、`people` 三个分区的固定产品说明，以及按需调用 `list` 的提示。
- 分区说明属于产品合同，不来自用户可编辑的 Markdown。
- `list` 必须显式接收 `scope=topics|areas|people`；不支持 `all`、query、匹配、排序参数、分页、cursor、after 或 limit。
- 一次 `list` 返回指定分区全部直属动态页，按 canonical path 字典序排列。
- 成功响应保持最小形状 `{status, files}`；每项只包含 `path`、`description`、`aliases`，且 `aliases` 即使为空也必须返回 `[]`。
- `list` 只扫描和验证目标分区。其他分区或固定页的损坏不阻塞本次调用；目标分区任一结构无效页面使整个调用失败，并返回准确 path、原因和恢复提示。

### 页面数量与路由元数据

- Agent 增长页面数时按目标分区分别执行硬上限：`topics=50`、`areas=50`、`people=100`。
- 上限计算的是页面数，不是人物数；同一个人可因稳定主题需要拥有多个 `people/` 页面。
- create、创建新目的页的 move、跨分区 rename 都必须检查目标分区额度；分区内 rename 不增加计数。
- 已有或人工产生的超额分区仍可 list、read、修改、重命名和删除；只阻止继续增加该分区页面数的操作。
- 目标分区达到上限时返回 `capacity_exceeded`，包含 `scope`、`current`、`limit`、`message`、`recovery`。Agent 不重试，不误报为格式错误，并向用户说明需要整理该分区。
- 删除跨页面 name/alias 全局唯一约束。canonical path 仍全局唯一；同页 aliases 仍去重，且不能等于该页 name。
- 不同页面允许相同 name 或 alias。Agent 根据 description 和读到的 Facts 消歧；无法确定时询问用户。
- Agent 创建页面或更新页面元数据时，规范化后的 description 最长 80 个 Unicode 字符，aliases 最多 6 个。
- alias 单项和合计不设独立字符上限，path/stem 不新增字符上限；仍遵守现有 canonical lowercase kebab-case 和文件系统边界。
- description 与 aliases 的新上限只约束 Agent create 或相关页面元数据更新。既有更长 description 或 7–8 个 aliases 可读取；Doctor 可警告，下一次相关元数据更新必须收敛。

### 页面与 Fact 容量

- `profile.md` 和 `preferences.md` 的 Agent 写入后规范化完整页面上限均为 2000 个 Unicode 字符。
- 所有动态页的 Agent 写入后规范化完整页面上限均为 5000 个 Unicode 字符。
- 页面上限按最终渲染文本计算，包含 frontmatter、basis、格式字符和 Fact 日期。
- 单 Fact 的新写入 `content` 上限为规范化并 trim 后 800 个 Unicode 字符；basis、格式字符和日期不计入 800，但会计入页面总量。
- `update.old_fact`、`move.facts` 与 `delete.fact` 是已有 Fact 的精确选择器，不是新内容；它们继续接受最多 4096 字符，以便整理或精炼兼容读取的旧 Fact。
- 删除 Profile Fact content 合计 300 字符的特殊限制。Profile 与其他页面使用相同的单 Fact 上限和 basis 行为，只由页面准入语义决定写什么。
- 不设置独立的每页 Fact 数量上限。
- 不截断超长内容。新候选超过 800 时，Agent 将其拆成可独立维护的 Facts，或保留在项目 Authority 而不写入核心记忆。
- 既有页面或 Fact 超过新上限仍可读取。减少超限页面内容的 mutation 可执行，即使结果仍暂时超限；不得继续增长已有超限页面。
- 固定页 mutation 会导致超过 2000 时拒绝。Agent 向用户展示容量、拟写 Fact 和可选精炼方案；固定页不自动拆分、转移、重写或删除。
- 动态页 mutation 会导致超过 5000 时先拒绝原 mutation，由 Agent 组织页面后再基于最新 Page Snapshot 重试。
- 动态页只有在被 Agent 修改时才整理；启动、list、read 和后台任务不得触发写入。Doctor 只报告，不修改。
- 对已超 5000 的动态页，即使本次只修改 description 或 aliases，也必须先整理至新合同允许的状态。

### 动态页自动整理

- “自动”表示 Agent 可在无需逐次询问用户的情况下编排既有 Tools；Store 不执行语义匹配，不决定 Fact 属于哪个页面。
- Agent 先调用目标分区 `list`，依据 `path + description + aliases` 选择候选，再 read 候选页确认。优先转移到已有的语义合适页面；只有没有合适页面时才创建新页。
- Agent 可在 Facts 明确符合另一个分区语义时跨分区整理，否则留在原分区。任何新页面都必须检查目标分区额度。
- 同一人物的主页面保存身份、关系与核心 Facts；扩展页面使用稳定主题命名，例如 `people/<name>-work.md`，不得使用无语义的 `part-1`、`part-2`。
- 扩展现有 `move`，使一次操作可以携带 `new_path + description + aliases` 创建目的页并移动准确 Facts；不新增第九个公开 Tool。
- 原有目的页模式继续使用 `destination_path + destination_version`。新目的页模式与原有模式在 schema 中互斥。
- Store 在全局锁内预检源 version、目标路径、页面数量、元数据、Fact 与最终页面容量。
- 跨文件提交保持“目的页先写、源页后写”。发生部分提交时允许 Facts 暂时重复，不能丢失 Facts，并返回现有 partial-commit 证据。
- 自动整理只原样转移 `{basis, content, date}`，不摘要、不截断、不重写 Fact 内容。
- 整理后源页至少保留一个 Fact，自动流程不得整页删除。若全部 Facts 应迁走，Agent应改用 rename/页面更新表达新语义，或取得用户当前轮明确授权后再 delete。
- 只有目标分区已经达到自身上限、且没有可复用页面时，Agent 才停止自动整理并提醒用户。

### Fact basis、人物准入与隐私

- Fact basis 继续只有 `stated|observed`。
- `stated` 表示用户明确陈述；`observed` 覆盖 Agent 从当前可见材料直接归纳或推断的内容。
- 所有页面使用相同 basis 规则，Profile 不再限制为 stated-only；页面只按各自语义限制写入内容类别。
- 一份充分的当前证据即可支持 observed，不要求重复次数、置信度、推断理由、来源引用、provenance 或时效字段。存在明显不确定或冲突时不写。
- 推断出来的 Fact 必须以 `observed` 明示；不新增独立的 inference basis。
- 当前用户明确陈述优先：observed 可升级为 stated；stated 不得被冲突的 observed 自动覆盖或降级。用户当前陈述可更新旧 stated Fact。
- Agent 应主动为已提供或当前可见材料中可观察到详细信息的人收集长期记忆。只有姓名或一次性提及不足以创建页面；至少有一条除姓名外、稳定、未来有用的 Fact 才创建人物页。
- 隐私排除只覆盖真正会直接危及账户、身份或资产的秘密和完整标识，以及用户明确要求不要记住的内容，包括密码、API key/token、私钥、恢复码、完整支付卡号、完整证件号、完整账户标识。
- 不因健康、财务、政治、宗教、家庭或关系主题本身一概禁止写入；仍须满足页面语义、稳定性、证据和用户当前指令。

### Fact 日期

- 新规范 Fact 行为 `- [stated|observed] <content> [YYYY-MM-DD]`，日期必须位于行尾。
- 日期表示 Fact 最后一次实际新增或更新的宿主机本地日历日期，不表示页面修改时间、证据发生时间或有效期。
- Store 在一次顶层 mutation 进入全局锁后读取一次本地日期，并用于该批次所有新建或实际更新的 Facts。
- Agent 的公开 Tool 输入仍只包含 `basis + content`，不得提交或修改日期；Fact 身份与重复键仍是 `basis + normalized content`，日期不参与匹配。
- create/add 为新 Fact 写当天日期。`update(target=fact)` 在 content 或 basis 确实变化时写当天日期；完全相同的替换是 no-op，不改日期。
- `observed → stated` 属于 Fact 更新并写当天日期；stated 自动降级仍禁止。
- move、自动拆分、repair、rename 和页面元数据更新完整保留已有日期；通用 renderer 不得给无日期 Fact 自动补日期。
- `read` 的每个结构化 Fact 固定返回 `basis`、`content`、`date`；新 Fact 的 date 为 `YYYY-MM-DD` 字符串，旧 Fact 为 `null`。
- 旧的无日期 Fact 是长期兼容的合法输入。升级不批量迁移、不使用文件时间或升级日期补写，也不为缺少日期产生 Doctor 警告。
- 日期存在时必须是合法的 ISO `YYYY-MM-DD` 日历日期；无效日期使页面结构无效。
- 日期不触发 TTL、自动过期、降权、删除或定期确认。Agent 可在实际使用明显时效性内容时结合当前上下文核对。

### 结构损坏与机械修复

- list 保持严格只读，不得在扫描时隐式修复文件。
- 目标分区结构无效时，失败响应提供准确 `path`、`message`、`recovery`，并在适用时提供 `repairable=true` 和当前 raw/version，使 Agent 能决定是否调用修复。
- 扩展现有 `update`，增加 `target=repair`；不新增公开 Tool。
- 只有存在唯一规范结果且不需要发明或改变语义内容时，才允许 Agent 无需用户确认自动调用 repair。
- 可机械修复的情形包括：完整 frontmatter 字段顺序错误、换行/空白/末尾换行、完全重复 aliases、alias 等于同页 name、完全重复 Fact 行、mutation 时移除兼容的 legacy `sources`，以及能够完整解析后规范重渲染的文件。
- 不可自动修复的情形包括：name/path 不一致、缺少 description、正文含非 Fact prose、Fact content 超长、basis 非法、UTF-8 非法、symlink、非法 path，以及语义冲突但文本不同的 Facts。
- repair 必须携带失败响应提供的当前 version，在全局锁内执行 compare-and-swap。冲突或修复失败时 Agent 停止并通知用户，不循环重试或猜测修复。

### 批量边界、兼容与升级

- read 每次最多 15 个唯一 paths。
- 所有 mutation 每次最多 15 个 operations。
- create、add、move 每个 operation 最多 30 个 Facts。
- 这些边界由 Tool schema 和 Store 双方执行，失败时整批不写。
- 升级不扫描、不批量改写、不自动拆分 Memory Root。既有 description、aliases、Fact 和页面容量超限内容仍可读取；相关后续 Agent mutation 必须遵守新限制或向限制收敛。
- 当前合法页面无需因 schema 升级改变 version；只有真实 mutation 或显式 repair 才写文件。
- 公开 raw MCP Tool 仍必须且只能是现有八个：`list`、`read`、`create`、`add`、`update`、`move`、`rename`、`delete`。

## Scenarios

### 按需发现人物页

启动上下文告诉 Agent `people` 分区的用途但不列页面。任务涉及某人且动态路由可能改变回答时，Agent 调用 `list(scope="people")`，从完整有界目录中选取候选，再 read 所需页面。`topics` 或 `areas` 的损坏不影响这次 list。

### 主动记录新人物

用户提供了一个人的稳定关系背景或 Agent 从当前可见材料得到一条未来有用的详细 Fact。Agent先 list/read 防止创建语义重复页面；仅有姓名或一次性提及时不创建。推断内容写为 observed，明确陈述写为 stated。

### 动态页达到字符上限

Agent 的 add 会让一个动态页超过 5000 字符。Store 不提交该 add，并返回容量失败。Agent list/read 相应分区，优先把准确 Facts 原样 move 到既有合适页面；无候选时使用 move 的新目的页模式创建有语义名称的页面。随后基于返回的新 Page Snapshots 重试原 mutation。

### 目标分区已满

自动整理需要在 `people` 创建新页面，但已有 100 页且没有可复用目的页。Store 返回包含 scope/current/limit/recovery 的 `capacity_exceeded`；Agent停止并请用户整理 `people`，不影响其他分区继续增长。

### 固定页达到字符上限

向 preferences 或 profile 写入会超过 2000 字符。Store 拒绝 mutation；Agent向用户展示容量和候选内容，并建议精炼或显式删除，不自动迁移固定页 Facts。

### 结构损坏的单一分区

`people/broken.md` 存在可唯一规范化的 frontmatter 顺序问题。`list(scope="people")` 整体失败并标记 repairable；`list(scope="topics")` 仍成功。Agent使用失败返回的 version 调用 `update(target="repair")`，冲突时停止并通知用户。

### 旧 Fact 与日期

旧页面含 `- [stated] 内容。`。read 返回 `date: null`，Doctor 不警告。移动或页面规范化仍保持无日期；只有该 Fact 的 content 或 basis 后续确实更新，Store 才写入当天日期。

## Accepted decisions

- 选择“有界分区目录 + 按需完整 list”，而不是启动时全量目录、搜索、匹配或分页；分区硬上限使一次返回全部页面可预测。
- `people` 的页面额度高于其他分区，因为人物数量天然更多，并允许同一人物按稳定主题拆页。
- 容量限制作用于 Agent 写入准入，不把历史或人工文件变成不可读数据；Doctor 提供可见性，mutation 负责收敛。
- Store 保持结构化和确定性，只提供范围读取、验证、条件写入、事务性 move 与机械 repair；语义选择仍由 Agent 完成。
- 动态整理优先复用已有页，减少页面额度消耗；新页创建与 Fact 转移合成一次 move，避免 create 后留下空孤儿页。
- 跨文件崩溃仍不引入日志或数据库事务；沿用目的页先写的轻量安全原则，使最坏结果为重复而不是丢失。
- 日期由 Store 管理且不参与 Tool 输入，避免增加 Agent 参数、格式错误和伪造更新时间；无日期兼容优先于不准确迁移。
- 隐私边界只排除真正的秘密、完整高风险标识和用户明确拒绝记忆的内容，不以宽泛主题类别代替准入判断。
- basis 保持两值，不新增 provenance、confidence、reason、source 或 time-validity 字段；日期只表达记录的最后实际新增或更新日。

## Verification

- 扩展 `tests/test_memory.py` 的现有 codec、list/read、mutation、容量、冲突和 partial-commit 接缝，覆盖：
  - 带日期与无日期 Fact 的 parse/render/read；非法日期；日期不参与 Fact key；各操作的生成、更新和保留规则；单批次日期只读取一次。
  - scoped list 的输入、排序、恒定 aliases 字段、隔离验证和目标分区 fail-closed。
  - 50/50/100 分区页数准入，以及 create、新目的页 move、跨/同分区 rename 和已有超额树行为。
  - 80 字 description、6 aliases、800 字 content、2000/5000 最终页面限制，以及减少超限内容的 mutation。
  - 新目的页 move 的全批预检、源页非空约束、目的先写与中断后只重复不丢失。
  - repairable 分类、`update(target=repair)` 的 version 检查、唯一规范修复和不可修复拒绝。
- 扩展 `tests/test_mcp_schema.py`，证明仍只有八个 Tool，`list.scope` 是封闭枚举且无分页/搜索参数，写入 Fact schema 不含 date，update/move 判别式和 15/15/30 边界可发现。
- 扩展 `tests/test_hooks.py`，证明 bootstrap 保留 Home Pages 及 version、删除动态页面目录、只注入三分区固定说明，并能渲染带日期和无日期的 Home Page Facts。
- 扩展 `tests/test_diagnostics.py`，证明按分区页数、页面字符和兼容元数据只产生预期警告；无日期 Fact 不警告，结构非法日期阻塞。
- 更新并验证 `contracts/core-memory-v1/` 的合同与 canonical/legacy fixtures；旧无日期 fixture 必须继续读取，新的 canonical fixture 必须稳定渲染日期。
- 更新 MCP initialize instructions、Tool descriptions/schema 与短 Agent Contract，使 Agent 能发现按需 list、自动整理、repair、日期和失败分流规则。
- 运行最小相关测试后执行仓库现有完整门：

```shell
uv run pytest -q
uv run ruff check .
uv run pyright
uv run python scripts/smoke_mcp_server.py
```

## Acceptance criteria

- 启动输出不含任何动态页面 path/description/aliases，只含完整 Home Pages、它们的 version、三分区固定说明与按需 list 指引。
- `list` 缺少 scope、传入 all 或任何额外搜索/分页字段时失败；三个合法 scope 各自一次返回完整、排序、最小且 aliases 恒定存在的目录。
- 一个分区的非法页面不影响另两个分区 list；目标分区非法页面绝不被静默跳过。
- Agent 无法通过 create、新目的页 move 或跨分区 rename 把 topics/areas/people 分别增长到 50/50/100 以上；已有超额分区仍可读且可做不增加目标计数的 mutation。
- 新 Agent 写入不能产生 description>80、aliases>6、Fact content>800、固定页>2000 或动态页>5000 的结果；所有计数均基于约定的规范化内容。
- 动态页可在一次 move 中安全创建目的页并移动准确 Facts；任何失败路径都不会丢失 Fact，自动流程不会删除源页或留下 create 产生的空孤儿页。
- 固定页超限只返回失败和恢复信息，不发生自动整理；动态页只在 mutation 路径整理，任何 read/list/Doctor/Hook 都不写文件。
- Store 不执行语义匹配；Agent 自动整理先考虑现有页，只在必要时创建语义明确的新页，并在目标分区无额度且无可复用页时通知用户。
- 新建和实际更新的 Facts 得到同批次统一的本地 `YYYY-MM-DD`；移动、拆分、修复、重命名和页面元数据更新不改变日期；旧无日期 Fact 始终返回 `date:null` 且不被补写。
- `observed` 可用于所有页面中基于可见材料直接归纳或推断的内容，并明确区别于用户 stated；当前用户陈述在冲突时优先。
- 隐私准入只硬性拒绝已定义的真实秘密、完整高风险标识和明确“不要记住”，不按宽泛敏感主题自动拒绝其他稳定 Fact。
- 可唯一机械修复的页面能通过带 version 的 `update(target=repair)` 收敛；语义不明确或不可安全修复的页面保持原样并返回可行动错误。
- 升级本身不扫描或改写现有 Memory Root，旧格式、旧上限内的兼容数据继续可读。
- MCP 对外仍恰好八个 raw Tools，默认 smoke、完整测试、Ruff 与 Pyright 全部通过。

## Out of scope

- Store 端语义搜索、关键词搜索、向量检索、路径匹配或别名匹配。
- `list` 的 all scope、分页、cursor、limit、after、query、排序配置或容量统计字段。
- provenance、source、confidence、推断理由、证据计数、历史记录、Fact TTL 或自动过期。
- 背景扫描、启动迁移、读取时修复、定期整理、自动压缩、自动摘要或自动整页删除。
- 新的公开 MCP Tool、独立 repair Tool、独立 split Tool 或恢复日志/数据库事务。
- 人工编辑器的强制写入限制；人工/历史超限内容以兼容读取和 Doctor 可见性处理。
- Knowledge/RAG、项目 Authority、会话历史或宿主原生记忆系统的行为。

## Open questions

无。
