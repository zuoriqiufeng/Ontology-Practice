"""mcp_server.py — 把本体能力开放给 Hermes 以外的客户端（P3，MCP stdio）。

只实现 MCP 的一个实用子集（换行分隔的 JSON-RPC 2.0，stdio）：
  initialize / notifications/initialized
  tools/list / tools/call
  resources/list / resources/read
  prompts/list / prompts/get

设计取舍：
  * **不引入 SDK 依赖**：协议子集手写，零依赖、可离线测试；
  * **复用现有 handler**：tools 就是 `plugin.tools.HANDLERS`（15 个），不复制逻辑；
  * **resources 只读**：卡片来自 `plugin.cards`，schema/维度来自 `bkn/`；
  * **不暴露写操作**：本进程只做查询与核对；
  * stdio ＋ HTTP JSON-RPC（POST /mcp）；HTTP 默认只绑 127.0.0.1，可用 BKN_MCP_TOKEN 开 Bearer 鉴权。
"""
from __future__ import annotations

import json
import os
import sys

from .cards import BKN_ROOT, build_card

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "bkn-ontology", "version": "0.3.0"}


def _handlers():
    from .tools import HANDLERS
    return HANDLERS


def _schemas():
    from .schemas import SCHEMAS
    return SCHEMAS


def _resources():
    return [
        {"uri": "bkn://schema", "name": "BKN SCHEMA", "mimeType": "text/markdown"},
        {"uri": "bkn://dimensions", "name": "检查维度", "mimeType": "text/markdown"},
        {"uri": "bkn://changelog", "name": "本体变更记录", "mimeType": "text/markdown"},
    ]


PROMPTS = {
    "diagnose-by-code": {
        "description": "按错误码排障：先查本体，再给证据与 Skill 指针",
        "arguments": [{"name": "code", "required": True}, {"name": "message", "required": False}],
    },
    "plan-check": {
        "description": "检查一串运维步骤是否符合前置与约束",
        "arguments": [{"name": "action", "required": True}, {"name": "state", "required": False}],
    },
}


def _text_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _read_resource(uri: str) -> str:
    if uri.startswith("bkn://card/"):
        return build_card("object", uri[len("bkn://card/"):])
    if uri == "bkn://schema":
        return (BKN_ROOT / "SCHEMA.md").read_text(encoding="utf-8", errors="ignore")
    if uri == "bkn://dimensions":
        return build_card("dimension", "dimensions")
    if uri == "bkn://changelog":
        return "本体版本见 bkn-version.json；变更记录见仓库 CHANGELOG.md。"
    raise KeyError(uri)


def handle_request(req: dict) -> dict | None:
    """处理一条 JSON-RPC 请求；通知返回 None。"""
    if not isinstance(req, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    method = req.get("method") or ""
    req_id = req.get("id")
    params = req.get("params") or {}
    if method == "notifications/initialized":
        return None
    try:
        if method == "initialize":
            result = {"protocolVersion": PROTOCOL_VERSION,
                      "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                      "serverInfo": SERVER_INFO}
        elif method == "tools/list":
            result = {"tools": [{"name": s["name"], "description": s.get("description", ""),
                                 "inputSchema": s.get("parameters") or {"type": "object"}} for s in _schemas()]}
        elif method == "tools/call":
            name = str(params.get("name") or "")
            args = params.get("arguments") or {}
            handler = _handlers().get(name)
            if handler is None:
                raise KeyError("unknown tool: %s" % name)
            out = handler(args)
            result = _text_result(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False))
        elif method == "resources/list":
            result = {"resources": _resources()}
        elif method == "resources/read":
            uri = str(params.get("uri") or "")
            text = _read_resource(uri)
            result = {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text}]}
        elif method == "prompts/list":
            result = {"prompts": [{"name": k, "description": v["description"],
                                   "arguments": v["arguments"]} for k, v in PROMPTS.items()]}
        elif method == "prompts/get":
            name = str(params.get("name") or "")
            if name not in PROMPTS:
                raise KeyError("unknown prompt: %s" % name)
            supplied = params.get("arguments") or {}
            if name == "diagnose-by-code":
                code = supplied.get("code", "")
                msg = supplied.get("message", "")
                body = "错误码 %s%s。请先用 bkn_ask 查本体（码是入口，不背码表），再给证据与应加载的 Skill。" % (
                    code, ("，日志文本：" + str(msg)) if msg else "")
            else:
                body = "步骤：%s（当前状态 %s）。请先用 check_plan 核对前置与约束，再决定是否执行。" % (
                    supplied.get("action", ""), supplied.get("state", "未知"))
            result = {"description": PROMPTS[name]["description"],
                      "messages": [{"role": "user", "content": {"type": "text", "text": body}}]}
        else:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": "method not found: %s" % method}}
    except Exception as exc:  # noqa: BLE001
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32603, "message": "%s: %s" % (type(exc).__name__, exc)}}
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def serve_stdio(stream_in=None, stream_out=None) -> int:
    """换行分隔的 JSON-RPC 循环（MCP stdio 传输）。"""
    fin = stream_in or sys.stdin
    fout = stream_out or sys.stdout
    for line in fin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            fout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                   "error": {"code": -32700, "message": "parse error"}}) + chr(10))
            fout.flush()
            continue
        resp = handle_request(req)
        if resp is not None:
            fout.write(json.dumps(resp, ensure_ascii=False) + chr(10))
            fout.flush()
    return 0



# ---- HTTP 传输（streamable 子集）＋ Bearer 鉴权（C-20261018-12） ----

def _auth_token() -> str:
    """token 来源：环境变量 BKN_MCP_TOKEN 优先，其次 config.yaml mcp.token。空＝不鉴权。"""
    try:
        from .config import _config
        cfg = (_config.get("mcp", {}) or {}).get("token") or ""
    except Exception:  # noqa: BLE001
        cfg = ""
    return str(os.environ.get("BKN_MCP_TOKEN") or cfg or "").strip()


def _auth_ok(headers) -> bool:
    token = _auth_token()
    if not token:
        return True
    got = (headers.get("Authorization") or "").strip()
    return got == "Bearer " + token


def make_http_handler():
    """返回一个 BaseHTTPRequestHandler 子类：POST /mcp（JSON-RPC）、GET /health。"""
    from http.server import BaseHTTPRequestHandler

    class _Handler(BaseHTTPRequestHandler):
        server_version = "bkn-mcp/0.4"

        def _send(self, code, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?")[0] == "/health":
                return self._send(200, {"ok": True, "server": SERVER_INFO})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path.split("?")[0] != "/mcp":
                return self._send(404, {"error": "not found"})
            if not _auth_ok(self.headers):
                return self._send(401, {"error": "unauthorized"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n) or b"{}")
            except Exception:  # noqa: BLE001
                return self._send(400, {"jsonrpc": "2.0", "id": None,
                                        "error": {"code": -32700, "message": "parse error"}})
            resp = handle_request(req)
            if resp is None:
                return self._send(202, {"ok": True})
            return self._send(200, resp)

        def log_message(self, *args):  # 静默，避免污染客户端日志
            return

    return _Handler


def serve_http(host: str = "127.0.0.1", port: int = 8765) -> int:
    """HTTP JSON-RPC 服务；默认只绑本机。鉴权见 _auth_token()。"""
    from http.server import ThreadingHTTPServer

    srv = ThreadingHTTPServer((host, port), make_http_handler())
    print("bkn MCP HTTP listening on http://%s:%d/mcp（health: /health；auth: %s）"
          % (host, srv.server_address[1], "Bearer" if _auth_token() else "off"))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="用 HTTP 而不是 stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    if a.http:
        raise SystemExit(serve_http(a.host, a.port))
    raise SystemExit(serve_stdio())
