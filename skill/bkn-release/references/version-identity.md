# 版本身份：三个脚本的语义、参数与退出码（模块 3）

> **定位**：本文件是"现场跑的是哪一版"这件事的**实现口径**——「bkn_version.py」（磁盘身份）、
> 「changeset.py」（版本 ↔ 记录对账）、「check_loaded_version.py」（服务进程自证）三者的
> 用途、参数、退出码与判据。
>
> **来源**：直接读三个脚本的 docstring 与 `argparse` 定义（scripts/bkn_version.py、
> scripts/changeset.py、plugin/scripts/check_loaded_version.py），非二手转述。
> **引用一律纯文本路径**（AGENT.md R-1，不写链接）。

---

## 0. 三个脚本各回答什么

| 脚本 | 回答的问题 | 判据名 | 退出码 |
|---|---|---|---|
| `scripts/bkn_version.py --check` | 现场**磁盘内容** = 版本清单？ | I14 | `0` 一致 / `1` 不一致或缺失 |
| `scripts/bkn_version.py --show` | 现场**磁盘上**是哪版？（`version_id` / hash / 文件数） | — | 打印身份 |
| `scripts/changeset.py --check --strict` | 当前**版本**在 changelog 有锚行、候选已 `applied`？ | I15 | `0` 通过 / `1` 不一致 |
| `plugin/scripts/check_loaded_version.py` | **服务进程加载的**是哪版、与磁盘现状是否一致？ | I16 | `0` 一致 / `1` 磁盘已改进程未加载 / `2` 无记录 |

---

## 1. scripts/bkn_version.py — BKN 版本身份（27 号批 V-0）

**为什么需要**：27 号 §1 实测——`git tag` 0 个、无版本目录、无 active 指针、无 changeset，
"现场此刻跑的是哪一版"**无法回答**；`.reload_state.json` 只有 mtime，不能证明生效。

**设计（Q7/Q18 裁定）**：

- **文件级 sha256 清单**（不是全量单 hash）——能回答"这次改动碰了哪几个文件"（回滚与评审要用）；
- **落仓库根 `bkn-version.json`**——部署形态可能是软链或拷贝，版本文件必须**随部署走**；
  放 `bkn/` 内会与「零元信息」（它本身就是元信息）冲突，放 `logs/` 会被 `.gitignore` 忽略；
- 版本号 `bkn-YYYYMMDD-N`（N = 当日序号，从既有版本自增，无需外部状态）；
- **hash 算法单点定义在本文件**，25 号批 U-2（服务自证）复用，不各写一套。

**路径常量**：`REPO_ROOT = Path(__file__).resolve().parent.parent`、`BKN_DIR = REPO_ROOT / "bkn"`、
`VERSION_FILE = REPO_ROOT / "bkn-version.json"`。

**纳入范围（本仓实测：44 文件）**：`INCLUDE_SUFFIXES = (".bkn", ".md")`，排除路径中含 `templates` 的件。
实测清单 **44 个** = **40 个 `.bkn`** + **4 个 `.md`**。⚠️ **改 `bkn/` 下任何 `.md` 都会升版**。

**命令行**：

```bash
python3 scripts/bkn_version.py --write            # 生成/升级版本（读完当前内容 → 写 bkn-version.json）
python3 scripts/bkn_version.py --check            # 校验当前 bkn/ 内容与版本清单是否一致（I14）
python3 scripts/bkn_version.py --show             # 打印当前版本身份
python3 scripts/bkn_version.py --diff A B         # 比对两份版本文件（改了哪几个文件）
```

**`--write` 的可选参数**：`--label`（简短标签）、`--changeset`（指向 changelog 条目 / 号方案，
即 V-4 的键）、`--released-by`（发布人，可选，Q20：不强填，避免形式主义）。

**`--write` 写入 `bkn-version.json` 的字段**（`cmd_write`）：`schema=1`、`version_id`、`version_hash`、
`released_at`、`released_by`、`changeset_ref`、`label`、`supersedes`（被取代的上一版 id）、
`file_count`、`files`（文件级清单）。写成功打印
`✅ 已写 bkn-version.json：bkn-YYYYMMDD-N（44 文件，hash …）` 与`取代 …`，
并提示「下一步：把 version_id 记入 90-history/bkn-changelog.md（V-4 changeset 对账）」。
**内容未变时**（`version_hash` 与上一版相同）：打印「内容未变，版本仍为 …——未生成新版本」并返回 0。

**`--check` 的判据**（`cmd_check`）：比对记录清单与实算清单，分**新增 / 删除 / 修改**三类；
三类皆空 → 打印
`✓ 内容与版本清单一致：<version_id>（44 文件，hash …）` 并返回 **0**；
否则打印 `✗ 内容与版本清单 **不一致**（当前版本 …）——I14` 并逐条列出，返回 **1**。
版本文件缺失或不可解析 → 返回 **1**。

**hash 算法（单点）**：`manifest_for(root, prefix)` 产出 `<prefix>/相对路径 -> sha256`；
`version_hash(files)` 把清单**排序后逐个喂`相对路径 + 文件 sha256`归并成一个 hash。
**相对根**（不是绝对、不是相对 cwd）——同一份内容无论从哪调用都得到同一个 hash。
服务自证（模块 3 第 3 节）对插件实际加载的 `BKN_ROOT` **复用本函数**，两处 hash 才能直接比对。

---

## 2. scripts/changeset.py — 版本 ↔ 记录的机械对账（27 号批 V-4）

**问题**：版本号住在 `bkn-version.json`，改动记录住在 `90-history/bkn-changelog.md`，
两头没有机械联系——"这一版对应哪条记录""这条记录是哪个版本"只能靠人记。

**约定**：changelog 里每条**发布**对应的条目内，写一行**版本锚行**（机读、唯一）：

```text
- **版本**：bkn-YYYYMMDD-N
```

锚行**该行只出现这一个版本号**（其后可跟一句简短说明，如 `（含 … 两次落盘）`）——
校验是"该行恰好能解析出一个版本号"，不是"整行必须光秃秃"。
机读前缀常量：`ANCHOR_PREFIX = "- **版本**："`；版本号形态 `^bkn-[0-9]{8}-[0-9]+$`。

**两种检查形态**（刻意分开）：

| 形态 | 跑到哪 | 为什么 |
|---|---|---|
| `--check`（门禁形态） | 已有锚行合法 / 唯一 / 不倒挂；`changeset_ref` 若指向候选，**候选须存在** | **不要求"当前版本必须有锚行"**，也不要求候选已 `applied`——`pending_apply` 落盘时会自动升版，且**复验门跑在候选 status 改写之前**；若门禁要求这两条，任何改 `.bkn` 的候选都会"升版 → 门禁红 → 回滚"。与 I14 的死锁同类 |
| `--check --strict`（发布收尾） | 额外要求**当前版本**有锚行、且 `changeset_ref` 的候选 `status=applied` | 只有发布动作结束时才该满足；`pending_apply` 跑的是 `gate.sh --fast`，用的是上面那条 |

**命令行**：

```bash
python3 scripts/changeset.py --check              # I15（门禁形态）
python3 scripts/changeset.py --check --strict     # 发布收尾（含当前版本）
python3 scripts/changeset.py --show [版本号]       # 某版本的记录条目 + 涉及文件
```

**退出码**：`0` 通过 / `1` 不一致（供 `gate.sh` 用）。
**changelog 路径**：`CHANGELOG.md`（唯一权威）。

---

## 3. plugin/scripts/check_loaded_version.py — 服务自证一致性检查（I16）

**回答两个问题**：① 此刻**服务进程**加载的是哪版（`logs/.loaded_version.json`）；
② 它与**磁盘**是否一致——**三方比对**：

| 记号 | 来源 |
|---|---|
| A | 进程加载（`loaded.version_hash`，自证时算出） |
| B | 磁盘现状（**现在**对 `loaded.bkn_root` 重算 manifest → hash） |
| C | 版本记录（仓库根 `bkn-version.json` 的 `version_hash`，即"已发布的是哪版"） |

**判定**：

- `A == B` → 一致（进程加载的就是磁盘现状）；若 `B != C` 附注「内容未升版（I14）」提示；
- `A != B` → 不一致：磁盘已改、进程未加载 → **重启服务进程**（这才是"哪版生效"的主判据）；
- `A == B` 但记录陈旧 → **不判失败**（I14 由 gate ③b 负责），只提示先 `bkn_version.py --write`。

**退出码（供现场与脚本用）**：`0` = 一致；`1` = 不一致（磁盘已改、进程未加载 → 重启）；
`2` = 无记录 / 文件缺失 / 自证降级。

**参数**：`--loaded`（缺省 `LOADED_VERSION_FILE`，即 `logs/.loaded_version.json`）、
`--version-file`（缺省仓库根 `bkn-version.json`）、`--bkn-root`（缺省取自证记录里的 `bkn_root`）。

**运行方式**：

```bash
python3 plugin/scripts/check_loaded_version.py   # 0=一致；1=磁盘已改、进程未加载（重启）；2=无记录
```

**退 2 的常见情形**：

- 服务进程还没跑过含「服务自证」的代码——**重启后自动生成** `logs/.loaded_version.json`；
- 自证文件不是合法 JSON；
- 自证时 hash 计算失败（记录里有 `hash_error`）；
- 无法重算磁盘内容 hash（BKN 根不存在等）。

**写入时机**（`plugin/loaded_version.py`）：`register()`（Hermes 启动注册插件时）与每次 `reload()` 之后；
内容为进程标识 + 加载时间 + 触发方式 + 实际 BKN 根 + 版本号 + 版本 hash；算法与磁盘身份**单点同源**
（`scripts/bkn_version.py::manifest_for/version_hash`）。全程 `try/except`：自证写不进去
（只读盘 / 无权限）**不得**影响插件注册与主流程。

**为什么刻意不进 `gate.sh`**：`.bkn` 一改、进程未重启时该检查必然报不一致，而 `pending_apply`
落盘后要跑 `gate.sh --fast` 复验 → 会自锁。现场自检与发布收尾**手工跑**。

---

## 4. 三层身份怎么合起来读

| 观察 | 含义 | 动作 |
|---|---|---|
| 磁盘 `--check` 退 0，进程检查退 0 | 磁盘内容 = 版本清单；进程加载 = 磁盘现状 | 发布成立，去写 changelog 锚行 |
| 磁盘 `--check` 退 0，进程检查退 1 | **磁盘已改、进程未加载** | **重启服务进程**，复跑进程检查 |
| 磁盘 `--check` 退非 0 | 内容与版本清单对不上（I14） | 先 `bkn_version.py --write` 升版，再复验；**不可重试** |
| 进程检查退 2 | 无自证记录 / 文件缺失 / 自证降级 | 若是刚重启前 → 重启后自动生成；仍退 2 则查 `logs/.loaded_version.json` 与权限 |
| `changeset.py --check --strict` 退非 0（发布收尾） | 当前版本缺 changelog 锚行，或候选未 `applied` | 写锚行，再对账；**不可重试** |

---

*素材来源：scripts/bkn_version.py（docstring 与 `argparse`）、scripts/changeset.py（docstring）、
plugin/scripts/check_loaded_version.py（docstring 与 `main`）、plugin/loaded_version.py（docstring）；
数字 44 文件 = 40 `.bkn` + 4 `.md` 为本仓实算。本文件仅为 skill references，不改变生效树。*
