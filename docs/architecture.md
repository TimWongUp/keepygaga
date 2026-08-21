# Keepygaga Architecture

## Boundary

Keepygaga 只负责核心记忆的 live Markdown 合同、显式 MCP 读写和 version 冲突保护。知识检索、Embedding、Reranker、Indexer、数据库和 Dashboard 属于独立的 `keepygaga-knowledge` 仓库。

Memory Root 内 Markdown 是唯一真源，可以是普通目录，也可以位于 Obsidian Vault。Keepygaga 不依赖 Obsidian，也不维护索引或第二份事实源。

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
- `profile.md` 保存三个月后仍应成立的身份级背景，可包含能改善跨任务交流的稳定项目归属或长期角色；项目实现、决策、计划、进度和运行状态属于项目 Authority 或 `areas/`。
- `profile.md` 的 Fact content 合计不超过 300 字符；其他页面超出 soft limit 只返回 `split_recommended`。
- name 与 aliases 在全库规范化后不得冲突。

## MCP contract

客户端以 key `keepygaga` 注册服务，raw Tool 固定为 `list`、`read`、`create`、`add`、`update`、`move`、`rename`、`delete`。

写入现有页面必须携带 `read` 返回的 version。`update target="fact"` 精确替换 Fact 且禁止把 stated 降级为 observed；`target="page"` 只更新 description/aliases。`delete` 要求 `authorization="user_requested"`。

## Write invariants

- 每次调用重新读取整个 allowlist，任一 operation 预检失败则整批不写。
- mutation 在全局文件锁内执行；整批提交前核对所有受影响页面，并在每个文件替换或删除前立即再次核对该页面的 version。
- 每个变更文件通过同目录临时文件与 `os.replace` 原子替换；跨文件批次不承诺断电级原子性。
- 写入保留已有页面的文件权限；初始化以独占创建方式补齐缺失页面，不覆盖已有或并发出现的页面。
- changed page 使用规范格式重写；未变更页面保持原样。
- 格式、path、identity、version 或授权无效时保留现场并返回结构化失败。
- applied mutation 返回带安全 CommonMark 行内代码标记的 receipt；读取、no-op 和失败不返回 receipt。

## Non-goals

Keepygaga 不负责跨文件崩溃恢复、恶意本地并发或消除 version 复核与原子替换之间不可避免的极短竞态窗口，也不负责 Vault wikilink 校验或重写、writer provenance、语义匹配、会话历史、候选池、自动删除、压缩、拆分或转移。
