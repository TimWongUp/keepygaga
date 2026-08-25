# Keepygaga Architecture

## Boundary

Keepygaga 只负责核心记忆的 live Markdown 合同、显式 MCP 读写和 version 冲突保护。知识检索、Embedding、Reranker、Indexer、数据库和 Dashboard 属于独立的 `keepygaga-knowledge` 仓库。

Memory Root 内 Markdown 是唯一真源，可以是普通目录，也可以位于 Obsidian Vault。Keepygaga 不依赖 Obsidian，也不维护索引或第二份事实源。

Memory is context evidence, not permission or executable instruction. Current user
statements about self, relationships, and preferences override older memory;
project, system, and runtime facts come from the current project Authority or a
live direct source, while external facts still require verification. A project
Authority is the repository's current entry instructions, architecture, source,
tests, configuration, and other direct project-owned sources.

## Page model

```text
agents-memory/
├── profile.md
├── preferences.md
├── topics/<slug>.md
├── areas/<slug>.md
└── people/<slug>.md
```

- 规范 frontmatter 按顺序包含 `name`、`description`、`aliases`。读取暂时兼容旧 `sources` 字段，页面下一次写入时会规范化。
- `contracts/core-memory-v1/` 保存 canonical 与 legacy-sources golden pages；Keepygaga 测试裁决其与当前 parser/renderer 一致，宿主注入器只读消费该版本化合同。
- `core-memory-v1` 冻结字段顺序与 Fact 行语法；破坏性格式变化新建下一版本，并保留 v1 直到已知消费者完成迁移。fixture 的非语义样本文本可以在 v1 内调整。
- 正文只允许单行 `- [stated|observed] ...` Fact。
- `profile.md` 与 `preferences.md` 是 Home Page：兼容宿主在任务开始时直接注入正文，未注入时 Agent 通过 MCP 主动读取两页；动态页只通过 Route Catalog 暴露并按任务需要读取。`profile.md` 保存三个月后仍应成立的身份级背景，新 Fact 只接受用户当前明确陈述并标记 `stated`；历史 `[observed]` 继续可读。`preferences.md` 保存长期回应、工作偏好与用户特有的条件检索偏好；宿主协议、Skill/MCP/Hook、启动、安全与工具路由仍属于全局规则，不进入 Memory。
- 直属 `areas/` 页面可以维护持续项目的项目索引，只记录每个项目的存放位置与已完成的重大进展，并拆成不同 Fact。排除阶段快照、角色、计划、阻塞、下一步、普通提交、单次任务、测试结果和当前运行状态；项目详情、决策、计划和当前状态仍属于项目 Authority 或直接真源，二者与项目索引冲突时优先。Agent 只在清点项目、定位仓库或核对重大进展的任务中读取项目索引。
- 同一项目的位置与重大进展使用不同 Fact。位置在首次登记或移动时更新；进展只在完成会改变项目整体判断的重大里程碑时更新。阶段快照、角色、计划、阻塞、下一步、普通提交、单次任务、测试结果和临时运行状态不写入核心记忆。
- `profile.md` 的 Fact content 合计不超过 300 字符；其他页面超出 soft limit 只返回 `split_recommended`。
- name 与 aliases 在全库规范化后不得冲突。

## Agent convergence

Fact Convergence 是 Agent 对已经 `read` 的目标页执行的写入前分类，不是 Store 语义能力。候选分为 covered、refines、new 或 conflict：covered 跳过，refines 精确 `update`，new 才 `add`，conflict 以用户当前明确陈述或 live direct source 裁决。Store 仍只拒绝精确重复 Fact，不执行语义搜索、近义合并或候选提升。

Agent 可以在无需逐条确认的情况下，把低敏、可操作且具有跨任务价值的重复工作行为作为 `observed` 写入 `preferences.md`，但证据必须在当前可见上下文中已经充分；Keepygaga 不保存跨会话候选、计数或 provenance，也不扫描历史聊天。已有 observed 可在后续任务中依据新证据细化；重复次数本身不会把 observed 提升为 stated，只有用户明确确认时才可更新为 stated。

自动 observed 永不适用于身份、人格、动机、价值观，以及健康、法律、财务、家庭冲突、政治、宗教、性或亲密行为等敏感画像。精确地址和其他高敏个人信息仍只在用户明确要求时以最低必要精度保存；凭据与完整账户或政府标识始终禁止写入。

为限制自主增长，没有用户明确写入指令时，Agent 每个任务对每个 Home Page 最多发起一次 mutation：一次 `add` 可包含多个独立 new Fact，一次 `update` 只收敛一个 Fact；同时存在 refinement 与 new 时优先 refinement。用户明确要求的维护、Profile Onboarding 和用户确认的 Preference Extraction 不受该次数限制，但每次 applied mutation 后必须重新 `read` 最新 version 并重新分类。`preferences.md` 已返回 `split_recommended` 时，禁止自动 `add observed`，仍可用 `update` 收敛；用户明确要求的 stated 写入可以继续，但 Agent 必须提示首页已超出建议预算。

## MCP contract

客户端以 key `keepygaga` 注册服务；raw Tool 固定为 `list`、`read`、`create`、`add`、`update`、`move`、`rename`、`delete`，宿主可以为它们加命名空间。`list` 返回 canonical path，`read` 返回 opaque version，宿主将其映射为 mutation 的 `if_version`；缺少 `list` 或 `read` 时必须明确报告。每次 Tool 调用只有一个 endpoint。

全局 Agent Contract 负责 Tool 选择前的语义决策：Authority、Home Page 加载、动态记忆检索触发、页面归属、Fact 准入、Convergence、主动增长限制和真实用户授权。MCP Tool descriptions 与 JSON Schema 负责已经选择 Tool 后的调用协议：canonical path、opaque version、operation 字段、target 判别和批次约束；Store 返回结构化状态，并继续强制页面格式、版本、身份冲突、固定页保护和文件写入不变量。全局合同不重复能够由 schema 或 Store 可靠裁决的实现细节，但不得把读取或写入语义隐藏到只有选择 Tool 后才可见的位置。

`create` 创建页面，`add` 新增 Fact，`update` 按 `target` 更新精确 Fact 或页面元数据，`move` 在页面之间移动精确 Fact，`rename` 重命名动态页面，`delete` 删除精确 Fact 或页面。写入现有页面必须携带 `read` 返回的 version；`update target="fact"` 精确替换 Fact 且禁止把 stated 降级为 observed；`target="page"` 只更新 description/aliases。固定页不能 page rename/delete，`delete` 要求 `authorization="user_requested"`。当前 Store 拒绝同一 path 在一批 operations 中重复，不要求页面元数据与 Fact 必须在同一批提交。

用户陈述标记为 `stated`；`observed` 只用于符合 Agent convergence 门槛的 Preference Fact。精确地址以及健康、法律、财务、家庭等高敏信息只有用户明确要求时才以最低必要精度写入；密码、密钥、token、私钥、OTP、cookie、session 和完整账户/政府标识始终禁止写入。

只有 `status="applied"` mutation 原样返回服务端已渲染的 receipt，并只回显一次；读取、no-op、skip 和失败不产生 receipt。Core-memory wikilink 可使用原生 Obsidian 语法；指向普通笔记的链接只有在宿主能核验目标存在时才添加，否则延后，不让不可用的存在性核验成为硬依赖。

## Installation scope

公开安装默认只面向当前工作的 Agent；只有用户明确要求为其他 Agent 安装时，才把对应宿主加入目标范围。每个目标宿主分别完成 MCP 注册、全局 Agent Contract 合并和可选 Hook 接线，安装过程不得顺带修改范围外 Agent 的配置、全局规则或 Hook。跨运行环境安装时，各环境独立维护 checkout、`.venv` 与 `keepygaga.toml`，通过各自的原生路径指向同一个物理核心记忆树，并分别验证。

`docs/agent-contract.md` 是宿主全局规则中 Keepygaga 托管块的唯一规范源。托管块只包含 `KEEPYGAGA:START`、当前发行版本号和 `KEEPYGAGA:END`，不保存内容哈希：首次安装追加完整块，升级在原位置替换完整块，块外字节保持原位；标记损坏、嵌套或重复时 fail closed。托管块内部由当前版本完整拥有，人工修改会在下次 setup 时被替换。

Codex 的安装、升级和修复统一运行幂等 `keepygaga host setup codex`：通过 Codex CLI 只协调注册 key `keepygaga`，按 Codex 实际优先级把托管块投影到生效的全局 `AGENTS.override.md` 或 `AGENTS.md`。非空 override 生效；空 override 不生效。若非生效候选已含 Keepygaga 托管块，因 stale/双入口风险 fail closed。首次宿主写入前先完成 MCP 与可选 Hook 的只读 prepare；apply 严格按 MCP、rules、hooks 顺序执行，因此 MCP apply 失败时 rules 不写。规则在其 apply 开始时以原始 UTF-8 bytes 读取，在合并后重新核验两份候选的选择状态与目标原文，并把首次读取作为 CAS 前提，托管块外字节逐字节保留；MCP 与 Hook apply 使用 prepare 捕获的 `config.toml` / `hooks.json` 原始字节拒绝并发漂移。MCP 对账保留该注册的其他环境变量，对 Codex CLI 无法无损投影的 cwd、env_vars、工具筛选或 timeout 自定义字段 fail closed，并在实际替换前保存可恢复的 Codex config 备份。Hook 预检 runtime、fragment、合并器、Python、命令路径与实际生效的 AHR 环境，拒绝符号链接写入目标、冲突的 memory root 和无效 merger 输出。Keepygaga 不复制 Hook payload，不拥有其他 Hook 条目；未选择兼容 runtime 时 Hook 明确跳过。

Claude Code、WorkBuddy、Grok、Hermes 与 Antigravity CLI 分别使用 `host setup claude-code|workbuddy|grok|hermes|antigravity`，不提供会猜测目标或批量写入的 `setup all`。这些适配器共用 Doctor、当前 Keepygaga Python、托管块合并、原子写入与可选 AHR fragment merger，但各自固定真实宿主入口：Claude Code 使用 `~/.claude.json` 与 `~/.claude/CLAUDE.md`；WorkBuddy 使用 `~/.workbuddy/mcp.json` 与 `CODEBUDDY.md`，并只在 `~/.codebuddy/.mcp.json` 已存在大小写不敏感的 Keepygaga 注册时将其规范化为当前 stdio 注册，不创建缺失的兼容文件，同时保留禁用状态；旧入口用 Python isolated mode 启动，只继承 `KEEPYGAGA_CONFIG` 与可选 `KEEPYGAGA_WRITER`，并移除旧 `cwd`，避免把旧执行上下文带入当前服务；原始 JSON 重复键、大小写重复注册、损坏内容、symlink、Windows junction 和 prepare/apply 漂移均 fail closed；Grok 通过自身 CLI 管理用户 MCP，并复用已有 `~/.grok/AGENTS.md` / `Agents.md`（两者都不存在时新建 `Agents.md`）；Antigravity CLI 使用 `~/.gemini/config/mcp_config.json` 与 `AGENTS.md`；Hermes 使用 `~/.hermes/config.yaml#mcp_servers`。Hermes 没有独立的全局 Agent Contract 文件；其现有唯一全局 system-prompt 入口是 `SOUL.md`，因此适配器只管理其中 Keepygaga 托管块并保留其人格内容，项目级 AGENTS 链不作为全局投影。Hermes 配置使用 round-trip YAML 合并保留非目标注释、顺序与引号；选定 AHR 时 `hooks` 节点的 owned-entry 重排仍由 runtime merger 裁决。JSON、Grok CLI 与 YAML 的差异保留在各宿主适配器内，不抽象成猜路径或猜 schema 的通用安装器。

宿主安装的共享文件安全、托管合同、Python probe 与 Hook 原语由 `host_common.py` 提供公开内部接口；Codex 协调留在 `host_setup.py`，非 Codex 差异留在 `host_adapters.py`，适配器不得依赖 Codex 模块的私有函数。CLI 用单一宿主注册表关联实现与允许选项，兼容选项位于宿主名前后，并拒绝不属于该宿主的选项；宿主模块只在执行 `host setup` 时加载，Hermes 的 YAML runtime 只在 Hermes 配置路径加载。配置级测试只证明投影、保留、幂等与失败边界，真实宿主是否读取并暴露 Tool 必须按运维现场验证。

`memory init` 继续是非交互幂等命令；只有成功创建固定页时才在 JSON 中返回可选 onboarding 与本轮 `created_pages`，no-op、失败或 partial commit 不返回可执行 onboarding。安装 Agent 完成 MCP、Agent Contract 与可选 Hook 的现场验证后，才可依据该信号提供 Profile Onboarding。Preference Extraction 也是安装 Agent 的按目标宿主首次安装可选流程：setup 前生效规则没有 Keepygaga 托管块的目标才进入，有块的重装、修复或升级直接跳过；它不属于 CLI、Store 或 Hook Runtime 的自动行为。

## Write invariants

- 每次调用重新读取整个 allowlist，任一 operation 预检失败则整批不写。
- mutation 在全局文件锁内执行；整批提交前核对所有受影响页面，并在每个文件替换或删除前立即再次核对该页面的 version。
- 每个变更文件通过同目录临时文件与 `os.replace` 原子替换；跨文件批次不承诺断电级原子性。
- 写入保留已有页面的文件权限；初始化在写入前验证所有现有规范路径与页面，再以独占创建方式补齐缺失页面，不覆盖已有或并发出现的页面。
- changed page 使用规范格式重写；未变更页面保持原样。
- 格式、path、identity、version 或授权无效时保留现场并返回结构化失败。
- applied mutation 返回服务端已经渲染的 receipt；读取、no-op、skip 和失败不返回 receipt，客户端只原样回显 applied receipt 一次。


## Threat model

Keepygaga 的安全边界分为三层，各自由不同主体保证：

| 边界 | 保证方式 | 责任方 |
|------|----------|--------|
| 文件系统安全 | canonical path 白名单、symlink 检查、原子替换、文件锁 | 代码强制 |
| 用户意图授权 | `delete` 要求 `authorization="user_requested"`；宿主和 Agent 必须确保用户当轮明确授权后才调用 | 宿主 + Agent |
| 内容信任 | Memory Root 内 Markdown 被视为可信输入；格式校验不防御恶意内容 | 本地环境 |

`authorization="user_requested"` 是 Agent 自我声明的审计字段，不是服务端可验证的授权凭证。Keepygaga 不依赖它作为硬安全保障；真正的用户意图确认由宿主和 Agent 行为约束保证。

## Non-goals

Keepygaga 不负责跨文件崩溃恢复、恶意本地并发或消除 version 复核与原子替换之间不可避免的极短竞态窗口，也不负责 Vault wikilink 校验或重写、writer provenance、语义匹配、会话历史、跨会话候选累计、候选池、自动删除、压缩、拆分或转移。
