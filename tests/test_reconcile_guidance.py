#!/usr/bin/env python3
"""Unit tests for reconcile_guidance: value parsing + multi-doc guidance lineage.
Run from repo root: .venv/bin/python .claude/skills/earnings-summary/tests/test_reconcile_guidance.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import reconcile_guidance as rg  # noqa: E402

fails = []
def check(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r}, want {want!r}")
def approx(name, got, want, tol=1e-6):
    if got is None or abs(got - want) > tol:
        fails.append(f"{name}: got {got!r}, want ~{want!r}")

# ---- parse_value ----
approx("pv range mid", rg.parse_value("1.45 - 1.79")[2], 1.62)
approx("pv parens-neg mid", rg.parse_value("(3.0%) - (5.0%)")[2], -4.0)
check("pv tilde-zero", rg.parse_value("~0.0%"), (0.0, 0.0, 0.0))
approx("pv billions mid", rg.parse_value("$2.48 billion to $2.64 billion")[2], 2.56)
check("pv flat", rg.parse_value("flat"), (0.0, 0.0, 0.0))
approx("pv signed-pos", rg.parse_value("+1.0%")[2], 1.0)
check("pv empty", rg.parse_value(""), None)
approx("pv approx-single", rg.parse_value("approximately $632 million")[2], 632.0)

def doc(period, date, recs):
    return {"period": period, "filing_date": date,
            "guidance": [{"guide_key": k, "metric": m, "guide_period": gp, "unit": u,
                          "status": s, "value": v, "quote": f"q:{v}"}
                         for (k, m, gp, u, s, v) in recs]}

def by_key(results):
    return {r["guide_key"]: r for r in results}

# ---- A: reaffirmed 3 quarters back (the headline use case) ----
A = rg.reconcile({"docs": [
    doc("FY26 Q1", "2026-05-04", [("fy26_ny", "FY26 Net Yield", "FY26", "%", "reaffirmed", "")]),
    doc("FY25 Q4", "2026-02-12", [("fy26_ny", "FY26 Net Yield", "FY26", "%", "reaffirmed", "")]),
    doc("FY25 Q3", "2025-11-04", [("fy26_ny", "FY26 Net Yield", "FY26", "%", "initiated", "+2.0% - +3.0%")]),
]})
a = by_key(A)["fy26_ny"]
check("A current_guide", a["current_guide"], "+2.0% - +3.0%")
check("A set_as_of", a["set_as_of"], "FY25 Q3")
check("A reaffirmed_through", a["reaffirmed_through"], "FY26 Q1")
check("A prior_guide", a["prior_guide"], "")
check("A action", a["action"], "MAINTAIN")
check("A origin_in_window", a["origin_in_window"], True)

# ---- B: origin before window (all reaffirmed, no number anywhere) ----
B = rg.reconcile({"docs": [
    doc("FY26 Q1", "2026-05-04", [("fy26_eb", "FY26 EBITDA", "FY26", "$B", "reaffirmed", "")]),
    doc("FY25 Q4", "2026-02-12", [("fy26_eb", "FY26 EBITDA", "FY26", "$B", "reaffirmed", "")]),
]})
b = by_key(B)["fy26_eb"]
check("B current_guide empty", b["current_guide"], "")
check("B action unknown", b["action"], "UNKNOWN")
check("B origin_in_window", b["origin_in_window"], False)

# ---- C: cut with prior distinct value ----
C = rg.reconcile({"docs": [
    doc("FY26 Q1", "2026-05-04", [("fy26_eps", "FY26 Adj EPS", "FY26", "$", "cut", "1.45 - 1.79")]),
    doc("FY25 Q4", "2026-02-12", [("fy26_eps", "FY26 Adj EPS", "FY26", "$", "initiated", "2.00 - 2.20")]),
]})
c = by_key(C)["fy26_eps"]
check("C current_guide", c["current_guide"], "1.45 - 1.79")
check("C prior_guide", c["prior_guide"], "2.00 - 2.20")
check("C prior_as_of", c["prior_as_of"], "FY25 Q4")
check("C action", c["action"], "CUT")
check("C set_as_of", c["set_as_of"], "FY26 Q1")
check("C origin_in_window", c["origin_in_window"], True)
check("C no conflict note", any("verify" in n for n in c["notes"]), False)

# ---- E: raised, single doc -> prior outside window (flag) ----
E = rg.reconcile({"docs": [
    doc("FY26 Q1", "2026-05-04", [("fy26_rev", "FY26 Revenue", "FY26", "$B", "raised", "12.0 - 12.4")]),
]})
e = by_key(E)["fy26_rev"]
check("E action", e["action"], "RAISE")
check("E prior empty", e["prior_guide"], "")
check("E origin flagged", e["origin_in_window"], False)

# ---- F: declared raise but midpoint fell -> conflict note ----
F = rg.reconcile({"docs": [
    doc("FY26 Q1", "2026-05-04", [("k", "Metric X", "FY26", "$", "raised", "1.0 - 1.2")]),
    doc("FY25 Q4", "2026-02-12", [("k", "Metric X", "FY26", "$", "stated", "2.0 - 2.2")]),
]})
f = by_key(F)["k"]
check("F action declared", f["action"], "RAISE")
check("F conflict note present", any("verify" in n for n in f["notes"]), True)

# ---- D: initiate, single doc ----
D = rg.reconcile({"docs": [
    doc("FY26 Q1", "2026-05-04", [("fy26_seg", "FY26 Segment", "FY26", "$B", "initiated", "5.0")]),
]})
d = by_key(D)["fy26_seg"]
check("D action initiate", d["action"], "INITIATE")
check("D origin_in_window", d["origin_in_window"], True)

# ---- render_table smoke ----
tbl = rg.render_table(A + B)
check("table provenance", "set FY25 Q3, reaffirmed thru FY26 Q1" in tbl, True)
check("table warn flag", "⚠" in tbl, True)

verdict = "PASS" if not fails else "FAIL"
print(f"{verdict} - {len(fails)} failure(s)")
for x in fails:
    print("  FAIL:", x)
sys.exit(0 if not fails else 1)
