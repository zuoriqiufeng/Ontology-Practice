# BKN 更新工作流

> 来源: <repo>/demo-product-bkn/update/
> 23 号方案：本体层只留定义/关系/实例登记；值数据（版本表/矩阵/命令/参数）下延 Skill references，路由下延 Tool 常量。

## 三层更新规则

| 变动类型 | 改 BKN | 改 Skill | 改 Plugin | 生效方式 |
|---------|:--:|:--:|:--:|:--:|
| 新增操作 (加 capability) | ✅ actions/ + relations | ✅ 加 SKILL.md | — | 重启服务进程 |
| 改脚本路径/环境 | — | ✅ | — | — |
| SDK 版本升级 | — | ✅ notes | — | — |
| 新增约束/风险 | ✅ risks/ + relations | — | — | 重启服务进程 |
| 新增错误码/症状 | ✅ `relations/process_topology.bkn` 补边 + `plugin/constants.py` 别名常量 + `plugin/error_semantics.yaml` 码含义规则（25 号：BKN 不建清单） | — | ✅ 常量 | 重启服务进程 |
| 新增兼容性/版本数据 | ❌ 不下延进 BKN — 写 `skill/<负责 skill>/references/*.md`（值数据；本体只留指针） | ✅ | — | — |
| 新增对象类型 | ✅ objects/（定义段 KV + 实例登记表，禁说明性表格） | — | — | 重启服务进程 |
| 新增场景 | ✅ `objects/scenario-<id>.bkn`（entity 段）+ `relations/scenario.bkn` | — | — | 重启服务进程 |
| Plugin 代码升级 | — | — | ✅ | 重启 Hermes |

> 改 `.bkn` 后须**重启服务进程**：`reload.py` 只重建执行它的短命进程的全局，常驻服务不生效。

## 生效方式

改 `.bkn` 后须**重启服务进程**（`plugin/scripts/reload.py` 只重建执行它的短命进程的全局，常驻服务不生效）：

```bash
# 重启常驻服务进程（具体命令见部署方式）
```

## 新增操作完整流程

1. 编辑 BKN `actions/xxx_lifecycle.bkn` — 追加 Action 条目
2. 编辑 BKN `relations/` — 追加 Object→Action（references.bkn）和 Action→Skill（action_routing.bkn）关系
3. 编辑 Skill `SKILL.md` — 追加 capability 的 script/command/env；Skill 语义 ID 登记进 `plugin/skill_manifest.yaml`
4. 重启服务进程生效（`reload.py` 对常驻服务不生效）
5. 验证: `resolver.lookup_operation("new_capability")`
