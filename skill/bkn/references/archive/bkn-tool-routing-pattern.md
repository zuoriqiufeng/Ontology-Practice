> 历史文档（已归档）
> 本文描述的是 `find_bkn.py` / `demo-product_bkn_router` 阶段的旧路由架构。
> 当前项目已迁移到 Hermes Plugin（10 个 Tool）查询 BKN，不再使用以下工具/脚本。
> 保留本文仅供追溯设计演进。

# BKN 路由工具化模式 (find_bkn.py)

> 将 BKN 路由判断从 Agent 推理链下沉到 Python 脚本

## 演进过程

### 阶段 1: Agent 脑内匹配 (已淘汰)

```
Agent 读 network.bkn 全文 → 在人脑/模型脑内做正则匹配 → 选文件 → 查BKN
```
问题：Agent 每次要读全文(100+行)，正则匹配依赖 Agent 推理能力，不稳定。

### 阶段 2: 路由 Skill 表 (已淘汰)

demo-product_bkn_router SKILL.md 内置路由表，Agent 加载 Skill 后看到路由信息。
问题：路由表仍在 prompt 中(60行)，Agent 仍需做匹配推理。

### 阶段 3: 工具下沉 (当前)

```python
# find_bkn.py 核心逻辑
def normalize(text):    # 同义词标准化: "挂了"→"异常", "重跑"→"重启"
def route(text):        # 正则路由匹配: 10级优先级 → 返回最佳 BKN 文件
def main():             # JSON 输出: {best: {file, method}, fallback}
```

Agent 只做一件事：`terminal("python3 find_bkn.py '<输入>'")`

## 收益

| 维度 | 之前 | 之后 |
|------|------|------|
| Agent 负担 | 读表 + 匹配 + 选文件 | 1 次 terminal |
| 上下文占用 | ~60行路由表常驻 | 不入上下文 |
| 同义词处理 | Agent 自己理解 | Python 脚本标准化 |
| 可测试性 | 无法验证 | 命令行直接测 |

## 关键设计决策

1. **同义词优先于路由**：先做标准化("挂了"→"异常")，再做正则匹配
2. **短变体防护**："ora" 不匹配 "Oracle" (内部包含且更短的变体跳过)
3. **JSON 输出**：结构化返回，Agent 直接解析，无需再做匹配
4. **fallback 机制**：无命中返回 `fallback:true`，Agent 不再查 BKN

## KWeaver 对比

| | find_bkn.py | KWeaver find_skills |
|------|-----------|-------------------|
| 触发 | Agent 手动调 terminal | ContextLoader 自动拦截 |
| 路由存储 | Python 正则 + 同义词字典 | BKN 图关系 (applicable_skill 边) |
| 变更方式 | 改脚本 | SQL UPDATE |
| 同义词 | Python 字典 | 未明确 |
| 方向 |"路由=工具" | "路由=图数据" |
