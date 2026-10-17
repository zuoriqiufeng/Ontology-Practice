# search_qdrant_handler dict leak → DeepSeek HTTP 400

## 完整调用链追踪 (Hermes 内部)

```
search_qdrant_handler(args)
  → return {"hits": [...], "count": 5, ...}        # Python dict

agent._invoke_tool("search_qdrant", args)
  → model_tools.py:handle_function_call()
    → registry.dispatch("search_qdrant", args)
      → tools/registry.py:404: return entry.handler(args, **kwargs)  # dict 透传
    → run_tool_execution_middleware(...) → dict
    → _emit_post_tool_call_hook(...) → dict
    → return result  # dict (line 1197)

agent._execute_tool_calls_sequential()
  → agent/tool_executor.py
    → result = agent._invoke_tool(...)  # dict
    → make_tool_result_message(name, result, tc.id)
      → agent/tool_dispatch_helpers.py:336
        → _maybe_wrap_untrusted("search_qdrant", result)
          → not _is_untrusted_tool("search_qdrant") → return content  # dict
      → return {"role": "tool", "content": <dict>, ...}

messages.append(tool_message)  # content 是 dict!

api_messages = list(messages)  # 准备发 API 请求
  → conversation_loop.py:787
    → isinstance(am.get("content"), str) → False → 跳过 strip
  → 发送给 DeepSeek:
    → json.dumps(api_messages) →
      {"role":"tool", "content":{"hits":[...],"count":5}, ...}
                                ↑ JSON object，不是 string!
  → DeepSeek 校验: content must be string or list → HTTP 400
```

## 为什么其他 BKN Tool 不受影响

| Tool | 返回路径 | 最终类型 |
|------|---------|---------|
| query_product | `_wrap()` → `context_loader.process()` | str |
| explain_architecture | `_wrap()` → `context_loader.process()` | str |
| design_solution | `_wrap()` → `context_loader.process()` | str |
| check_compatibility | `_wrap()` → `context_loader.process()` | str |
| list_scenarios | `_wrap()` → `context_loader.process()` | str |
| diagnose_error | `_wrap()` → `context_loader.process()` | str |
| get_prerequisites | `_wrap()` → `context_loader.process()` | str |
| resolve_relation | `_wrap()` → `context_loader.process()` | str |
| resolve_operation | `_wrap()` → `context_loader.process()` | str |
| **search_qdrant** | **直接 return dict** | **dict** ❌ |

`search_qdrant_handler` 刻意绕过 `_wrap()` 以避免 supplement 管道循环（`_wrap` → L2 fallback_to_qdrant → 可能调用 search_qdrant → 无限循环），但未将返回值序列化为 JSON string。

## 修复

```python
import json

def search_qdrant_handler(args, **kwargs):
    ...
    # 每个 return 路径
    return json.dumps({...}, ensure_ascii=False)
```

## 验证

```bash
cd /path/to/demo-product-bkn && python3 -c "
from plugin.tools import search_qdrant_handler
import json
result = search_qdrant_handler({'query': 'Oracle CDC redo log', 'top_k': 3})
assert isinstance(result, str), f'Expected str, got {type(result).__name__}'
assert json.loads(result), 'Not valid JSON'
print('OK: handler returns JSON string')
"
```

## 相关文件

- `demo-product-bkn/plugin/tools.py` — `search_qdrant_handler` (line 204-312)
- `/usr/local/lib/hermes-agent/tools/registry.py` — `dispatch()` (line 390-416)
- `/usr/local/lib/hermes-agent/model_tools.py` — `handle_function_call()` (line 876-1202)
- `/usr/local/lib/hermes-agent/agent/tool_dispatch_helpers.py` — `make_tool_result_message()` (line 320-343)
- `/usr/local/lib/hermes-agent/agent/conversation_loop.py` — message normalization (line 787)
