> 历史文档（已归档）
> 本文描述的是 `find_bkn.py` / `demo-product_bkn_router` 阶段的旧路由架构。
> 当前项目已迁移到 Hermes Plugin（10 个 Tool）查询 BKN，不再使用以下工具/脚本。
> 保留本文仅供追溯设计演进。

# search_files `|` 交替符失效 & keyword 提取模式

> 发现: 2026-06-26, Demo Product BKN 路由优化

## 现象

```
search_files(pattern="Oracle|1521", path="file.bkn") → 0 结果 ❌
search_files(pattern="Oracle", path="file.bkn")       → 9 结果 ✅
search_files(pattern="1521", path="file.bkn")         → 2 结果 ✅
```

## 根因

search_files 底层 ripgrep 对正则交替符 `|` 处理有 bug。与文件编码无关。

## 通用解决方案: keyword 提取模式

路由工具（如 find_bkn.py）不仅返回文件路径，还从用户输入中**提取单关键词**:

```json
{
  "file": "objects/database.bkn",
  "method": "search_files",
  "keyword": "Oracle"    // ← Agent 用此值单关键词搜索
}
```

Agent 流程:
```
hit.keyword → search_files(pattern=hit.keyword, path=hit.file)
  ├── 命中 → 读 context 行
  └── 0 结果 → read_file(hit.file) 降级
```

## 实现

find_bkn.py:
- `KEYWORD_MAP`: 信号名 → 候选关键词列表
- `extract_keyword(signal, text)`: 从标准化文本取第一个匹配的关键词
- route() 输出增加 `keyword` 字段

## 适用

任何使用 find_bkn.py 式路由工具的 BKN 系统。关键词提取是通用模式，不限于 Demo Product。
