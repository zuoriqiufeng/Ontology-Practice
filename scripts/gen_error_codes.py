#!/usr/bin/env python3
"""gen_error_codes.py — 由官方码表生成 plugin/error_codes.yaml（62 号批 P-2A）

**为什么需要**：Q27 裁定「错误码不进本体」——码空间无上界，穷举在任何一层都无意义。
但 `plugin/resolver.py` 的 `get_risk()` **只吃消息文本**（`classify_error_message(message)`），
「只给码」时 `dimension` 为空、推理链断在第一步。官方码表到位后，**码的"含义"成了权威输入**：
把 码 → 官方含义 → 语义类别（复用同一套 `error_semantics.yaml` 规则）离线算成**预计算映射**，
即可补上这个口子，而码**始终不进入本体**（出口仍是 `dimension:*`）。

**表的实际形状（实测，勿再按"267 行"称）**：sheet1 共 267 行，其中 **91 行是空行**，
**176 行有内容且 `define` 唯一**；`code`（数字）列有 1 个重复值 `4217`（两个不同 ALARM 定义）。
⇒ **本表以 `define` 为键**，`code` 只作字段。

**三段结构**（各段事实不同，不是重复）：
  · `codes`          —— 官方表**逐字**（三张 sheet 合并：sheet2/3 的中文更长时优先）
  · `codes_meta`     —— sheet2 告警表专有列（iaproxy 告警级别 / 告警间隔递增机制）
  · `dimension_map`  —— **我们的判断**：含义 → 维度（预计算）＋ `status`（统一/区分/待现场复核）

**单一事实源**：维度判类**复用** `plugin.resolver.classify_error_message`，
不在此重新实现 match 逻辑（实测导入 0.03s、无 torch/transformers 副作用）。

用法:
  python3 scripts/gen_error_codes.py                 # 生成 plugin/error_codes.yaml
  python3 scripts/gen_error_codes.py --check         # 只比对，不一致则退出码 3
  python3 scripts/gen_error_codes.py --report        # 只打印覆盖度，不写文件

退出码：0 成功；1 源文件缺失；2 解析失败；3 --check 发现不一致。
"""

import argparse
import hashlib
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SRC = os.path.join(HERE, "doc", "projectdoc", "错误代码定义.xlsx")
OUT = os.path.join(HERE, "plugin", "error_codes.yaml")
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
LF = chr(10)

# ── 6 条码的判定（62 号 §4，**人工结论**，不是自动推断）──────────────────
VERDICTS = {
    "4002": ("统一", "官方含义与仓内别名「REDO位点异常」同义；官方多给「指定序号」，采用官方表述"),
    "4016": ("统一", "同义（节点离线）；官方额外点名 iahelper ⇒ 可作 process:iahelper 的第二来源（本批不改本体）"),
    "4071": ("统一", "同一件事：RUNNING 下重复启动被拒；sheet2/3 中文更完整（多「不能再次启动此规则」）"),
    "4046": ("区分", "主体不同：官方=装载「错误」（数据层，对应 IAERR_LOAD_ERROR 4062 / IAERR_LOAD 4013）；"
                     "仓内别名=装载「进程异常」（服务层）⇒ 须现场确认是数据错还是服务挂"),
    "4031": ("区分", "**2026-10-13 对齐后**：本仓别名「ABNORMAL禁止重启」与官方「有其他冲突性操作正在后台执行」**不是同一件事**（前者是状态机约束语义，见 action_routing 的 cannot_restart_ABNORMAL）⇒ 保留别名（现场就这么叫）、按「区分」处理；手册对本码说的是**另一套编号**（其内容对应官方 ALARM_RULE_STATE 4213），已按用户裁定「错误码和错误码表统一」对齐，不再计入本码冲突"),
    "4073": ("待现场复核", "**三方冲突**：官方=规则未找到；仓内A=源端日志不可读"
                          "（db-diagnostics/oracle.md:29、fault-injection-catalog.md:211、"
                          "test_direction_layer.py:39 断言 → dimension:log_readable）；"
                          "仓内B=规则配置下发失败（demo_product-debug/SKILL.md:161）"),
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _shared_strings(z):
    return ["".join(t.text or "" for t in si.iter(M + "t"))
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(M + "si")]


def _sheet(z, name, ss):
    rows = []
    for tr in ET.fromstring(z.read(name)).iter(M + "row"):
        d = {}
        for c in tr:
            col = re.match(r"[A-Z]+", c.get("r") or "A").group(0)
            v = c.find(M + "v")
            val = "" if v is None else v.text
            if c.get("t") == "s" and val:
                val = ss[int(val)]
            d[col] = (val or "").strip()
        rows.append(d)
    return rows


def load():
    """→ (codes_by_define, codes_meta, blank_rows)。以 **define** 为键（code 列有重复）。"""
    if not os.path.isfile(SRC):
        print("源文件缺失: %s" % SRC)
        sys.exit(1)
    try:
        z = zipfile.ZipFile(SRC)
        ss = _shared_strings(z)
        s1 = _sheet(z, "xl/worksheets/sheet1.xml", ss)
        s2 = _sheet(z, "xl/worksheets/sheet2.xml", ss)
        s3 = _sheet(z, "xl/worksheets/sheet3.xml", ss)
    except Exception as exc:  # noqa: BLE001
        print("解析失败: %s" % exc)
        sys.exit(2)

    codes, blanks = {}, 0
    for r in s1[1:]:
        key = r.get("A", "")
        if not key:
            blanks += 1
            continue
        codes[key] = {
            "define": key, "code": r.get("B", ""), "zh": r.get("C", ""),
            "en": r.get("D", ""), "zh_tw": r.get("E", ""), "ja": r.get("F", ""),
            "level": r.get("G", ""), "affected": r.get("H", ""),
            "old_define": "", "alarm_level": "", "interval_escalation": "",
        }
    # sheet3：补 old_define；中文更长时覆盖 zh
    for r in s3[1:]:
        key = r.get("A", "")
        if key not in codes:
            continue
        if r.get("G"):
            codes[key]["old_define"] = r["G"]
        if len(r.get("C", "")) > len(codes[key]["zh"]):
            codes[key]["zh"] = r["C"]
    # sheet2：告警专有列；中文更长时覆盖 zh
    meta = []
    for r in s2[1:]:
        key = r.get("A", "")
        if not key:
            continue
        if key in codes:
            if len(r.get("C", "")) > len(codes[key]["zh"]):
                codes[key]["zh"] = r["C"]
            codes[key]["alarm_level"] = r.get("E", "")
            codes[key]["interval_escalation"] = r.get("F", "")
        meta.append({"define": key, "code": r.get("B", ""), "zh": r.get("C", ""),
                     "en": r.get("D", ""), "alarm_level": r.get("E", ""),
                     "interval_escalation": r.get("F", "")})
    return codes, meta, blanks


def build():
    from plugin.resolver import classify_official_meaning

    codes, meta, blanks = load()
    dim_map, classified = [], 0
    for key in sorted(codes):
        e = codes[key]
        num = e["code"] or key
        verdict, note = VERDICTS.get(e["code"], ("", ""))
        # Step A（用户 2026-10-13 裁定 C → A）：**官方含义明确且仓内无相反说法**的码
        # ⇒ status=单源（给维度，但标注单源未经现场验证）。已知误判已由 Step C 的 deny 表清掉。
        if not verdict and classify_official_meaning(e["zh"])["dimension"] != "dimension:unknown":
            verdict = "单源"
            note = "官方含义明确、仓内无相反说法（**单源：厂商文档，未经现场验证**）"
        res = classify_official_meaning(e["zh"])
        dim = res.get("dimension") or "dimension:unknown"
        if dim != "dimension:unknown":
            classified += 1
        dim_map.append({
            "define": key, "code": e["code"], "meaning": e["zh"],
            "dimension": dim, "rule": res.get("rule", ""), "matched_by": res.get("evidence", ""),
            "status": verdict, "note": note,
        })
    doc = {
        "schema": 1,
        "generated_by": "scripts/gen_error_codes.py",
        "generated_from": "doc/projectdoc/错误代码定义.xlsx",
        "source_sha256": sha256(SRC),
        "not_ontology": "Q27：本文件是 Tool 层只读侧车，**bkn/ 不得引用**（码不进本体；出口是 dimension:*）",
        "why": "官方码表给「含义」；含义经 error_semantics.yaml 的同一套有界规则落到 dimension:*，"
               "使「只给码」也能进本体推理链（此前 get_risk 只吃消息文本）",
        "table_shape": {
            "sheet1_rows": len(codes) + blanks,
            "blank_rows": blanks,
            "entries": len(codes),
            "key": "define（code 列有 1 个重复值 4217，故不以 code 为键）",
        },
        "coverage": {"entries": len(codes), "classified": classified,
                     "unknown": len(codes) - classified,
                     "rate_pct": round(100.0 * classified / max(len(codes), 1), 1)},
        "codes": [codes[k] for k in sorted(codes)],
        "codes_meta": meta,
        "dimension_map": dim_map,
    }
    import yaml
    body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100,
                          default_flow_style=False)
    header = ("# plugin/error_codes.yaml —— 由 scripts/gen_error_codes.py 生成，**请勿手改**" + LF +
              "# Q27：错误码不进本体。本文件是 Tool 层只读侧车；bkn/ 不得引用。" + LF +
              "# 重新生成：python3 scripts/gen_error_codes.py" + LF)
    return header + body, doc["coverage"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对，不写文件")
    ap.add_argument("--report", action="store_true", help="只打印覆盖度")
    args = ap.parse_args()

    text, cov = build()
    print("官方表 %d 条 ｜ 已归类 %d （%.1f%%）｜ 未归类 %d"
          % (cov["entries"], cov["classified"], cov["rate_pct"], cov["unknown"]))

    if args.report:
        return 0
    if args.check:
        cur = open(OUT, encoding="utf-8").read() if os.path.isfile(OUT) else ""
        if cur != text:
            print("不一致：%s 需重新生成" % OUT)
            return 3
        print("一致 ✓")
        return 0
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("写出 %s（%d 行）" % (OUT, text.count(LF)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
