# ⑩ 本体结构合规（P0′）— 机检维度

> **唯一不需要人工标注、不需要造用例的维度**：跑现成门禁看退出码。
> 它回答的不是「知识答得对不对」，而是「**骨架立不立得住**」——结构坏了，其余 9 个维度的分数都没有意义。
> 权威机器：`plugin/scripts/lint_bkn.py`（**32 项**检查）、`scripts/gate.sh`（四道门）、`scripts/bkn_version.py`、`plugin/scripts/graph_metrics.py`。

## 评判标准

| 指标 | 阈值 | 含义 |
|------|:---:|------|
| lint 错误数 | **= 0** | 形式违规（段类型 / 引用 / 命名空间 / 禁项…） |
| lint 警告数 | 0（推荐） | 存量债；新增不得带来新警告 |
| 门禁道数 | **4 / 4** | 见「测试方法」 |
| 结构量 | **只增不减** | 节点 / 边 / 关系类型数不得低于基线（`plugin/baselines/graph.v3.json`） |
| 版本身份 | **一致** | `bkn-version.json` 的 sha256 与磁盘一致（`bkn_version.py --check`） |
| 退场词 | **0** | 五层 / L1–L5 / `index`·`matrix`·`symptom`·`class`·`scenario` 段类型 / `diagnostics/` / 12 种关系 |
| 裸错误码 | **0** | `.bkn` 内不得出现裸码（Q27：码不进任何一层） |
| 元信息 | **0** | 不得有 `> 来源:` / `source_doc` / 解释性表格（零冗余 / 零元信息原则） |

## 测试方法

```bash
cd <repo>/demo-product-bkn

# 第 1 道：BKN 结构 lint（32 项）
python3 plugin/scripts/lint_bkn.py --error-only     # 期望 EXIT=0，errors=0

# 第 2 道：回归测试（含类层次 / 方向层 / 边语义）
python3 -m pytest plugin/tests -q                   # 期望全绿

# 第 3 道：结构量与基线比对（只增不减）
python3 plugin/scripts/graph_metrics.py             # 期望 nodes=198 edges=211 relation_types=29

# 第 4 道：版本身份
python3 scripts/bkn_version.py --check              # 期望 EXIT=0

# 一键四门（推荐，CI / 发版前必跑）
bash scripts/gate.sh
```

### 反向注入（证明门禁真的会报，而不是「恰好没违规」）

```bash
# 取一份副本，注入一类违规，断言对应检查命中
cp -r bkn /tmp/bkn-probe
# ① 加一个退场段类型 → _check_retired_terms 应报 error
# ② 写一个不存在的 ref → _check_ref_resolution 应报 error
# ③ 引一个未声明的边类型 → _check_relation_declaration_completeness 应报 error
# ④ 动作文件 constraints: 与 constrained_by 边不一致 → _check_constraint_edge_alignment 应报 error
python3 plugin/scripts/lint_bkn.py --root /tmp/bkn-probe
```

**为什么必须做反向注入**：只跑「零违规」无法区分「检查有效」与「检查没接上」——本体侧已有过一次实例（`reverse_ok` 声明了却没有消费者，见 24 号 §3.4 缺陷 R-1）。

## 预期输出样例

```
$ python3 plugin/scripts/lint_bkn.py --error-only
errors=0  warnings=0  infos=0
EXIT=0

$ python3 plugin/scripts/graph_metrics.py
nodes=198  edges=211  relation_types=29  ingraph_sections=30  constrained_by=28
```

## 执行频率

| 时机 | 跑什么 |
|------|--------|
| 每次改 `.bkn` / Plugin 代码后 | 第 1 + 2 道（lint + pytest） |
| 每次发版 / 合批前 | **四道全跑**（`bash scripts/gate.sh`） |
| 每月结构审计 | 第 3 道 + 反向注入抽 1 类 |

## 边界（这个维度**不**证明什么）

- 不证明知识正确——只证明**形式合规、引用可解析、结构没缩水**；
- 不证明推理能力——能力边界见 `doc/capability/ontology-inference.md`；
- 结构量「只增」是**下限**而非目标：不鼓励为凑数加节点（02 号第八条）。
