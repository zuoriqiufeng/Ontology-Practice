# demo-product-bkn Plugin · 部署与使用文档

> Hermes Plugin: Demo Product 业务知识网络查询引擎
> 13 个 Tool 提供产品/架构/方案/兼容/运维/向量检索全维度知识查询

---

## 部署

### 前置条件

- Hermes Agent ≥ 1.0
- Python 3.9+（`from __future__ import annotations` 兼容）
- BKN 文件已生成: `<repo>/demo-product-bkn/bkn/` (**46 个 `.bkn` 文件（40 本体 + 6 模板）**)
- 依赖: `qdrant-client`、`sentence-transformers`、`jieba`、`PyYAML`、`numpy`、`scipy`

### 安装

```bash
# 方式1: 创建软链到 Hermes plugins 目录
ln -s <repo>/demo-product-bkn/plugin ~/.hermes/plugins/demo-product-bkn

# 方式2: 直接复制
cp -r <repo>/demo-product-bkn/plugin ~/.hermes/plugins/demo-product-bkn

# 方式3: 指定 BKN 路径 (如果 BKN 不在默认位置)
export DEMO-PRODUCT_BKN_ROOT=/path/to/bkn
```

### 验证安装

```bash
# 重启 Hermes 后
hermes plugins list | grep demo-product-bkn

# 或在对话中测试
hermes chat -q "Demo Product 支持 Oracle 同步到 OceanBase 吗"

# 检查 BKN 能否加载 (从项目根目录执行)
cd /path/to/demo-product-bkn
python3 -c "from plugin.resolver import BKNResolver; r = BKNResolver(); print(len(r.cache), 'files')"
```

### 配置 BKN 路径 + Qdrant

插件从 `config.yaml` 读取配置，完整字段说明见 `../doc/build/demo-product-bkn/41-config_reference.md`。

```yaml
# config.yaml
qdrant:
  host: localhost
  port: 6333
  collection: demo-product_collection       # 主检索集合

embedding:
  mode: local                          # local | api
  model_name: BAAI/bge-large-zh-v1.5   # 本地 BGE 模型 (1024 维)

search:
  top_k: 5
  score_threshold: 0.3
  hybrid: true                         # BM25 + BGE RRF 混合搜索
  fallback_on_bkn_none: true           # BKN 无数据时自动回退 Qdrant
  fallback_on_bkn_partial: true        # BKN partial 时也回退 Qdrant
  defer_to_hermes: true                # v3.0: 返回 gaps + instruction，让 Agent 自主调用 search_qdrant
  bm25_fallback_score: 0.1             # v3.3: dense 全失败时 BM25-only 兜底
  bm25_precision_guard: true           # v3.4: 精确项缺失时触发 exact + BM25 兜底
```

环境变量覆盖 (优先级更高):
```bash
export QDRANT_HOST=192.0.2.100
export QDRANT_PORT=6333
export QDRANT_COLLECTION=demo-product_collection
export DEMO-PRODUCT_BKN_ROOT=/path/to/bkn
```

Qdrant 搜索策略:
- **默认 hybrid=true**: BGE dense (语义) + BM25 sparse (关键词) → RRF 融合
- **hybrid=false**: 仅 BGE dense 向量搜索
- BGE 擅长自然语言描述 ("数据同步延迟高怎么排查")
- BM25 擅长精确匹配 ("-4073" "Oracle" "OceanBase")
- RRF 融合: `score = 1/(60 + rank_bge) + 1/(60 + rank_bm25)`
- BGE Precision Guard: 查询含 `-4073` / `ORA-00001` 等精确项但 BGE 未命中时，先走 `_exact_index` 再与 BM25 合并

回退机制:
- BKN confidence=none → 自动 Qdrant 混合搜索
- BKN confidence=partial → 默认也回退 (可配置)
- `defer_to_hermes=true` 时返回 `_search_deferred` + `_instruction`，同时内部仍执行 Qdrant fallback 并写入 `enrichment`/`fallback_hint`
- Qdrant 不可用 / Embedding 模型不可用 → 降级为 REST scroll 全表扫描

---

## 使用

### 13 个 Tool 速查

| Tool | 用途 | 示例 |
|------|------|------|
| `query_product` | 产品定位/竞品对比 | "Demo Product 和 OGG 有什么区别" |
| `explain_architecture` | 技术原理 | "增量同步是怎么实现的" |
| `design_solution` | 方案设计 | "Oracle 迁移到 OceanBase" |
| `check_compatibility` | 兼容性检查 | "Oracle 能同步到 TiDB 吗" |
| `list_scenarios` | 场景发现 | "有哪些大数据方案" |
| `diagnose_error` | 错误诊断 | "-4073 是什么错误" |
| `get_prerequisites` | 前置检查 | "创建规则前需要做什么" |
| `resolve_relation` | 关系查询 | "syncrule 有哪些关联对象" |
| `resolve_operation` | 能力映射 | "创建规则用哪个 Skill" |
| `search_qdrant` | 向量检索兜底 | "search_qdrant(query='-4073 处理方案')" |
| `diagnose_db_link` | 链路诊断路由 | "增量同步卡住了怎么办" |
| `check_action_risk` | 动作风险自查 | "规则 RUNNING 时能直接删除吗" |
| `diagnose_mechanism` | 机制归因 | "增量卡住背后是什么机制" |

### 典型对话

```
用户: Oracle 迁移到 OceanBase 怎么做?

模型:
  ① check_compatibility("Oracle", "OceanBase")
     → supported: true, archivelog: required

  ② design_solution("Oracle", "OceanBase")
     → scenario: 跨平台迁移
     → topology: 单向复制, 远程部署点位3
     → steps: 环境准备→节点部署→规则配置→全量→增量
     → risks: -4073, 脏数据, FULLSYNC卡住

  ③ get_prerequisites("create_rule")（库差异化配置由负责 Skill 补充）
     → 激活节点 → 注册源库 → 注册目标库 → 开启归档...

  ④ 模型基于①②③输出完整方案
```

```
用户: 帮我创建一条 Oracle→OceanBase 的同步规则

模型:
  ① resolve_operation("创建同步规则")
     → capability: create_sync_rule
     → implements: skill:demo-product-rule-manager
     → params: rule_name, src_db_uuid, tgt_db_uuid
     → constraints: 源端NORMAL, 目标端NORMAL, dry-run first

  ② skill_view("demo-product-rule-manager")
     → script, workdir, env, command_template

  ③ terminal(rule_create.py --dry-run --rule-name X ...)
     → 用户确认 → terminal(去掉 --dry-run)
```

### BKN 数据不充分时

插件自动降级:
1. `assess_confidence()` 标记 gaps，写入 `gap_log.jsonl`
2. `fallback_to_qdrant()` 触发 Qdrant 混合搜索，结果写入 `enrichment` / `fallback_hint`
3. `defer_to_hermes=true` 时额外返回 `_search_deferred` + `_instruction`，供 Agent 自主调用 `search_qdrant`
4. 定期执行 `scan_gaps.py` 生成 `gaps_report.md`，反哺 BKN

---

## 维护

### 更新 BKN 文件

```bash
# 编辑 BKN 文件
vim <repo>/demo-product-bkn/bkn/objects/product.bkn

# 热重载 (只作用于执行它的进程；常驻服务需重启，见 ../skill/bkn-release/references/release-flow.md §3.2)
cd /path/to/demo-product-bkn
python3 -m plugin.scripts.reload
```

### 查看 BKN 缺失清单

```bash
cd /path/to/demo-product-bkn
python3 -m plugin.scripts.scan_gaps
# 输出: gaps_report.md
```

### 文件结构

```
demo-product-bkn/
├── bkn/                     BKN 文件 (46 个：40 本体 + 6 模板)
│   ├── objects/ actions/ risks/ relations/
│   ├── SCHEMA.md / SKILL.md / SYNONYMS.md   规范件
│   └── templates/           新增内容模板
│
└── plugin/                  Plugin 实现
    ├── plugin.yaml          清单 (13 个 Tool)
    ├── config.yaml          Qdrant/Embedding/BKN 配置
    ├── CLAUDE.md            开发协作指南
    ├── __init__.py          注册入口
    ├── schemas.py           13 Tool Schema
    ├── tools.py             13 Handler + _wrap()
    ├── resolver.py          BKN 加载引擎
    ├── relations.py         关系图遍历
    ├── context_loader.py    Trim+Toon
    ├── supplement.py        补充机制 + Qdrant 搜索
    ├── bm25.py              BM25 检索 + RRF 融合
    ├── constants.py         DB 列表/别名/噪声变体
    └── scripts/
        ├── reload.py        热重载
        └── scan_gaps.py     缺失扫描
```

---

## 常见问题

**Q: 插件加载失败?**
```bash
# 检查 BKN 文件是否存在
ls <repo>/demo-product-bkn/bkn/
# 检查插件模块能否导入 (从项目根目录执行)
cd /path/to/demo-product-bkn
python3 -c "from plugin import tools; tools._init(); print('OK')"
```

**Q: Tool 返回空数据?**
- BKN 文件对应 section 是否存在
- 操作名是否匹配 (可用 `resolver.list_operations()` 查看)
- 检查 `gap_log.jsonl` 中的 confidence/gaps

**Q: Qdrant 回退不工作?**
```bash
# 检查 Qdrant 服务
curl http://localhost:6333/collections
```

**Q: 如何添加新操作?**
```bash
# 1. 编辑 BKN actions/*.bkn, 添加新 Action
vim <repo>/demo-product-bkn/bkn/actions/xxx.bkn

# 2. 热重载
cd /path/to/demo-product-bkn
python3 -m plugin.scripts.reload

# 不需要改 Plugin 代码
```

---

## 更多文档

- 架构与数据流: `../doc/build/demo-product-bkn/01-architecture.md`
- 每个 Tool 的 Schema/Handler/返回契约: `../doc/build/demo-product-bkn/31-tools.md`
- 模块职责、类/方法、调用流程: `../doc/build/demo-product-bkn/30-modules.md`
- Confidence-Gaps-Supplement 机制: `../doc/build/demo-product-bkn/32-supplement.md`
- Trim + Toon 上下文压缩: `../doc/build/demo-product-bkn/33-context_loader.md`
- BKN 数据模型: `../doc/build/demo-product-bkn/24-bkn_ontology.md`
- 配置参考: `../doc/build/demo-product-bkn/41-config_reference.md`
- 关键约束: `../doc/build/demo-product-bkn/10-design_constraints.md`
- 设计规则清单: `../doc/build/demo-product-bkn/11-design_rules_checklist.md`
- 部署与验证: `../doc/build/demo-product-bkn/40-build.md`
- 变更检查单: `../doc/build/demo-product-bkn/42-review_checklist.md`
- 数据库诊断工具集成: `../doc/build/demo-product-bkn/21-db_diagnostics_integration.md`
