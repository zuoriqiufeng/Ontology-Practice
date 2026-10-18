# 快速开始

## 1. 安装

```bash
git clone <this-repo> Ontology-Practice && cd Ontology-Practice
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

要求 Python ≥3.9；核心只依赖 PyYAML。向量检索是**可选**的（`.[retrieval]`），缺省自动降级为关键词检索。

## 2. 校验本体

```bash
python3 -m plugin.scripts.lint_bkn --error-only --bkn-root bkn            # 骨架：0 error
python3 -m plugin.scripts.lint_bkn --error-only --bkn-root examples/example-product/bkn
```

## 3. 跑一次查询

```python
from plugin.resolver import BKNResolver
r = BKNResolver(bkn_root="examples/example-product/bkn")
print(r.get_process_skills("worknode"))   # 值委托：返回 Skill 指针，不返回命令
```

## 4. 接进你的 Agent

运行时把能力暴露为**工具函数**（`plugin.tools.HANDLERS`）。接入方式见 [integrate-agent.md](integrate-agent.md)。

## 5. 写你自己的本体

照 [write-your-first-ontology.md](write-your-first-ontology.md) 做一遍，30 分钟能跑通。

