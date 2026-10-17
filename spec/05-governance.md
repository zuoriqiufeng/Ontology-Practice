# 05 · 治理模型：候选 · 门禁 · 版本 · 回滚

> 目标：**优化产物不就地生效**。任何改动先进待审区，过门禁、经审批，才允许落盘。

## 5.1 候选（pending）

```
doc/optimize/pending/C-YYYYMMDD-NN/
├── candidate.json   # 元数据：假设、证据、改动清单、门禁、回滚方式
├── review.md        # 人读评审：定位、逐件改法、风险
└── payload/         # 全量文件快照（不是 diff）
```

`candidate.json` 的关键字段：`status`（pending/applied/rejected/superseded）、`evidence`（每条带可定位 `ref`）、`changes`、`gates`、`rollback`。

## 5.2 审批与落盘

1. `approve` 写入账本 `ledger.jsonl`：`by`（审批人原话）、`payload_hash`；
2. `pending_apply` 校验（status ＋ 账本审批 ＋ 哈希）后复制 payload、备份到 `.pre-apply/`；
3. 落盘后自动跑门禁；失败**自动回滚**。

## 5.3 版本

- 本体版本 = **文件清单的哈希**（内容一变，版本必变）；
- 版本记录在 `bkn-version.json`，发布条目在变更日志；
- 机器检查：内容与清单一致；变更集与发布记录一致。

## 5.4 门禁（gate）

| 道 | 检查 | 通过标准 |
|---|---|---|
| ① 结构 | lint（段类型/必填/引用/命名空间/码与命令越界） | errors = 0 |
| ② 回归 | pytest | 全绿 |
| ③ 结构量 | 节点/边/关系类型只增不减 | 不劣化 |
| ④ 基线 | 置信度/输出体积对比 | 不劣化 |
| ⑤ 回放 | 案例回放 | 不更差 |

## 5.5 可观测

事件流（每次调用一条轨迹）：`mention_resolve`（提及如何被解析）、`reasoning_path`（推理走了哪条轴/几跳/终止原因）、`answer_source`（答案来自本体边/侧车/外部文档）。
据此可回答：**本体这次真的起作用了吗**。

## 5.6 别名与码：数据化而非写死

- 别名是**数据**（`plugin/aliases.yaml`，带 provenance），只收「不可生成」的等价说法；
- 码的机械变体由形态解析生成 + 码表校验，**不写 per-code 别名**；
- 未命中先聚类出候选 → 人审 → 写数据；不猜。

