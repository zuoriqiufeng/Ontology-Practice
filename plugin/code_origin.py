"""code_origin.py — 错误码来源分类（有界规则，不枚举码）。

为什么：Demo Product 产品码（176 条 sidecar）与数据库原生码（ORA-/SQLSTATE/1062…）
不可能放进同一张表；DB 码空间无界，只能按**来源形状**分流：
  1) product：命中 sidecar（error_codes.yaml）→ diagnose_error；
  2) oracle/mysql/postgres/db2/sqlserver：由 `code_origin.yaml` 的形状/消息规则判定；
  3) ambiguous：裸数字等无法单凭形状断言 → 返回 needs，不猜；
  4) unknown：如实说不知道。

边界：本模块只做「来源/形状」，**不解释含义**；含义永远在产品侧车或 DB 文档/Skill。
"""
from __future__ import annotations

import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_YAML = _HERE / "code_origin.yaml"
_ERROR_CODES = _HERE / "error_codes.yaml"

_FALLBACK_MESSAGE_RULES = []
_RULES_CACHE = None
_PRODUCT_CACHE = None


def _load_yaml(path: Path):
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def rules() -> dict:
    global _RULES_CACHE
    if _RULES_CACHE is None:
        data = _load_yaml(_YAML)
        _RULES_CACHE = {"rules": data.get("rules") or [], "message_rules": data.get("message_rules") or []}
    return _RULES_CACHE


def product_codes() -> set:
    """产品码集合（懒加载；命中即 origin=product）。"""
    global _PRODUCT_CACHE
    if _PRODUCT_CACHE is None:
        codes = set()
        data = _load_yaml(_ERROR_CODES)
        for item in data.get("codes") or []:
            c = str((item or {}).get("code") or "").strip()
            if c:
                codes.add(c)
        _PRODUCT_CACHE = codes
    return _PRODUCT_CACHE


def _norm_product(code: str):
    codes = product_codes()
    for cand in (code, code.lstrip("-"), "-" + code.lstrip("-")):
        if cand in codes:
            return cand
    return None


_VENDORS = {
    "oracle": "oracle", "ora": "oracle",
    "mysql": "mysql", "mariadb": "mysql",
    "postgres": "postgres", "postgresql": "postgres", "pg": "postgres",
    "db2": "db2",
    "sqlserver": "sqlserver", "mssql": "sqlserver",
}


def _vendor_hint(text: str) -> str:
    if not text:
        return ""
    t = str(text).lower()
    for key, vendor in _VENDORS.items():
        if re.search(r"(?<![a-z])" + re.escape(key) + r"(?![a-z])", t):
            return vendor
    return ""


def _match(pattern: str, text: str):
    try:
        return re.search(pattern, text, re.I | re.M) is not None
    except re.error:
        return False


def classify(code: str, message: str = "", db_hint: str = "") -> dict:
    """返回 {origin, vendor, ambiguous, rule, confidence}；异常一律 unknown。"""
    out = {"origin": "unknown", "vendor": "", "ambiguous": False, "rule": "", "confidence": "low"}
    try:
        raw = str(code or "").strip()
        if not raw:
            return out
        prod = _norm_product(raw)
        if prod:
            return {"origin": "product", "vendor": "demo_product", "ambiguous": False,
                    "rule": "product_sidecar", "confidence": "high"}
        vendor_hint = _vendor_hint(str(db_hint or "")) or _vendor_hint(str(message or ""))
        if vendor_hint:
            return {"origin": vendor_hint, "vendor": vendor_hint, "ambiguous": False,
                    "rule": "vendor_hint", "confidence": "medium"}
        text = raw.upper()
        data = rules()
        for rule in data["message_rules"]:
            if message and _match(rule.get("pattern", ""), str(message)):
                return {"origin": rule.get("origin", "unknown"), "vendor": rule.get("vendor", ""),
                        "ambiguous": False, "rule": rule.get("id", ""), "confidence": "medium"}
        for rule in data["rules"]:
            if not _match(rule.get("pattern", ""), text):
                continue
            if rule.get("ambiguous"):
                return {"origin": "ambiguous", "vendor": rule.get("vendor", ""), "ambiguous": True,
                        "rule": rule.get("id", ""), "confidence": "low"}
            return {"origin": rule.get("origin", "unknown"), "vendor": rule.get("vendor", ""),
                    "ambiguous": False, "rule": rule.get("id", ""), "confidence": "medium"}
        return out
    except Exception:  # noqa: BLE001
        return out


def route(code: str, message: str = "", db_hint: str = "") -> tuple:
    """返回 (tool, args, info)：product→diagnose_error；vendor→diagnose_db_link；否则 (None, {}, info)。"""
    info = classify(code, message=message, db_hint=db_hint)
    origin = info["origin"]
    if origin == "product":
        return "diagnose_error", {"error_code": code}, info
    if origin in ("oracle", "mysql", "postgres", "db2", "sqlserver"):
        args = {"error_code": code, "db_type": origin}
        if message:
            args["message"] = str(message)[:500]
        return "diagnose_db_link", args, info
    return None, {}, info
