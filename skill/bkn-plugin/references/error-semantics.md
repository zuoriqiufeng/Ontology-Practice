# 码 → 含义（`plugin/error_semantics.yaml`）

> **权威文件只有一份**：`plugin/error_semantics.yaml`。本页是说明。

## 0. 一句话

**码只作入口，不是知识**（用户裁定 Q27）。含义由**日志消息文本**决定，落入 **8 个有界语义类别**。

## 1. 为什么不能穷举码

- 错误码空间**无上界**——所谓「全部错误码」只是当时手里那张表；
- 线上实测（2026-10-13，`<data>/public/log-mode`）：`LP-*.json` 共 **83 条**、**71 个不同码**，其中 **34 条 `error_codes` 为空** —— 码本身就不是稳定入口；
- `plugin/scripts/lint_bkn.py::_check_no_bare_error_codes` 会把 `.bkn` 里的裸码报 **error**。

⇒ **码不进任何一层**：不建类、不建段、不做风险表条目、不建表。

## 2. 8 个有界语义类别

**8 类 = 7 条规则 + 1 条兜底**；判定**按文件顺序，首位命中即返回**（先具体后泛化）。

| 类别 | 典型消息特征（摘自 `error_semantics.yaml` 的 `match`） |
|---|---|
| `dimension:log_readable` | 归档 / redo / binlog / WAL / 位点 / 复制槽 / 位点不连续 |
| `dimension:state_machine` | RUNNING / ABNORMAL / FULLSYNC / 状态不允许 / 重启 |
| `dimension:permission` | 权限 / 授权 / 密码 / insufficient privileges / 用户不存在 |
| `dimension:connectivity` | 监听 / TNS / 连接失败 / 超时 / 网络 / 端口 / 防火墙 / 离线 |
| `dimension:resource` | No space / 磁盘满 / 内存 / OOM / ulimit / too many open files / 堆积 |
| `dimension:consistency` | 不一致 / unique constraint / cannot insert NULL / 字符集 / 数据类型 / 字典 |
| `dimension:time_sync` | 时间同步 / 时钟 / clock skew / NTP / 时区 |
| `dimension:unknown` | **都不命中就是它** —— 如实说不知道，不许猜（走检索 + `gap_log`） |

## 3. 推理链路

```
码 (+ 日志消息文本) → classify_error_message() → dimension:*
    ├── diagnosed_by → skill:*   （该查哪个 Skill）
    └── observed_in  → log:*     （该看哪个日志）
```

- **未给消息文本** → 返回 `dimension:unknown` 并把「需要消息文本」写进 `needs`；
- **未给 `log_source`** → **不猜**嫌疑进程（空列表 + `needs`）；
- 类别再落到 `bkn/objects/dimensions.bkn` 的 8 个维度类上（本体侧只认这 8 个）。

## 4. 怎么加规则

| 关 | 要求 |
|---|---|
| **有界** | 归入既有 8 类之一 —— **不新增类别**（新增类别要过准入四关） |
| **有据** | 必须有真实**日志消息原文**样例，写进规则的 `sources` |
| **命中方式** | 用**消息文本特征**命中，不用码 |

## 5. 与检索的分工

本体（本文件）只说「**查哪一类**」；「这一类里有哪些真实案例」由检索侧回答 ——
`store:log_patterns_collection`（身份见 [skill-manifest.md](skill-manifest.md)）。
语料**不进 `.bkn`**（第八条：本体只装机器拿不到、且能纠正直觉的知识）。
