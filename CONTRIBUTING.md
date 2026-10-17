# Contributing

## 环境

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

Python ≥3.9。`qdrant-client`/`sentence-transformers` 属可选项；缺失时运行时自动降级（关键词检索），lint 与门禁不受影响。

## 提交前（等价于 CI）

```bash
python -m plugin.scripts.lint_bkn --error-only plugin/bkn   # 本体结构 lint，errors 必须为 0
python -m pytest -q                                        # 全绿
python3 tools/redact.py --root . --report /tmp/redact.md   # 敏感扫描，五类必须为 0
```

## 改动纪律

1. **本体（`bkn/`）与运行时（`plugin/`）分离**：本体只写语义与指针，命令/参数/阈值归 Skill。
2. **新增本体元素先论证**：新命名空间/新轴/新关系类型需要一份说明（为什么不能由既有元素推导）。
3. **可推就写、不能推就删**：没有消费者的声明不入库。
4. **文档引用纯文本路径**（不写跨文档 markdown 链接），保证渲染器无关。
5. **不提交敏感信息**：厂商文档、客户数据、内网地址、工单号一律不进仓；`tools/redact.py` 会把它们扫出来。

