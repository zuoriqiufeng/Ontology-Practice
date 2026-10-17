# Action: 启动同步规则（示例）

> 动作只声明**能力语义**；参数、命令、校验由 Skill 提供。

<!-- type: action -->
## Action: 启动同步规则

- capability: start_sync_rule
- object: worknode
- access_type: write
- binding_type: skill
- implements: skill:example-rule-manager
- params: 规则标识，具体字段由 Skill 定义
- prerequisites: [rule must be STOPPED, target must be reachable]
- constraints: [cannot_start_without_prerequisite]
- aliases: start_rule, 启动规则
