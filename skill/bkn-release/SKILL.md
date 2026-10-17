---
name: bkn-release
description: |
  发布 / 发包 / 现场生效自检 / 发错了怎么退。把 Demo Product BKN 改动从开发机送到现场，
  证明「现场此刻跑的是哪一版」，并在发错时按决策树回退。
  覆盖前置校验（gate.sh + bkn_version.py --check + changeset.py --check --strict）、
  分发两形态（软链 / 拷贝）、生效（重启服务进程）、三层自检（磁盘 / 身份 / 进程）、
  changelog 版本锚行记录、失败三分类与重试上限，以及「回滚 = 一次新发布」。
triggers:
  - "发布 BKN"
  - "发包"
  - "上线"
  - "现场生效"
  - "自检是哪一版"
  - "版本对不上"
  - "发错了"
  - "回滚"
  - "退回上一版"
  - "门禁红"
  - "重试发布"
  - "现场跑的是哪版"
  - "重启服务进程"
  - "三层自检"
tools_used:
  - terminal
  - read_file
  - write_file
  - search_files
---

# Demo Product BKN 发布与回滚

> **一句话**：把改好的 BKN 送到现场、证明送对了、发错了能退，且**每一步都留痕**。
> **两条铁律**：① 前置校验不跑完不得发包；② **回滚 = 一次新发布**（已发布内容不可改写，版本号只前进）。
> 依据：原 doc/update/release-flow.md（2026-10-15 清理）、原 doc/update/rollback.md（2026-10-15 清理）；引用纪律见 AGENT.md R-1（**只写纯文本路径，不写链接**）。

## 速览

| 项 | 内容 |
|---|---|
| 用途 | 发布（开发机 → 现场）、生效（重启服务进程）、三层自检、留痕、回滚决策 |
| 核心流程 | ① 前置校验 → ② 打包分发 → ③ 生效（重启服务进程）→ ④ 三层自检 → ⑤ 记录（changelog 锚行 + 对账）→ ⑥ 不可覆盖 |
| 生效判据 | **重启服务进程**；`reload.py` 只作用于**执行它的那个短命进程**，对常驻服务进程不生效 |
| 三个必答问题 | 现场跑哪版（三层自检）/ 相对上一版改了什么（changelog 锚行 → changeset.py --show）/ 怎么退回（rollback 决策树） |
| 最小命令集 | `bash scripts/gate.sh`、`python3 scripts/bkn_version.py --check`、`python3 scripts/bkn_version.py --show`、`python3 plugin/scripts/check_loaded_version.py`、`python3 scripts/changeset.py --check --strict` |
| 关键约束 | 门禁红（内容类）**0 次**重试；环境类同批次**3 次**上限；版本身份含 `bkn/*.md` |

## 触发条件

用户说以下任一即加载：发布 BKN / 发包 / 上线 / 现场生效 / 自检是哪一版 / 版本对不上 / 发错了 / 回滚 / 退回上一版 / 门禁红 / 重试发布 / 现场跑的是哪版。

## 分流边界表

| 用户意图 | 归属 | 为什么 |
|---|---|---|
| 改 BKN 内容（新增对象 / 动作 / 错误码 / 症状 / 约束…） | skill:bkn-updater | 那是**改什么**；本 skill 只管**改完怎么送出去** |
| 退到旧版 / 回滚某一处改动 | 本 skill，references/rollback.md | 回滚是发布的逆操作，分支判据与顺序规则都在决策树里 |
| 改 Plugin 代码（`plugin/*.py` 架构与约束） | plugin/CLAUDE.md（纯文本） | 代码怎么改归它；跨全仓引用与写作纪律归 AGENT.md |
| 现场实例的问题（连不上 / 节点异常 / 库对不上） | skill:demo-product-i2agent-coop | 那是**运行态诊断**，不是发布动作 |
| 只想看现场是哪版，不做任何改动 | 本 skill「验收闸门」三条只读命令 | `--show` / `--check` / `check_loaded_version.py` 均只读 |
| 待审区候选的落盘（apply）本身 | scripts/pending_apply.py（不走本 skill） | apply 是候选系统的动作；发布人只接它打印的 `version_id` |

## 纪律门禁（硬约束）

1. **不跑完前置校验不得发包**：先 `bash scripts/gate.sh` 四道门全绿（含 ③b I14），任一道失败即停；再 `python3 scripts/bkn_version.py --check` 复算 I14；`python3 scripts/changeset.py --check --strict` 是**发布收尾**形态（要求当前版本在 changelog 有锚行 + `changeset_ref` 候选已 `applied`），**不得**塞进 apply 复验门。
2. **发布不可覆盖**：已发布版本的内容不可改写；内容要变就是**一次新发布**——新的 `version_id` + 新 changelog 锚行。出问题不回写历史，**回滚同样是一次新发布**（不回写历史、不覆盖旧版本号）。
3. **`reload.py` 不覆盖常驻服务进程**：`plugin/scripts/reload.py` 是**短命进程**，只重建**它自己进程内**的 `tools._resolver / tools._traverser / tools._loader`；常驻服务进程（Hermes 里已注册的插件实例）持有自己的那组句柄，`plugin/tools.py` 的 `_init()` 只在句柄为 `None` 时创建，此后没有失效或重建路径。**以「重启服务进程」为生效判据。** 危险点：独立跑 `reload.py` 会**退出码 0 并打印"已重新加载"**，与「成功生效」输出完全一样——不改代码分辨不出来，必须用进程层自检。
4. **版本身份含 `bkn/*.md`**：`bkn_version.py` 的纳入后缀是 `.bkn` 与 `.md`（排除 `templates`），当前清单 **44 文件**（40 个 `.bkn` + 4 个 `.md`）。**改 `bkn/` 下任何 `.md` 都会升版**——不是只有改 `.bkn` 才升版。

## 模块索引（references 表）

| 模块 | 文件 | 内容 |
|---|---|---|
| 1 · 发布主流程 | skill/bkn-release/references/release-flow.md | 前置校验 / 分发两形态与拷贝三补件 / 生效范围（`reload` 与 `--with-bm25`）/ 三层自检 / 记录 / 失败三分类与重试上限 / 一页清单 |
| 2 · 回滚决策树 | skill/bkn-release/references/rollback.md | 分支①定点恢复 / ①b 无候选来源 / ②批量恢复 / ③整版回退 / 门禁红非 I14 的二选一 / 收尾顺序规则 / 演练记录 |
| 3 · 版本身份 | skill/bkn-release/references/version-identity.md | `bkn_version.py` / `changeset.py` / `check_loaded_version.py` 的语义、参数、退出码与判据 |

## 验收闸门（可跑，三层自检）

| 层 | 命令 | 回答什么 | 通过判据 |
|---|---|---|---|
| 磁盘 | `python3 scripts/bkn_version.py --check` | 现场磁盘内容 = 版本清单（I14） | 退出码 **0**；非 0 会列出新增 / 删除 / 修改的文件清单 |
| 身份 | `python3 scripts/bkn_version.py --show` | 现场**磁盘上**是哪版 | 打印 `version_id` / hash / 文件数 |
| 进程 | `python3 plugin/scripts/check_loaded_version.py` | **服务进程加载的**是哪版、与磁盘现状是否一致（I16） | 退出码 **0 = 一致**；**1 = 磁盘已改、进程未加载 → 重启服务进程**；**2 = 无记录 / 文件缺失 / 自证降级** |

```bash
cd <repo>/demo-product-bkn
python3 scripts/bkn_version.py --check
python3 scripts/bkn_version.py --show
python3 plugin/scripts/check_loaded_version.py     # 0=一致；1=还没重启；2=无记录
```

> `check_loaded_version.py` **刻意不挂 gate.sh**：`.bkn` 一改、进程未重启时它必报 1，而候选落盘后要跑 `gate.sh --fast` 复验 → 会自锁。发布收尾手工跑一次（报 1 = 还没重启，正是要看的信号）。
> 退 2 的常见情形：服务进程还没跑过含「服务自证」的代码（**重启后自动生成** `logs/.loaded_version.json`）。

## 发布一页清单（照抄）

```bash
cd <repo>/demo-product-bkn

# ① 前置校验（开发机）
bash scripts/gate.sh
python3 scripts/bkn_version.py --check

# ② 分发：软链自动随行；拷贝必须另拷仓库根 bkn-version.json + scripts/bkn_version.py + 修 plugin/bkn

# ③ 生效：重启服务进程（reload.py 不覆盖常驻进程）

# ④ 自检（现场）
python3 scripts/bkn_version.py --check
python3 scripts/bkn_version.py --show
python3 plugin/scripts/check_loaded_version.py

# ⑤ 记录：changelog 写条目 + 版本锚行，然后对账
python3 scripts/changeset.py --check --strict
```

## 相关权威位置（纯文本指针）

| 主题 | 权威位置 |
|---|---|
| 发布主流程原文 | `references/release-flow.md`（原 doc/update/release-flow.md，2026-10-15 清理） |
| 回滚决策树原文 | `references/rollback.md`（原 doc/update/rollback.md，2026-10-15 清理） |
| BKN 改动逻辑（改什么） | skill:bkn-updater |
| Plugin 代码规范（代码怎么改） | plugin/CLAUDE.md |
| 跨全仓写作与引用纪律 | AGENT.md |
| 现场实例协同诊断 | skill:demo-product-i2agent-coop |
| 迭代记录（版本锚行宿主） | CHANGELOG.md |
