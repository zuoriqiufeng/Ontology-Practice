# Changelog

## 0.1.0a0-sync — 2026-10-29
- 同步开放入口路由（Open-Entry Router）P1-P5：新增 plugin/ask_router.py（信号抽取框架 + 意图路由 resolve_intent + 聚合答案层 attach_intents）、plugin/entry_signal.yaml（信号注册表）、plugin/intent_routes.yaml（数据驱动路由表）；ask() 前置 _route_v2（默认关闭，影子跑）。
- 行为影响：否。ask_router.enabled 默认 false，关闭态输出与接入前逐字节一致；启用时新增 intents / alt_intents 全意图呈现（dominant-first + 备选方向一句话）。
- 产品 vendor 哨兵用非产品名常量 _PRODUCT_VENDOR=product，保证去产品化改写不撕裂 .py/.yaml 两处同一常量。

## 0.1.0a0 — v0.1.0-alpha

- 首次从内部工程仓剥离出**绿名单**：本体骨架（`bkn/`）、运行时（`plugin/`）、7 个通用 `bkn-*` skill、治理脚本（`scripts/`）。
- 全仓去产品化：产品名/厂商名/内网 IP/内部路径/工单号 → 占位或通用写法（`tools/redact.py` 五类为 0）。
- 新增：`spec/` 7 篇、`docs/` 4 篇、`examples/example-product` 示例本体、`pyproject.toml`、CI、许可与社区文件。
- 测试：保留运行时通用测试（265 项）；30 个断言产品级本体内容的测试文件移至实例仓（清单见 `plugin/tests/README.md`）。
- 文档：定位表述改为「**面向产品运维的 BKN 本体工程实践**」；与 OpenBKN Engineering 的关系改写为「理念同源（爱数 BKN 本体理论）、实践不同（运维本体工程）」；NOTICE/FAQ/spec/Release 正文同步。
- 未包含：任何厂商官方文档、内部过程记录、产品专有技能。

