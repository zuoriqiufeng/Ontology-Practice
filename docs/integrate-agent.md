# 接入 Agent

## 形态

`plugin.tools.HANDLERS` 是一个 `name -> callable` 的映射（13 个工具）。任何 Agent 框架只要能把
「工具名 + JSON 参数」路由到 Python 函数，就能接入；`plugin/schemas.py` 里有每个工具的 JSON Schema。

```python
from plugin.tools import HANDLERS, _init
_init()                                  # 解析 BKN、装配规则（一次）
out = HANDLERS["resolve_relation"]({"source_entity": "worknode", "relation_type": "runs_on"})
```

## 配置

`plugin/config.yaml`：

| 键 | 说明 |
|---|---|
| `bkn.root` | 本体根目录（相对 `plugin/` 或绝对路径） |
| `tools.enabled` | 只启用部分工具（空 = 全部） |
| `search.*` | 检索后端的预算与阈值（可选 Qdrant） |
| `output_max_chars` | 单次输出预算（防一次性灌爆上下文） |

## 降级

没有 Qdrant/嵌入模型时：检索退化为关键词/BM25；`resolve_relation`、`diagnose_error` 等**基于本体边**的工具不受影响。

## 可观测

每次调用写一条轨迹（`logs/trajectories/*.jsonl`）：`mention_resolve`（提及解析）、`reasoning_path`（推理路径）、
`answer_source`（答案来自本体边/侧车/外部文档）。没有 `task_id` 的调用不落盘（避免探针污染）。

## 不要把命令塞进本体

工具只返回「做什么、看哪、找谁」；具体命令由 Skill 提供。见 `spec/06-bkn-vs-skill.md`。

