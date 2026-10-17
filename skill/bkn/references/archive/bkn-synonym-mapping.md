> 历史文档（已归档）
> 本文描述的是 `find_bkn.py` / `demo-product_bkn_router` 阶段的旧路由架构。
> 当前项目已迁移到 Hermes Plugin（10 个 Tool）查询 BKN，不再使用以下工具/脚本。
> 保留本文仅供追溯设计演进。

# BKN 同义词映射

> 来源: Demo Product BKN 路由实战 (2026-06-23)
> 解决问题: 用户变体表达（"挂了"/"重跑"/"ora库"）→ BKN 路由漏匹配

## 问题

BKN 路由表用精确关键词匹配用户输入。用户说"ora库挂了"时：
- "挂了" 不匹配 "ABNORMAL"
- "ora" 不匹配 "Oracle"  
- 同义词/缩略语/口语化表达全部漏掉

## 方案：路由前先标准化

```
用户输入 → 同义词映射表 → 标准化文本 → 路由匹配
```

### 映射表结构

```python
SYNONYMS = {
    "标准词": ["变体1", "变体2", ...],
    "异常":   ["挂了", "报错", "出错", "失败", "不行", "error", "crash", "坏了"],
    "重启":   ["重新启动", "重跑", "再跑一下", "restart", "重新开始", "再启"],
    "Oracle": ["oracle", "ORACLE", "ora"],
    "MySQL":  ["mysql", "my", "mysqld"],
    "OB":     ["OceanBase", "oceanbase", "ob"],
}
```

### 关键设计决策

1. **长变体优先匹配**: 先匹配"重新启动"再匹配"重启"，防"重启"被前缀匹配
2. **短变体保护**: 如果变体是标准词的子串且更短（如 "ora" 是 "Oracle" 的子串），**跳过不匹配**
3. **Case-insensitive**: 全部大小写不敏感匹配
4. **正则替换**: 纯字符串替换，不需要 NLP/LLM

### 防护案例

```
输入: "Oracle 同步到 OB"
  → "Oracle" 是标准词本身 → 不变
  → "OB" 匹配变体 → 替换为 "OceanBase"
  → 输出: "Oracle 规则到 OceanBase"

输入: "ora库挂了"  (ora=Oracle变体, 挂了=异常变体)
  → "ora" 长度3 < "Oracle"长度6, 且 "ora" in "Oracle" → 跳过
  → "挂了" → 替换为 "异常"
  → 输出: "ora库异常"  (ora 没被错误替换)
```

注意: "ora" 没被翻译为 "Oracle" 是**故意的**——如果翻译了会导致 "ora库" → "Oracle库"（不自然）。路由表中 `Oracle` 正则本身匹配 `\bOracle\b|\bora\b` 即可。

## 与路由工具的集成

在 `find_bkn.py` 中作为第一步：

```python
def normalize(text: str) -> str:
    for standard, variants in SYNONYMS.items():
        for v in sorted(variants, key=len, reverse=True):
            if v.lower() in standard.lower() and len(v) < len(standard):
                continue  # 防短变体误伤标准词
            text = re.sub(re.escape(v), standard, text, flags=re.IGNORECASE)
    return text
```

## 适用范围

- **适合**: 操作动词、状态词、数据库名、组件名 — 这些词有有限的、已知的变体
- **不适合**: 自由文本、规则名 — 这些可以包含任意字符，无法枚举
