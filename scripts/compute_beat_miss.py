#!/usr/bin/env python3
"""Deterministic beat/miss + delta computation for the earnings-summary skill.

The extraction agent pulls raw numbers (actuals, prior-year, prior-quarter) from
the release/transcript; the runbook merges in the analyst's model estimates and
pasted consensus. This script does ALL the arithmetic — % deltas, YoY/QoQ, and
the BEAT / MISS / IN-LINE verdicts — and renders the markdown scorecard tables,
so the memo never relies on the model doing math.

Input JSON (--in):
{
  "company": "Salesforce", "ticker": "CRM", "period": "FY26 Q1",
  "inline_band_pct": 2.0,        # |delta| <= this %% vs a benchmark => IN-LINE
  "eps_inline_band_abs": 0.02,   # is_eps metrics: |delta| in $ <= this => IN-LINE
  "pp_inline_band": 0.5,         # is_pp metrics: |delta| in pts <= this => IN-LINE
  "metrics": [
    {
      "key": "revenue", "label": "Total Revenue", "unit": "$M",
      "section": "headline",          # headline | segment | kpi
      "actual": 9130, "my_est": 9100, "consensus": 9070,
      "prior_year": 8250, "prior_q": 9450,
      "is_eps": false, "is_pp": false, "higher_is_better": true,
      "source": "Q1 release, Financial Highlights table"
    }
  ]
}

A metric's verdict is taken vs consensus when consensus is present, else vs the
analyst's own estimate. is_pp metrics (margins, retention rates expressed as
point moves) delta in percentage points; is_eps metrics use an absolute cent
band because small denominators make %% deltas noisy.

Output: writes the enriched result to --out and prints a compact summary JSON to
stdout. The enriched result adds per-metric deltas/verdicts, per-section rendered
markdown tables ("tables_md", keyed by section), and a one-line "headline".

Optional --profile <profiles/slug.yaml>: reads preferences.inline_band_pct /
eps_inline_band_abs / pp_inline_band as defaults when not set in the input JSON.
"""
import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

SECTION_TITLES = {
    "headline": "Headline Scorecard",
    "segment": "Segment Detail",
    "kpi": "Key KPIs",
}
SECTION_ORDER = ["headline", "segment", "kpi"]


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def pct(a, b):
    """Percent change of a vs b, or None when not computable."""
    if not _num(a) or not _num(b) or b == 0:
        return None
    return (a - b) / abs(b) * 100.0


def fmt_value(v, unit):
    if not _num(v):
        return ""
    u = (unit or "").strip()
    if u in ("%", "pp", "ppt"):
        return f"{v:,.1f}%"
    if u == "bps":
        return f"{v:,.0f} bps"
    if u == "$":
        return f"${v:,.2f}"
    if u in ("$M", "$mm", "$mn"):
        return f"${v:,.0f}M"
    if u in ("$B", "$bn"):
        return f"${v:,.2f}B"
    if u == "x":                       # multiples: book-to-bill, net leverage
        return f"{v:,.2f}x"
    if u in ("ratio", "ratios"):       # bare ratio, no unit suffix
        return f"{v:,.2f}"
    if u in ("days", "day"):           # DSO / inventory days / cash runway in days
        return f"{v:,.0f} days"
    if u in ("", "M", "mm", "k", "K", "units", "patients", "stores", "subs"):
        return f"{v:,.0f}{u}"
    return f"{v:,.2f} {u}".strip()


def fmt_delta_vs(metric, b):
    """Signed delta of actual vs benchmark b, respecting metric type."""
    a = metric.get("actual")
    if not _num(a) or not _num(b):
        return ""
    if metric.get("is_pp"):
        return f"{a - b:+.2f}pp"
    p = pct(a, b)
    if p is None:
        return ""
    if metric.get("is_eps"):
        return f"{a - b:+.2f} ({p:+.1f}%)"
    return f"{p:+.1f}%"


def verdict_vs(metric, b, bands):
    a = metric.get("actual")
    if not _num(a) or not _num(b):
        return None
    hib = metric.get("higher_is_better", True)
    d = a - b
    if metric.get("is_eps"):
        within = abs(d) <= bands["eps_abs"]
    elif metric.get("is_pp"):
        within = abs(d) <= bands["pp"]
    elif b != 0:
        within = (abs(d) / abs(b) * 100.0) <= bands["pct"]
    else:
        within = False
    if within:
        return "IN-LINE"
    better = (d > 0) == hib
    return "BEAT" if better else "MISS"


def enrich(metric, bands):
    """Attach computed deltas + verdicts to a metric (mutates and returns it)."""
    metric["delta_vs_est"] = fmt_delta_vs(metric, metric.get("my_est"))
    metric["delta_vs_cons"] = fmt_delta_vs(metric, metric.get("consensus"))
    metric["yoy"] = fmt_delta_vs(metric, metric.get("prior_year"))
    metric["qoq"] = fmt_delta_vs(metric, metric.get("prior_q"))
    v_est = verdict_vs(metric, metric.get("my_est"), bands)
    v_cons = verdict_vs(metric, metric.get("consensus"), bands)
    metric["verdict_vs_est"] = v_est
    metric["verdict_vs_cons"] = v_cons
    # Headline verdict: vs Street (consensus) by convention, else vs own model.
    metric["verdict"] = v_cons if v_cons is not None else v_est
    return metric


def render_table(metrics, unit_in_label=False):
    """Render one section's metrics as a markdown table."""
    head = (
        "| Metric | Actual | My Est | Δ vs Est | Consensus | Δ vs Cons | YoY | Read |\n"
        "|---|---|---|---|---|---|---|---|"
    )
    rows = [head]
    for m in metrics:
        label = m.get("label", m.get("key", "?"))
        unit = m.get("unit", "")
        rows.append(
            "| {label} | {actual} | {est} | {dest} | {cons} | {dcons} | {yoy} | {read} |".format(
                label=label,
                actual=fmt_value(m.get("actual"), unit),
                est=fmt_value(m.get("my_est"), unit),
                dest=m.get("delta_vs_est", ""),
                cons=fmt_value(m.get("consensus"), unit),
                dcons=m.get("delta_vs_cons", ""),
                yoy=m.get("yoy", ""),
                read=m.get("verdict") or "",
            )
        )
    return "\n".join(rows)


def _clean_delta(metric, b):
    """Compact delta for the headline one-liner: pp for rates, % otherwise."""
    a = metric.get("actual")
    if not _num(a) or not _num(b):
        return ""
    if metric.get("is_pp"):
        return f"{a - b:+.1f}pp"
    p = pct(a, b)
    return f"{p:+.1f}%" if p is not None else ""


def build_headline(headline_metrics):
    """One-line summary from the headline-section metrics."""
    parts = []
    for m in headline_metrics:
        v = m.get("verdict")
        if not v:
            continue
        if _num(m.get("consensus")):
            delta, bench = _clean_delta(m, m.get("consensus")), "vs Street"
        else:
            delta, bench = _clean_delta(m, m.get("my_est")), "vs est"
        label = m.get("label", m.get("key", "?"))
        tail = f" ({delta} {bench})" if delta else ""
        parts.append(f"{label} {v}{tail}")
    return "; ".join(parts) if parts else "No benchmarked headline metrics."


def load_bands(data, profile_path):
    bands = {
        "pct": data.get("inline_band_pct", 2.0),
        "eps_abs": data.get("eps_inline_band_abs", 0.02),
        "pp": data.get("pp_inline_band", 0.5),
    }
    if profile_path and yaml is not None:
        try:
            prof = yaml.safe_load(Path(profile_path).read_text()) or {}
            prefs = prof.get("preferences", {}) or {}
            # Input JSON wins; profile preferences fill gaps; hardcoded defaults last.
            bands["pct"] = data.get("inline_band_pct", prefs.get("inline_band_pct", bands["pct"]))
            bands["eps_abs"] = data.get(
                "eps_inline_band_abs", prefs.get("eps_inline_band_abs", bands["eps_abs"])
            )
            bands["pp"] = data.get("pp_inline_band", prefs.get("pp_inline_band", bands["pp"]))
        except Exception as e:
            print(f"warn: could not read profile bands: {e}", file=sys.stderr)
    return bands


def main():
    ap = argparse.ArgumentParser(description="Compute beat/miss + deltas for an earnings scorecard.")
    ap.add_argument("--in", dest="inp", required=True, help="input metrics JSON")
    ap.add_argument("--out", dest="out", required=True, help="enriched output JSON")
    ap.add_argument("--profile", dest="profile", help="optional analyst profile YAML for default bands")
    args = ap.parse_args()

    data = json.loads(Path(args.inp).read_text())
    bands = load_bands(data, args.profile)

    metrics = data.get("metrics", [])
    for m in metrics:
        enrich(m, bands)

    by_section = {}
    for m in metrics:
        by_section.setdefault(m.get("section", "headline"), []).append(m)

    tables_md = {}
    sections_in_play = [s for s in SECTION_ORDER if s in by_section]
    sections_in_play += [s for s in by_section if s not in SECTION_ORDER]
    for s in sections_in_play:
        title = SECTION_TITLES.get(s, s.title())
        tables_md[s] = f"### {title}\n\n" + render_table(by_section[s])

    headline = build_headline(by_section.get("headline", []))

    counts = {"beat": 0, "miss": 0, "inline": 0, "no_benchmark": 0}
    for m in metrics:
        v = m.get("verdict")
        if v == "BEAT":
            counts["beat"] += 1
        elif v == "MISS":
            counts["miss"] += 1
        elif v == "IN-LINE":
            counts["inline"] += 1
        else:
            counts["no_benchmark"] += 1

    result = {
        "company": data.get("company"),
        "ticker": data.get("ticker"),
        "period": data.get("period"),
        "bands": bands,
        "headline": headline,
        "counts": counts,
        "metrics": metrics,
        "tables_md": tables_md,
    }
    Path(args.out).write_text(json.dumps(result, indent=2))

    print(json.dumps({
        "out": str(Path(args.out).resolve()),
        "ticker": result["ticker"],
        "period": result["period"],
        "headline": headline,
        "counts": counts,
        "metric_count": len(metrics),
        "sections": sections_in_play,
    }, indent=2))


if __name__ == "__main__":
    main()
