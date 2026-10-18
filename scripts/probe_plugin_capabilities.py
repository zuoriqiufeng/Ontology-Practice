#!/usr/bin/env python3
"""probe_plugin_capabilities.py — 探测本机 Hermes 插件面可用性（只读）。

回答三件事：
  1) 平台源码里存在哪些注册面（tools/hook/system_prompt_section/context_reference/middleware）；
  2) 哪些面受 capability 门控（plugin_capabilities._CAPABILITY_ROWS）；
  3) 用 FakeApi 跑一次 plugin.register()，确认我们的注册路径能走通、缺面时能降级。

用法：python3 scripts/probe_plugin_capabilities.py [--hermes /usr/local/lib/hermes-agent]
"""
import argparse
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FakeApi:
    """最小插件 API：记录每次注册；缺少某面时不报错，交由插件自身降级。"""

    def __init__(self, surfaces):
        self.surfaces = set(surfaces)
        self.tools = []
        self.hooks = []
        self.sections = []
        self.refs = []
        self.middleware = []

    def register_tool(self, **kw):
        self.tools.append(kw.get("name"))

    def register_hook(self, name, fn):
        self.hooks.append(name)

    def register_system_prompt_section(self, **kw):
        if "system_prompt_section" not in self.surfaces:
            raise AttributeError("register_system_prompt_section")
        self.sections.append(kw.get("id"))

    def register_context_reference(self, provider):
        if "context_reference" not in self.surfaces:
            raise AttributeError("register_context_reference")
        self.refs.append(getattr(provider, "prefix", "?"))

    def register_middleware(self, kind, cb):
        if "middleware" not in self.surfaces:
            raise AttributeError("register_middleware")
        self.middleware.append(kind)


def _hermes_surfaces(hermes: Path) -> dict:
    plugins = hermes / "hermes_cli" / "plugins.py"
    caps = hermes / "hermes_cli" / "plugin_capabilities.py"
    out = {"source": str(plugins)}
    if plugins.is_file():
        text = plugins.read_text(encoding="utf-8", errors="ignore")
        for name in ("register_tool", "register_hook", "register_system_prompt_section",
                     "register_context_reference", "register_middleware", "register_context_engine",
                     "register_memory_provider"):
            out[name] = ("def %s(" % name) in text
    if caps.is_file():
        text = caps.read_text(encoding="utf-8", errors="ignore")
        ids = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith('("') and '",' in s:
                cid = s[2:].split('",', 1)[0]
                if cid and cid not in ids:
                    ids.append(cid)
        out["capability_ids"] = sorted(ids)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hermes", default="/usr/local/lib/hermes-agent")
    a = ap.parse_args()
    hermes = Path(a.hermes)
    info = _hermes_surfaces(hermes)
    sys.path.insert(0, str(ROOT))
    import plugin as bkn_plugin

    all_surfaces = ["system_prompt_section", "context_reference", "middleware"]
    api = FakeApi(all_surfaces)
    bkn_plugin.register(api)
    full = {"tools": len(api.tools), "hooks": api.hooks, "sections": api.sections,
            "refs": api.refs, "middleware": api.middleware}
    degraded = {}
    for drop in all_surfaces:
        partial = FakeApi([s for s in all_surfaces if s != drop])
        try:
            bkn_plugin.register(partial)
            degraded[drop] = {"ok": True, "tools": len(partial.tools)}
        except Exception as exc:  # noqa: BLE001
            degraded[drop] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    print("Hermes 源码面：")
    for k, v in info.items():
        print("  %-28s %s" % (k, v))
    print("注册结果（全能力 FakeApi）：", json.dumps(full, ensure_ascii=False))
    print("降级测试：", json.dumps(degraded, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
