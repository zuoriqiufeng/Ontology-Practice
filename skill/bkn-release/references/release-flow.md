# 发布流程：开发机 → 现场（模块 1）

> **定位**：本文件回答「改完之后怎么送到现场、怎么证明送对了、怎么留痕」——补上更新文档缺失的
> 分发、前置校验、自检与记录四段。**改什么**由 skill:bkn-updater 回答。
>
> **原文来源**：原 doc/update/release-flow.md（2026-10-15 清理）（216 行，27 号批 V-2）。本文件是它的搬运与改写，
> 命令、判据、退出码均照原文；**引用一律纯文本路径**（AGENT.md R-1，不写链接）。
> **本流程不含任何运行时改动**，冻结期内可执行。

---

## 0. 一句话流程

```text
① 前置校验（开发机）──▶ ② 打包分发 ──▶ ③ 生效（重启服务进程）
                                             │
        ⑥ 不可覆盖原则 ◀── ⑤ 记录（changelog 锚行 + 对账）◀── ④ 自检（磁盘版本身份）
```

三个必须能答的问题：

| 问题 | 答案来自 |
|---|---|
| 现场此刻跑的是哪一版？ | §4 自检（磁盘层 + 身份层 + **进程层**） |
| 它相对上一版改了什么？ | §5 记录的版本锚行 → `changeset.py --show` |
| 怎么退回上一版？ | 本 skill 的 references/rollback.md 决策树 |

---

## 1. 前置校验（开发机）

两道，**都在打包之前**过：

```bash
cd <repo>/demo-product-bkn
bash scripts/gate.sh                       # ① 四道门全绿（含 ③b I14）
python3 scripts/bkn_version.py --check     # ① 复算一次 I14（磁盘内容 = 版本清单）
python3 scripts/changeset.py --check --strict   # ⑤ 记录对账（当前版本必须在 changelog 有锚行）
```

- `gate.sh` 任一道失败**不得发包**（`scripts/gate.sh`：① 结构 / ② 回归 / ③ 结构量+身份 / ④ 基线 / ⑤ 回放）；
- `changeset.py --check --strict` 要求**当前版本**在 changelog 有条目锚行——发布前过、
  发布中途（apply 刚升版还没写条目）**不过**，这是刻意设计（见 §5 第 4 条）。

## 2. 打包与分发

**随行清单必须含：`bkn/`、`plugin/`、`scripts/bkn_version.py`、仓库根 `bkn-version.json`。**
部署形态二选一（`doc/build/demo-product-bkn/40-build.md:12-21` 的安装方式）：

| 部署形态 | 怎么做 | 版本文件与自检 |
|---|---|---|
| **软链**（方式1） | `ln -s <repo>/demo-product-bkn/plugin ~/.hermes/plugins/demo-product-bkn` | 自动随行（同一份工作副本）；`Path(__file__).resolve()` 会把软链解到真实路径，`plugin/bkn` 与仓库根版本文件都指向开发机的那一份 |
| **拷贝**（方式2） | `cp -r <repo>/demo-product-bkn/plugin ~/.hermes/plugins/demo-product-bkn` | **必须补三样**：① 仓库根 `bkn-version.json`；② `scripts/bkn_version.py`（自检脚本本体，`REPO_ROOT = scripts/..`）；③ **修 `plugin/bkn`**——它是**绝对路径软链**（`plugin/bkn -> <repo>/demo-product-bkn/bkn/`），拷贝后仍指向开发机，需改为现场 BKN 路径或设 `DEMO-PRODUCT_BKN_ROOT` |

> 只拷 `plugin/` 是**不够**的：更新文档的旧安装方式（`40-build.md:16-17`）在"新增版本身份"之后需要补上面三样，
> 否则现场跑不了 `bkn_version.py --check`（脚本不在、基准文件也不在）。

为什么版本文件在仓库根、而不在 `plugin/` 或 `bkn/` 内（27 号 §2.2 的裁定理由）：
放 `bkn/` 内与「BKN 零冗余」冲突（**它本身就是元信息**）；放 `logs/` 内会被 `.gitignore` 忽略；
部署形态可能是软链或拷贝，**版本文件必须随部署走**。

## 3. 生效：`reload` 与它的真实范围 ★

### 3.1 命令

```bash
cd <repo>/demo-product-bkn/plugin
python3 scripts/reload.py
```

### 3.2 它**做不到**什么（本仓实测）

`reload()` 只重建**执行它的那个进程**里的全局对象（`plugin/scripts/reload.py:93,108-110` 重建
`tools._resolver` / `tools._traverser` / `tools._loader`），而 `python3 scripts/reload.py` 是
**短命进程**——跑完即退出。常驻的服务进程持有它自己的那一组句柄：
`plugin/tools.py:31-33` 是模块级全局，`plugin/tools.py:101-105` 的 `_init()` **只在句柄为 `None` 时创建，
此后没有任何失效或重建路径**。于是：

| 场景 | `reload.py` 生效吗 |
|---|---|
| 一次性新进程（如 `hermes chat -q "..."`，每次都是新进程） | ✅ 生效（新进程自己加载） |
| **常驻服务进程（Hermes 里已注册的插件实例）** | ❌ **不生效**——它仍持旧对象 |

`--watch` 模式同理（`plugin/scripts/reload.py` 的 `_watch()` 也是独立进程，监听与 reload 都发生在它自己进程内）。

**结论（本仓证据所及）**：要让改动对**常驻服务进程**生效，**以"重启服务进程"为准**。
旧表述（`plugin/CLAUDE.md:60` "BKN updates do not require Hermes restart"、`原 doc/update/README.md（2026-10-15 清理）`「热重载」节、
`plugin/scripts/reload.py:5` 的 docstring）在本仓代码里找不到支撑，**已更正**。

**复现实验（2026-10-10，隔离副本，可照抄）**：常驻进程先 `_init()` 建缓存（34 文件）→ 磁盘新增一个 `.bkn`
→ 独立进程跑 `reload.py`（**退出码 0、还打印"BKN 数据已重新加载"——看起来成功**）→ 常驻进程仍 34 文件
（**不生效**）→ 常驻进程内调 `reload()` → 35 文件（生效）。

```text
[常驻进程] _init() 后已解析文件数 = 34
[磁盘] 新增 bkn/objects/_drill_probe.bkn（模拟本体内容变化）
[独立进程] python3 plugin/scripts/reload.py → 退出码 0；首行：BKN 数据已重新加载
[常驻进程] 独立进程 reload 之后 = 34（期望 == 34，即不生效）
[常驻进程] 进程内 reload() 之后 = 35（期望 == 35，即生效）
结论：✅ 复现——独立进程 reload 不影响常驻进程；进程内 reload 生效
```

**注意这条命令的危险之处**：它的输出与"成功生效"完全一样，**退出码也是 0**——不改代码就分辨不出来。
这正是要在进程层加对照物（`logs/.loaded_version.json`）的原因。

> "服务进程加载了哪版"由 **§4 的进程层自检**回答（`logs/.loaded_version.json` +
> `plugin/scripts/check_loaded_version.py`，2026-10-12 起）：重启之后跑一次检查脚本，退 0 才算
> "进程与磁盘一致"；退 1 = 还没重启（正是本节那个静默不一致）。

### 3.3 什么时候**不需要** `--with-bm25`

**`.bkn` 文本改动不需要重建 BM25。** BM25 的索引语料是 **Qdrant collection 的文档**——
`plugin/bm25.py:174-278`（`_build_index` scroll 全量文档建索引、懒加载）；
本仓没有任何把 `bkn/` 送进 Qdrant 的代码路径。只有当 **Qdrant 语料本身更新过**
（重新向量化导入）时才需要：

```bash
python3 scripts/reload.py --with-bm25               # 重置全部注册集合
python3 scripts/reload.py --with-bm25 <collection>  # 只重置指定集合
```

**注意同样的进程范围问题**：`reset_bm25` 清的是**调用进程**的内存索引
（`plugin/bm25.py:284-299` 只 pop 模块级 `_bm25_indexes`），对常驻服务进程不生效；
服务进程侧重启即重建，无需单独跑这条命令。

## 4. 自检：怎么证明"现场跑的是这版"

| 层 | 命令 | 回答什么 | 现状 |
|---|---|---|---|
| **磁盘** | `python3 scripts/bkn_version.py --check` | 现场磁盘内容 = 版本清单（I14） | ✅ 已具备 |
| **身份** | `python3 scripts/bkn_version.py --show` | 现场**磁盘上**是哪版（`version_id` / hash / 文件数） | ✅ 已具备 |
| **进程** | `python3 plugin/scripts/check_loaded_version.py` | **服务进程加载的**是哪版、与磁盘现状是否一致（I16） | ✅ 已具备（2026-10-12） |

**进程层用法**：插件在 `register()`（服务启动）与 `reload()` 后写 `logs/.loaded_version.json`
（进程号 / 加载时间 / 触发方式 + 本进程加载根的内容 hash）；检查脚本做**三方比对**
（A 进程加载 / B 磁盘现状重算 / C `bkn-version.json` 记录）：

```bash
python3 plugin/scripts/check_loaded_version.py   # 0=一致；1=磁盘已改、进程未加载（重启）；2=无记录
```

- 退 **2** 的常见情形：服务进程还没跑过含本批的代码（**重启后自动生成**）；
- **刻意不挂 `gate.sh`**：`.bkn` 一改、进程未重启时它必报 1，而候选落盘后要跑 `gate --fast` 复验 → 会自锁。
  发布收尾手工跑一次（发布后若报 1 = 还没重启，正是要看的信号）。

## 5. 记录（发出去了就必须留痕）

1. **changelog 条目 + 版本锚行**（唯一权威：`CHANGELOG.md`）：
   条目内写一行机读锚 `- **版本**：bkn-YYYYMMDD-N`（27 号批 V-4 约定）。
2. **对账**（发布收尾跑）：
   ```bash
   python3 scripts/changeset.py --check --strict    # 其他明细见 scripts/changeset.py --help
   ```
3. **缺口闭合**（本次解决了缺口才跑；原文件自动留 `.bak`）：
   ```bash
   python3 plugin/scripts/mark_gaps_resolved.py --dry-run -4002
   python3 plugin/scripts/mark_gaps_resolved.py -4002
   ```
4. **走待审区的改动**（优化产物）：版本号由 `scripts/pending_apply.py` 落盘时**自动生成**
   （27 号 §2.4：**候选不是版本**，候选 `C-YYYYMMDD-NN` 与版本 `bkn-YYYYMMDD-N` 前缀刻意不同）。
   发布人只需把 `pending_apply` 打印的 `version_id` 写进第 1 条的锚行。
   —— 这解释了为什么 `--strict` 不能放进 apply 的复验门：apply 刚升版时锚行**必然**还没有，
   放进去会让每个改 `.bkn` 的候选"升版 → 无锚行 → 门禁红 → 回滚"（与 I14 的死锁同类）。

## 5b. 失败分类与重试上限（现场执行时用）

> **唯一事实源声明（D5）**：**重试规则只在本节定义**；references/rollback.md 只管「回滚怎么走」，
> **不重复**这里的三分类。

| 失败类别 | 判据 | 处置 | 上限 | 记录 |
|---|---|---|---|---|
| **可重试** | **环境就绪类**：目标目录不存在 / 权限不足、磁盘满、服务进程未停、软链未建立、`reload` 未执行 | 修好环境后**原样重跑该步骤** | 同一批次 **3 次** | 本节 ＋ changelog |
| **不可重试** | **内容错误类**：门禁红（I14 版本身份 / I15 版本与记录不一致）、版本文件缺失、hash 不符 | **停**，转 references/rollback.md 决策树 | **0 次**（一次都不重试） | 同上 ＋ 写明根因 |
| **需回退** | 已生效但现场表现不对（自检不过、加载版本不是预期） | 按 references/rollback.md 分支①②③ | 见该文件 | 同上 |

**三条纪律**：

1. **重试前必须能说清「这次和上次哪里不同」**——否则第 2 次与第 1 次等价，重试只是消耗时间。
2. **3 次是硬上限**；到顶后**停下来报错**，不许「再试一次看看」。
3. **不可重试类一次都不许重试**：I14 / I15 这类**矛盾**不会因重试而消失（重试只对**环境**有效）。

> **典型误判**：把「门禁红」当环境问题重试。门禁红是**内容**与**记录**对不上，重跑一百次还是红——
> 正确动作是回滚或修内容，不是重试。

## 6. 不可覆盖原则

**已发布版本的内容不可改写。** 内容要变，就是**一次新发布**：新的 `version_id` + 新的 changelog 锚行。
出问题不回写历史——按 references/rollback.md 的决策树处理，回滚同样是一次新发布。

---

## 7. 一页清单（照抄）

```bash
cd <repo>/demo-product-bkn

# ① 前置校验（开发机）
bash scripts/gate.sh
python3 scripts/bkn_version.py --check

# ② 分发：软链自动随行；拷贝必须另拷仓库根 bkn-version.json

# ③ 生效：重启服务进程（reload.py 不覆盖常驻进程，见 §3.2）

# ④ 自检（现场）
python3 scripts/bkn_version.py --check
python3 scripts/bkn_version.py --show

# ⑤ 记录：changelog 写条目 + 版本锚行，然后对账
python3 scripts/changeset.py --check --strict
```

---

*搬运自 原 doc/update/release-flow.md（2026-10-15 清理）（创建 2026-10-10，27 号批 V-2）；本文件仅为 skill references，不改变生效树。*
