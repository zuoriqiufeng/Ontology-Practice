# 维护规定：与内部工程仓的同步

> 本仓是内部工程仓的**开源投影**。内部仓（私有）是实践的一手现场；本仓只发布「可公开的绿名单」。
> 所有同步动作由 `tools/sync_from_internal.py` 执行，**默认 dry-run**，落盘前必须人工审 diff。

## 1. 方向：单向为主

- **内部 → 本仓（默认）**：日常同步。
- **本仓 → 内部（例外）**：外部 PR / 本仓修复若对内部也有价值，按「候选」或直改落内部，并在内部账本记一笔；不要反向整仓同步。

## 2. 同步范围（白名单）

| 同步（自动） | 人工维护（不自动同步） |
|---|---|
| `plugin/*.py`、`plugin/*.yaml`、`plugin/baselines/*.json`、`plugin/scripts/` | `plugin/skill_manifest.yaml`、`plugin/config.yaml`（本仓是空模板） |
| `scripts/`（lint/版本/变更集/门禁/待审/回放） | `plugin/tests/` 的**新增**文件（新测试需人工决定去留） |
| `skill/bkn*`（7 个通用 skill） | `bkn/` 骨架（SCHEMA/SYNONYMS/SKILL/templates/prerequisites，人工策展） |
| — | `spec/`、`docs/`、`README*`、`LICENSE/NOTICE`、`pyproject.toml`、`.github/`、`tools/` |

## 3. 去产品化改写（同步时自动执行）

| 内部 | 本仓 |
|---|---|
| 产品名 `i2Stream` / `i2stream` / `I2Stream` | `Demo Product` / `demo-product`（`.py` 内标识符用 `demo_product`） |
| 控制台 `i2UP` / `i2up` | `Demo Console` / `demo-console`（`I2UP_API_HOST` → `DEMO_CONSOLE_API_HOST`） |
| `/hdd/demo/public/i2stream-bkn` 等内部路径 | `<repo>` / `<data>` / `<tmp>` |
| `<local-path>`、`/root/.hermes` | `<repo>`、`~/.hermes` |
| 内网 IP | `192.0.2.x`（TEST-NET-1） |
| `BUG-NNNN` 内部编号 | `CASE-NNNN` |
| `doc/build/.../bkn-changelog.md` | `CHANGELOG.md` |

## 4. 四道闸（同步结束自动跑）

1. `lint --error-only --bkn-root bkn` 与 `--bkn-root examples/example-product/bkn` 均 **rc=0**；
2. `pytest -q` 全绿；
3. `redact.py` 五类命中 **0**（产品名/厂商/内网 IP/邮箱/内部痕迹）；
4. **内部引用扫描**：`doc/optimize/`、`/hdd/demo`、`doc/build/demo` 的新增命中为 0。

已知债务（存量内部引用）记在 `tools/internal-refs-baseline.txt`（当前 **58 文件**）——闸门只对**新增**失败；
燃尽规则：改到哪个文件就顺手清掉它的内部引用，并从基线删一行。

## 5. 执行步骤

```bash
python3 tools/sync_from_internal.py --source <内部仓路径>              # 1) dry-run，审清单
python3 tools/sync_from_internal.py --source <内部仓路径> --apply      # 2) 写入 + 四道闸
git diff --stat                                                       # 3) 人工审
git commit -am "sync: <一句话摘要>"                                   # 4) 提交（见 §6）
git push origin main
```

删除同步：`--apply --prune --yes`（只删同步集里已不存在的文件，不含 `plugin/tests/`）。

## 6. 提交与版本

- 提交信息：`sync: <摘要>`；必要时附「来自内部候选 `<C-YYYYMMDD-NN>`」。
- `CHANGELOG.md` 加一行（日期 / 同步内容 / 是否影响行为）。
- 版本：修 bug → PATCH；新增工具或规则 → MINOR；破坏性变更 → MAJOR；**发布前必须同步一次并重打 tag**。

## 7. 频率与审计

- 触发：内部候选 `applied` 之后；每次对外发布之前。
- 每季度审计一次白名单与 `LOCAL_OVERRIDES`（当前 1 个文件：`skill/bkn-intake/references/preprocessing.md`）。

## 8. 回滚

- 同步提交是独立 commit ⇒ `git revert <sha>` 即可整体回退；
- 若只错一件：`git checkout <sha>~1 -- <path>` 后重提。

