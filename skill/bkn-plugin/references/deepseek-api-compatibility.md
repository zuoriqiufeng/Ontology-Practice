# DeepSeek API 兼容性：`content: null` 导致 HTTP 400

## 现象

多轮 Tool Calling 后，Hermes 发送请求到 DeepSeek API 时报错：

```
API call failed (attempt 1/3): BadRequestError [HTTP 400]
   🔌 Provider: custom  Model: deepseek-v4-pro
   🌐 Endpoint: https://api.deepseek.com
   📝 Error: HTTP 400: Failed to deserialize the JSON body into the target type:
      messages[8]: content should be a string or a list at line 1 column 52443
```

特点：
- 发生在多轮 Tool Calling 后（12 msgs, ~12,964 tokens 级别）
- `messages[N]` 指向靠后的消息（通常是新一轮 assistant tool_calls）
- Plugin Tool 本身调用成功、返回值正常
- 问题出在 Hermes → DeepSeek 的请求构造阶段

## 根因

**DeepSeek API 不接受 assistant 消息的 `content: null`。**

在 OpenAI API 规范中，assistant 消息带上 `tool_calls` 时 `content` 可以为 `null`：

```json
// ✅ OpenAI 接受
{"role": "assistant", "content": null, "tool_calls": [...]}
```

DeepSeek API 的验证更严格，要求 `content` 必须是 `string` 或 `list`：

```json
// ❌ DeepSeek 拒绝 (content is null)
{"role": "assistant", "content": null, "tool_calls": [...]}

// ✅ DeepSeek 接受
{"role": "assistant", "content": "", "tool_calls": [...]}
```

## 触发条件

当 Hermes agent 在某一轮只声明 tool_calls 而不输出任何文字时，assistant 消息的 `content` 就是 `null`。这在多轮工具调用中很常见。

## 影响范围

- 所有使用 DeepSeek 作为 provider 的 Hermes 会话
- 任何涉及多轮 Tool Calling 的场景都会触发
- demo-product-bkn plugin 的 10 个 BKN Tool 均在影响范围内

## 诊断方法论

当遇到类似 "content should be a string or a list" 的 API 错误时：

1. **确定错误消息位置**：`messages[N]` 是第 N+1 条消息，推断消息角色
   - N 为偶数：通常是 assistant 消息
   - N 为奇数：通常是 tool 结果消息

2. **检查 Plugin Tool 返回值**：
   ```bash
   # 验证 handler 返回值是否正常
   cd /path/to/demo-product-bkn && python3 -c "
   from plugin.tools import search_qdrant_handler
   result = search_qdrant_handler({'query': 'test', 'dimension': '全量同步参数'})
   import json
   print(json.dumps(result, ensure_ascii=False, indent=2)[:500])
   "
   ```

3. **检查 .py vs .pyc 一致性**：
   ```bash
   # 确认源文件和字节码同步
   stat -c '%n  mtime:%y  size:%s' plugin/supplement.py plugin/__pycache__/supplement.cpython-*.pyc
   ```

4. **追踪 Hermes 消息构造**：
   - `agent/conversation_loop.py` — API 消息组装
   - `agent/agent_runtime_helpers.py` — `sanitize_api_messages()`
   - `run_agent.py` — `_sanitize_tool_calls_for_strict_api()`
   - `agent/transports/chat_completions.py` — provider 特定适配

5. **区分 Plugin bug vs Framework bug**：
   - Plugin 返回 dict → Hermes 序列化为 JSON string → tool message content 为 string → ✅ Plugin OK
   - Assistant message content 为 null → DeepSeek 拒绝 → ❌ Framework 需适配

## 修复方案

在 Hermes 框架的消息发送前做兼容处理。两个候选位置：

### 方案 A：在 `sanitize_api_messages()` 中统一处理

文件：`agent/agent_runtime_helpers.py` → `sanitize_api_messages()`

```python
# 在返回前添加
for msg in messages:
    if msg.get("role") == "assistant" and msg.get("tool_calls") and msg.get("content") is None:
        msg["content"] = ""
```

### 方案 B：在 DeepSeek provider adapter 中处理

文件：`agent/transports/chat_completions.py`

根据 provider 名称判断是否需要做 null→"" 转换。好处是不影响其他 provider。

### 临时 workaround

在 DeepSeek provider 配置中确保每次 assistant 消息都有非空 content，或者 system prompt 中 instruct 模型在 tool_calls 前输出简短说明文字（如 "Let me check..."）。

## 相关文件索引

| 文件 | 作用 |
|------|------|
| `<repo>/demo-product-bkn/plugin/tools.py` | search_qdrant_handler 等 handler |
| `<repo>/demo-product-bkn/plugin/supplement.py` | search_qdrant() 底层搜索 |
| `<repo>/demo-product-bkn/plugin/context_loader.py` | _wrap() → _loader.process() 格式化 |
| `/usr/local/lib/hermes-agent/agent/conversation_loop.py` | API 消息组装 |
| `/usr/local/lib/hermes-agent/agent/agent_runtime_helpers.py` | sanitize_api_messages() |
| `/usr/local/lib/hermes-agent/run_agent.py` | _sanitize_api_messages 转发 + _sanitize_tool_calls_for_strict_api |
| `/usr/local/lib/hermes-agent/agent/transports/chat_completions.py` | provider 适配层 |
