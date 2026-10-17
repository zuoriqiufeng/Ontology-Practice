# Hermes Agent 中的 BKN 集成指南

BKN 知识网络在 Hermes Agent 中的加载方式与 KWeaver 略有不同。核心原理是将 BKN 文件树放到 Skill 的 `references/` 目录或项目独立目录中，通过 Agent 按需 `read_file()` 实现渐进式披露。

---

## 核心区别: Hermes 没有 `@include`

| KWeaver (原生) | Hermes (适配) |
|---------------|--------------|
| `@include(network.bkn)` 指令 | Agent 主动调用 `read_file("bkn/network.bkn")` 或 `skill_view(name, 'references/bkn/network.bkn')` |
| BKN 解析器编译注入 | Agent 直接读取 Markdown, LLM 理解 |
| 框架自动展开 | Agent 按索引表场景决策加载 |

## 推荐文件放置

### 方案 A: Skill 内嵌 (单 Skill 独享)

适用于 BKN 仅服务于一个 Skill。
```
skills/<skill-name>/
├── SKILL.md
└── references/
    └── bkn/
        ├── objects/...
        ├── actions/...
        └── risks/...
```
加载: `skill_view('skill-name', 'references/bkn/objects/sync_rule.bkn')`

### 方案 B: 项目独立目录 (多 Skill 共享)

适用于多个 Skill 共享同一张 BKN 网络 (如 Demo Product 的 4 个 Skill)。
```
$STREAM_ROOT/
├── skills/               (Agent Skill)
└── bkn/                  (共享 BKN, 纳入 Git)
    ├── network.bkn
    ├── objects/...
    ├── relations/...
    ├── actions/...
    └── risks/...
```
加载: `read_file("bkn/objects/database_node.bkn")`

---

## SKILL.md 渐进式协议模板

在 SKILL.md 中用索引表替代全文, 让 Agent 按场景决策:

```markdown
## 知识网络索引

本 Skill 采用渐进式加载。根据用户意图按需展开对应文件。

| 场景 | 加载文件 | 
|------|---------|
| 创建规则 | `read_file("bkn/actions/rule_lifecycle.bkn")` |
| 操作规则 | `read_file("bkn/objects/sync_rule.bkn")` |
| 性能异常 | `read_file("bkn/risks/performance.bkn")` |

## BKN Risk 硬约束 (全局, 保留在 L0)
- 修改运行中规则: 禁止
- 未确认删除: 禁止
```

---

## 三层加载模型

```
L0: SKILL.md (自动注入, ≤3K tokens)
    → 索引表 + 高频速查 + 全局 Risk

L1: skill_view + file_path
    → 展开 references/ 下的 BKN 文件

L2: read_file
    → 加载项目任意位置的 BKN/参考文件

Token 消耗: L0(~400) + L1(~800) = ~1200
vs 全量: ~6000+ 节省 80%
```

---

## 与 Memory 的协同

BKN 和 Hermes Memory 各司其职:

| | BKN | Memory |
|---|-----|--------|
| 内容 | 业务本体/规则/操作 | 用户/环境/偏好 |
| 注入时机 | 按需 read_file | 每轮自动注入 |
| 维护者 | BKN-Creator + 人工审核 | Agent 自动提取 |
| 版本管理 | Git | SQLite |

## 与 ContextLoader 的协同

ContextLoader（KWeaver）的 Trim + Toon 机制可进一步优化 BKN 上下文:
- **Trim**: BKN 文件天然已过滤冗余字段（无 _score/UUID/MD5），与 Trim 理念一致
- **Toon**: BKN 的 Markdown 表格格式与 Toon 紧凑表示等效，压缩率 30-60%

详见 [contextloader-integration.md](contextloader-integration.md)
