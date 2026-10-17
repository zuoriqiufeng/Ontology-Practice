# 测试说明（开源版）

本仓只保留**与运行时自身相关**的测试。以下 30 个测试文件**已移除**（内部版存在），
原因是它们断言**产品级本体内容**（具体对象/进程/维度/码/机制），属于「实例仓」而非「运行时仓」：

```
test_synonyms, test_relations, test_direction_layer, test_diagnose_db_link,
test_resolver, test_edge_semantics, test_edge_semantics_injection, test_ontology_use,
test_mini_first_phase, test_impact_query, test_get_prerequisites, test_class_hierarchy,
test_risk_guard, test_mechanisms, test_manifest, test_bkn_version_root,
test_treatment_hint, test_trajectory, test_alias_golden, test_batch4_observability,
test_bkn_boundary, test_bm25_collections, test_chunk_mode, test_error_semantics,
test_impact_query, test_lint_bkn, test_output_budget, test_reasoning_path,
test_resolve_operation, test_skill_reference_ids, test_supplement
```

> 你自己的实例仓应带上这些测试的**等价物**（针对你的本体内容）。

