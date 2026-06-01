#!/usr/bin/env python3
"""Reconcile guidance across MULTIPLE earnings releases into a per-metric lineage.

A single-print summary can't populate "Prior Guide": a release that says guidance is
"unchanged" set its number some quarters ago. This script takes the per-document
guidance statements (one list per release) and, for each guided metric (matched by a
canonical `guide_key`), resolves:
  - the effective CURRENT guide (carrying forward `reaffirmed` statements),
  - WHERE/when the live number was last set (`set_as_of`) and that it's been reaffirmed
    through the current print,
  - the PRIOR DISTINCT guide and when it was set,
  - the action (raise/cut/narrow/maintain/initiate/withdraw) — trusting the current
    print's declared status, cross-checked against range-midpoint math,
  - whether the guide's origin is within the supplied window (else flagged "set before
    <oldest> — add older quarters").

Agents extract; THIS reconciles deterministically. Every resolved figure keeps the
quote + the period of the release that stated it (provenance travels). A single-doc
input is valid: prior guide is reported unavailable rather than fabricated.

Input JSON (--in):
{
  "ticker": "NCLH", "current_period": "FY26 Q1",
  "docs": [                       # any order if each has filing_date; else newest-first
    {"period": "FY26 Q1", "filing_date": "2026-05-04", "guidance": [REC, ...]},
    {"period": "FY25 Q4", "filing_date": "2026-02-12", "guidance": [REC, ...]},
    ...
  ]
}
REC = {"guide_key": "fy2026__adjusted_eps", "metric": "FY26 Adjusted EPS",
       "guide_period": "FY26", "unit": "$", "basis": "non-GAAP",
       "status": "stated|raised|cut|narrowed|reaffirmed|withdrawn|absent",
       "value": "1.45 - 1.79",    # SIGNED/normalized as stated this print ("" if reaffirmed w/o number)
       "quote": "...", "source": "..."}

Output: reconciled lineage per guide_key + a §4 markdown table; writes --out and prints
a compact summary to stdout.
"""
import argparse
import json
import re
import sys
from pathlib import Path

STATED = {"stated", "raised", "cut", "narrowed", "initiated"}
ACTION_FROM_STATUS = {
    "raised": "RAISE", "cut": "CUT", "narrowed": "NARROW",
    "reaffirmed": "MAINTAIN", "initiated": "INITIATE", "withdrawn": "WITHDRAW",
}


def parse_value(s):
    """Parse a guidance value string -> (lo, hi, mid) floats, or None if no numbers.

    Handles ranges (a-b / a to b), the financial parens-negative convention
    ((3.0%) -> -3.0), ~/approximately, and 'flat'/'unchanged' -> 0. Strips $ , % and
    scale words (billion/million) — sign/scale are assumed consistent across quarters
    for a given key, and the extractor is asked to emit SIGNED values.
    """
    if s is None or not str(s).strip():
        return None
    t = str(s).lower()
    if re.search(r"\b(flat|unchanged)\b", t) and not re.search(r"\d", t):
        return (0.0, 0.0, 0.0)
    # parenthesized number -> negative: (3.0%) -> -3.0
    t = re.sub(r"\(([^()]*\d[^()]*)\)", lambda m: " -" + m.group(1) + " ", t)
    t = t.replace(",", " ").replace("~", " ").replace("–", "-").replace("—", "-")
    t = re.sub(r"[$%]", " ", t)
    t = re.sub(r"\b(billion|bn|million|mm|approximately|approx|about|to|and|versus|vs|of|per)\b", " ", t)
    nums = re.findall(r"-?\d+(?:\.\d+)?", t)
    vals = [float(x) for x in nums]
    if not vals:
        return None
    lo, hi = min(vals), max(vals)
    return (lo, hi, (lo + hi) / 2.0)


def _sorted_trail(docs, key):
    """Entries mentioning `key`, newest->oldest. Sort by filing_date desc when all
    docs carry it; otherwise trust the given doc order (caller passes newest-first)."""
    have_dates = all(d.get("filing_date") for d in docs)
    ordered = sorted(docs, key=lambda d: d["filing_date"], reverse=True) if have_dates else list(docs)
    trail = []
    for d in ordered:
        for rec in d.get("guidance", []):
            if rec.get("guide_key") == key:
                trail.append({**rec, "period": d.get("period"), "filing_date": d.get("filing_date")})
                break  # one statement per doc per key
    return trail


def reconcile_key(key, trail):
    """trail: entries newest->oldest for one guide_key. Returns the resolved record."""
    notes = []
    current = trail[0]
    status = current.get("status")
    meta = {k: current.get(k) for k in ("metric", "guide_period", "unit", "basis")}
    out = {"guide_key": key, **meta,
           "current_period": current["period"], "current_status": current.get("status"),
           "current_quote": current.get("quote", ""),
           "lineage": [{"period": e["period"], "status": e.get("status"),
                        "value": e.get("value", ""), "quote": e.get("quote", "")} for e in trail]}

    # newest entry that actually stated a number
    stated_idx = next((i for i, e in enumerate(trail)
                       if e.get("status") in STATED and parse_value(e.get("value"))), None)
    if stated_idx is None:
        out.update({"current_guide": "", "set_as_of": None, "reaffirmed_through": None,
                    "prior_guide": "", "prior_as_of": None, "action": "UNKNOWN",
                    "origin_in_window": False,
                    "notes": ["no concrete guide value within the supplied documents — it was set "
                              "before %s; add older quarters" % trail[-1]["period"]]})
        return out

    stated = trail[stated_idx]
    cur_val = stated["value"]
    set_as_of = stated["period"]
    cur_mid = parse_value(cur_val)[2]

    # was it reaffirmed in docs newer than where it was last stated?
    reaffirmed_through = current["period"] if stated_idx > 0 else None
    if stated_idx > 0:
        notes.append("value %r set %s; reaffirmed through %s" % (cur_val, set_as_of, current["period"]))

    # walk older for the prior DISTINCT stated value; if an older doc states the SAME
    # value, the live number was actually set even earlier -> push set_as_of back.
    prior_val, prior_as_of = "", None
    for e in trail[stated_idx + 1:]:
        if e.get("status") in STATED and parse_value(e.get("value")):
            pmid = parse_value(e["value"])[2]
            if abs(pmid - cur_mid) > 1e-9:
                prior_val, prior_as_of = e["value"], e["period"]
                break
            set_as_of = e["period"]  # same value stated earlier -> origin moves back

    # origin within the supplied window?
    origin_in_window = True
    if not prior_val:
        earliest = trail[-1]
        if earliest.get("status") not in STATED:
            origin_in_window = False
            notes.append("earliest mention (%s) reaffirms — guide set before the supplied "
                         "window; add older quarters" % earliest["period"])
        elif status in ("raised", "cut", "narrowed"):
            origin_in_window = False
            notes.append("current print reports a %s but the prior guide is outside the "
                         "supplied window; add older quarters" % status)

    # action: trust the current print's declared status; cross-check vs midpoints
    action = ACTION_FROM_STATUS.get(status)
    if action is None:  # bare "stated"/"absent"
        if prior_val:
            pmid = parse_value(prior_val)[2]
            action = "RAISE" if cur_mid > pmid + 1e-9 else ("CUT" if cur_mid < pmid - 1e-9 else "MAINTAIN")
        else:
            action = "INITIATE" if origin_in_window else "MAINTAIN"
    if prior_val and status in ("raised", "cut", "narrowed"):
        pmid = parse_value(prior_val)[2]
        implied = "RAISE" if cur_mid > pmid + 1e-9 else ("CUT" if cur_mid < pmid - 1e-9 else "MAINTAIN")
        if implied != action and not (action == "NARROW" and implied == "MAINTAIN"):
            notes.append("release declares %s but prior(%s)->new(%s) midpoint implies %s — verify"
                         % (action, prior_val, cur_val, implied))

    out.update({"current_guide": cur_val, "set_as_of": set_as_of,
                "reaffirmed_through": reaffirmed_through, "prior_guide": prior_val,
                "prior_as_of": prior_as_of, "action": action,
                "origin_in_window": origin_in_window, "notes": notes})
    return out


def reconcile(data):
    docs = data.get("docs", [])
    keys = []
    for d in docs:
        for rec in d.get("guidance", []):
            k = rec.get("guide_key")
            if k and k not in keys:
                keys.append(k)
    results = [reconcile_key(k, _sorted_trail(docs, k)) for k in keys]
    return results


def _prov(r):
    if r["set_as_of"] is None:
        return "set before window"
    if r.get("reaffirmed_through") and r["reaffirmed_through"] != r["set_as_of"]:
        return "set %s, reaffirmed thru %s" % (r["set_as_of"], r["reaffirmed_through"])
    return "set %s" % r["set_as_of"]


def render_table(results):
    head = ("| Metric | Prior Guide | Current Guide | Action | Provenance |\n"
            "|---|---|---|---|---|")
    rows = [head]
    flags = []
    for r in results:
        prior = r["prior_guide"] or "—"
        if r["prior_as_of"]:
            prior += " (%s)" % r["prior_as_of"]
        elif not r["origin_in_window"]:
            prior = "— (set before window)"
        cur = r["current_guide"] or "—"
        prov = _prov(r)
        flag = "" if r["origin_in_window"] else " ⚠"
        rows.append("| %s | %s | %s | %s%s | %s |" % (
            r.get("metric") or r["guide_key"], prior, cur, r["action"], flag, prov))
        for n in r.get("notes", []):
            if "verify" in n or "before the supplied window" in n:
                flags.append("%s: %s" % (r.get("metric") or r["guide_key"], n))
    table = "\n".join(rows)
    if flags:
        table += "\n\n" + "\n".join("> ⚠ " + f for f in flags)
    return table


def main():
    ap = argparse.ArgumentParser(description="Reconcile multi-document guidance into a lineage.")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    args = ap.parse_args()

    data = json.loads(Path(args.inp).read_text())
    results = reconcile(data)
    out = {
        "ticker": data.get("ticker"), "current_period": data.get("current_period"),
        "doc_count": len(data.get("docs", [])),
        "doc_periods": [d.get("period") for d in data.get("docs", [])],
        "guidance": results,
        "table_md": render_table(results),
        "flags": [{"metric": r.get("metric"), "notes": r["notes"]}
                  for r in results if r.get("notes")],
    }
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(json.dumps({
        "out": str(Path(args.out).resolve()),
        "ticker": out["ticker"], "current_period": out["current_period"],
        "doc_periods": out["doc_periods"], "metrics": len(results),
        "needs_more_history": [r["guide_key"] for r in results if not r["origin_in_window"]],
    }, indent=2))


if __name__ == "__main__":
    main()
