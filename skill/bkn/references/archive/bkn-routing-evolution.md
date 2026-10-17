> 历史文档（已归档）
> 本文描述的是 `find_bkn.py` / `demo-product_bkn_router` 阶段的旧路由架构。
> 当前项目已迁移到 Hermes Plugin（10 个 Tool）查询 BKN，不再使用以下工具/脚本。
> 保留本文仅供追溯设计演进。

# BKN 路由三阶段进化

> 2026-06-23 | Demo Product 实战验证

## 阶段一：路由在 Prompt 里 (network.bkn 表格)

```
Agent 读 network.bkn → 脑内正则匹配 → 手动选文件 → search_files
```

**问题**: 
- 每次需要读全文 network.bkn (~60行) 进上下文
- 正则匹配在 Agent 推理中，不可验证
- 同义词/变体表达依赖 Agent 自行理解
- 加一条路由规则 = 改 Markdown 表格

**Demo Product 案例**: 最初的 network.bkn 路由表，Agent 手动匹配。

## 阶段二：路由在工具层 (find_bkn.py)

```
Agent 调 terminal("find_bkn.py '<输入>'") → {best: {file, method}} → search_files
```

**改进**:
- 同义词标准化下沉到脚本 ("挂了"→"异常")
- 路由匹配可复现、可测试
- Agent 一条命令得到结果，不做推理
- 路由不改 Prompt，只改 Python 脚本

**Demo Product 案例**: `~/.hermes/demo-product/bkn/scripts/find_bkn.py` — 130行 Python，同义词映射 + 10级优先级路由。

**Skill 改造**:
- `demo-product_bkn_router` 从"路由表内联"瘦身为"调用 find_bkn.py"
- 操作 Skill 只保留专属 BKN 引用，通用路由委托给路由 Skill

**边界**:
- 路由失败仍依赖 Agent 回退
- 优先级冲突由 Agent 判断（工具只给排序，不给决策）

## 阶段三：路由即数据 (KWeaver find_skills)

```
Agent 调 find_skills(material, MAT-002) → [supplier_expedite] → builtin_skill_load
```

**质变**:
- 路由从"文本规则"升级为"图数据关系"
- `UPDATE materials SET bound_skill_id=...` → 秒级路由变更
- Agent Prompt 里零行业务路由分支
- Skill 注册、版本化、上下线独立于 Prompt

**参考**: KWeaver `examples/05-skill-routing-loop/`

## 当前定位

Demo Product 处于 **阶段二**。阶段三需要图查询引擎 + Skill 注册表，当前 Hermes 基础设施不支持。

阶段二已经是 Hermes 框架内最接近 KWeaver 数据治理理念的实现。
