# BKN 模板目录

> 新建 .bkn 文件时从对应模板复制开始，替换 `[占位符]`。
> 模板已对齐当前规范：frontmatter（objects）、约束ID（risks）、中文名（relations）、`<!-- type: -->` 块标注。
> 写完运行 `python3 plugin/scripts/lint_bkn.py` 验证合规。

## 模板清单

| 模板 | 适用场景 | 输出位置 |
|------|---------|---------|
| `object.bkn` | 新增对象（业务对象 / 进程对象 / 主机 / DB 对象 / 注册集） | `bkn/objects/` |
| `relation.bkn` | 新增关系段 | 追加到 `bkn/relations/` 对应域文件 |
| `action.bkn` | 新增可执行动作 | 追加到 `bkn/actions/` 生命周期文件 |
| `risk.bkn` | 新增风险约束 / 前置维度 | `risks/constraints.bkn` 表格行（示例见 `examples/example-product/`） |
| `error.bkn` | 新增错误码/症状（25 号：**不建清单**——补 `suspected_in` 边 + `plugin/constants.py` 别名） | 无新段（见模板内同步动作） |
| `scenario.bkn` | 新增业务场景 | `bkn/objects/scenario-<id>.bkn`（`scenario-` 前缀，24 号） |

## 使用方式

```bash
# 新增 Object
cp bkn/templates/object.bkn bkn/objects/new_object.bkn
# 编辑替换占位符，然后:
python3 plugin/scripts/reload.py
python3 plugin/scripts/lint_bkn.py
```

## 边界铁律（模板已遵守，填充时不得破坏）

- **段类型白名单 4 种**（`entity`/`action`/`risk`/`relation`，= KWeaver 四元；26 号）——历史类型已全部退场：`index`/`matrix`（23 号废止）、`symptom`/`class`（24 号退役）、`scenario`（26 号归档为 entity；`scenario:` 命名空间保留供边引用）
- **定义段内只允许三类载荷**：KV 属性列表、**实例登记表**（行首带命名空间 ID，或段内声明 `> 行 = <注册集> 实例`）、定义性散文（限长 ≤3 行）
- **说明性表格一律下延**：值数据 → Skill references；路由 → Tool/`skill_manifest.yaml`；全量知识 → Qdrant；叙述 → `doc/`
- BKN 只写思路/约束/Skill 指针；具体命令、参数值、SQL 由 Skill 提供
- implements 绑定只出现在 `actions/*.bkn` 与 `relations/action_routing.bkn`
- 类型字段一律用 `bkn/SCHEMA.md` 枚举
