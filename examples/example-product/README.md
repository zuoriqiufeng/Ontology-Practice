# example-product（示例本体）

> 这是**最小示例**：两个对象 + 一个动作/关系片段，用来演示格式与「值委托」。
> 它**不是**本仓的默认本体——默认 `bkn/` 是骨架（规范 + 模板），你的本体放这里或任何 `--bkn-root` 指向的目录。

| 文件 | 演示什么 |
|---|---|
| `bkn/objects/host.bkn` | 对象 frontmatter（`id`/`name`/`aliases`）+ 不含阈值的写法 |
| `bkn/objects/worknode.bkn` | 别名同址、`{db_manager_skill}` 值委托、关系指针 |
| `snippets/action-start-rule.md` | 动作段：`capability` / `implements` / `prerequisites` / `aliases` |
| `snippets/relation-runs-on.md` | 关系段：`关系类型` / 源目标 / 映射规则 |

## 校验

```bash
python3 -m plugin.scripts.lint_bkn --bkn-root examples/example-product/bkn
```

## 走一遍

见 `../../docs/write-your-first-ontology.md`。
