> 历史文档（已归档）
> 本文描述的是 `find_bkn.py` / `demo-product_bkn_router` 阶段的旧路由架构。
> 当前项目已迁移到 Hermes Plugin（10 个 Tool）查询 BKN，不再使用以下工具/脚本。
> 保留本文仅供追溯设计演进。

# BKN 路由工具化模式

> 将 BKN 路由判断从 Agent 推理链下沉到 Python 脚本
> Demo Product 落地实例: `~/.hermes/demo-product/bkn/scripts/find_bkn.py`

---

## 为什么需要路由工具化

### 问题

Agent 手动做路由有三个痛点：
1. **正则不统一**：每次在脑海中重新做正则匹配，容易遗漏
2. **同义词漏判**：用户说"挂了"、"重跑一下"，Agent 可能不识别
3. **上下文浪费**：路由表在 network.bkn 里，需要 read_file 全量才能做匹配

### 方案

把同义词标准化 + 信号路由封装成一个 Python 脚本：

```
用户输入 → terminal("python3 find_bkn.py '<输入>'")
  ↓ 同义词标准化
  ↓ 正则路由匹配 (10级优先级)
  ↓ 返回 {best: {file, method}, fallback: bool}
Agent → 按 best.file + best.method 查询 BKN
```

---

## 脚本架构

```python
# 1. 同义词映射 — 变体→标准词
SYNONYMS = {
    "异常": ["挂了", "报错", "出错", "失败", "不工作", "有问题", "error", "crash"],
    "重启": ["重新启动", "重跑", "再跑一下", "restart", "重新开始"],
    "停止": ["停掉", "停下", "关掉", "stop", "暂停"],
    "Oracle": ["oracle", "ora", "ORACLE"],
    "MySQL": ["mysql", "my", "mysqld"],
    "OB": ["OceanBase", "oceanbase", "ob"],
}

# 2. 路由规则 — 信号→文件 10级优先级
ROUTES = [
    (10, r'-40[16|31|46|71|73]|ABNORMAL|异常', "risks/risks.bkn", "search_files"),
    (9,  r'重启|启动|停止|删除|创建|修改|激活', "actions/prerequisites.bkn", "search_files"),
    (8,  r'Oracle|MySQL|PG|MSSQL|DM|DB2|OB|Redis', "objects/database.bkn", "search_files"),
    (6,  r'端口|字符集|权限|ulimit|JDK|SELINUX', "objects/env_matrix.bkn", "search_files"),
    (4,  r'iahelper|iatrack|iadumper|ialoader|iaproxy', "relations/topology.bkn", "search_files"),
    (3,  r'架构|部署|拓扑|进程矩阵|数据流', "relations/topology.bkn", "read_file"),
    (2,  r'是什么|定义|什么是|含义', "term.md", "search_files"),
]

# 3. 返回 JSON
{
  "input": "ora库挂了",
  "normalized": "ora库异常",
  "hits": [{"priority":10, "signal":"异常", "file":"risks/risks.bkn", "method":"search_files"}],
  "best": {"priority":10, ...},
  "fallback": false
}
```

---

## Agent 集成

### Skill 层：demo-product_bkn_router

````markdown
## 路由工具

terminal("python3 ~/.hermes/demo-product/bkn/scripts/find_bkn.py '<用户输入>'")

返回 JSON:
  fallback=true  → 不查 BKN，直接执行 Skill
  method=search_files → search_files(best.file, keyword)
  method=read_file    → read_file(best.file)
````

### Agent 流程

```
用户: "ora库挂了"
  → terminal("python3 find_bkn.py 'ora库挂了'")
  → {best: {file:"risks/risks.bkn", method:"search_files"}}
  → search_files("-4073", path="risks/risks.bkn", context=5)
  → 返回诊断链路
```

---

## 调用成本

| 方式 | 调用 | Token | Agent 操作 |
|------|------|-------|----------|
| 手动读 network.bkn | read_file ×1 | ~100行 | 读全文 + 脑海匹配 |
| find_bkn.py 工具 | terminal ×1 | 0 (不入上下文) | 读 JSON 结果 |

---

## 同义词设计原则

1. **长匹配优先**：变体按长度降序排列，"重新启动" 优先于 "重启"
2. **标准词保护**："ora" 不误替换 "Oracle" 中的 "ora"（添加长度守卫 `len(v) < len(standard)` 时跳过）
3. **中英文通用**：变体中英文混排，同时覆盖
