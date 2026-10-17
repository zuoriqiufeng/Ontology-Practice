# Security Policy

## 报告问题

请不要公开提 issue。请通过仓库 Security 页面的私有报告渠道联系维护者，或发邮件到维护者地址（见 README）。

## 范围

- 运行时不执行任意代码：`plugin/` 只解析 Markdown 与 YAML；Skill 中的命令由使用者自行决定是否执行。
- 本仓**不应**包含任何凭据、内网地址、客户数据。若发现，视为安全事件处理。

## 维护者检查

```bash
python3 tools/redact.py --root . --report /tmp/redact.md
```

五类命中（产品名/厂商名/内网 IP/邮箱/内部痕迹）必须为 0 才能合并。

