#!/usr/bin/env python3
"""Resolve an analyst profile against kpi_catalog.yaml into a flat KPI list.

The profile is a thin OVERLAY over the sector catalog:

    extends:  [software_saas, ...]   # sector ids; a company can span sectors
    pick:     [arr, nrr, ...]        # optional subset of inherited keys (default: all)
    add:      [ {full metric def} ]  # custom metrics in no catalog sector
    override: { key: {field: val} }  # shallow-merge tweaks onto an inherited metric

Resolution = (union of `extends` sectors' metrics, filtered by `pick`, de-duped by
key with alias-union) + `add`, then `override` applied, then any key in the
always-pulled `standard_headline` set is DROPPED (those rows come from the
extractor's headline pass — keeping them here would duplicate the row). Order
follows `pick` when given, else sector/catalog order, with `add`-only keys last.

Back-compat: a profile with an inline `kpis:` list and NO `extends` is returned
as-is (today's behavior); a missing `key` is derived by slugifying the label.

--add-from <json>: merge a list of extra metric defs (same shape as `add:`) into the
resolved set — used by Step 5.5 to fold discovery-confirmed, run-only KPIs into
{{CUSTOM_KPIS}} without persisting them to the profile.

Output: the resolved KPI list (section "kpi") the rest of the pipeline consumes
(extraction_prompt.md {{CUSTOM_KPIS}} and the scorecard merge). Prints the full
result JSON to stdout; also writes it to --out if given. Exits non-zero if there
are warnings (unknown sector / pick typo / add collision / override miss).
"""
import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("error: pyyaml not installed (pip install -r requirements.txt)", file=sys.stderr)
    sys.exit(2)

DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "kpi_catalog.yaml"
DEF_FIELDS = ("key", "label", "aliases", "unit", "is_pp", "higher_is_better", "extraction_hint")


def slugify(label):
    s = re.sub(r"[^a-z0-9]+", "_", str(label).lower()).strip("_")
    return s or "metric"


def clean_metric(m):
    """Keep only definition fields; default section=kpi; ensure a key + aliases."""
    out = {k: m[k] for k in DEF_FIELDS if k in m and m[k] is not None}
    if not out.get("key"):
        out["key"] = slugify(out.get("label", "metric"))
    out.setdefault("aliases", [])
    out.setdefault("higher_is_better", True)
    out["section"] = "kpi"
    return out


def load_catalog(path):
    cat = yaml.safe_load(Path(path).read_text()) or {}
    sectors = {s["id"]: [clean_metric(m) for m in s.get("kpis", [])] for s in cat.get("sectors", [])}
    sector_themes = {s["id"]: list(s.get("themes", []) or []) for s in cat.get("sectors", [])}
    headline_keys = {m["key"] for m in cat.get("standard_headline", []) if m.get("key")}
    return sectors, headline_keys, sector_themes


def render_kpis_block(kpis):
    """Ready-to-paste markdown for the extraction prompt's {{CUSTOM_KPIS}}."""
    if not kpis:
        return "_(No custom KPIs beyond the standard headline set.)_"
    lines = []
    for m in kpis:
        flags = ["rate/level (is_pp)" if m.get("is_pp") else "value",
                 "higher is better" if m.get("higher_is_better", True) else "lower is better"]
        aliases = ", ".join(m.get("aliases", []) or []) or "—"
        lines.append(
            "- **{label}** (`{key}`, unit `{unit}`, {flags})\n"
            "  - aliases: {aliases}\n"
            "  - hint: {hint}".format(
                label=m.get("label", m["key"]), key=m["key"], unit=m.get("unit", ""),
                flags="; ".join(flags), aliases=aliases,
                hint=m.get("extraction_hint", "—"),
            )
        )
    return "\n".join(lines)


def render_themes_block(themes):
    """Ready-to-paste markdown for the extraction prompt's {{THEMES}}."""
    if not themes:
        return "_(No sector themes — use the standard highlight priorities.)_"
    return "\n".join("- " + t for t in themes)


def _drop_headline(keys, resolved, headline_keys, notes):
    dropped = [k for k in keys if k in headline_keys]
    if dropped:
        notes.append("dropped (already in standard_headline): " + ", ".join(dropped))
    return [k for k in keys if k not in headline_keys]


def resolve(profile, sectors, headline_keys, sector_themes, extra_adds=None):
    warnings, notes = [], []
    extra_adds = list(extra_adds or [])
    if extra_adds:
        notes.append("merged %d --add-from metric(s)" % len(extra_adds))
    extends = profile.get("extends")

    # ---- legacy mode: inline kpis, no extends ----
    if not extends:
        # de-dupe by key (later def wins on value, keeps first position) so an
        # --add-from metric that repeats an inline key yields one row, not two.
        deduped = {}
        for m in [clean_metric(x) for x in (profile.get("kpis") or [])] + [clean_metric(x) for x in extra_adds]:
            deduped[m["key"]] = m
        kpis = list(deduped.values())
        keys = _drop_headline([m["key"] for m in kpis], None, headline_keys, notes)
        kpis = [m for m in kpis if m["key"] in set(keys)]
        return kpis, {"mode": "legacy", "themes": [], "warnings": warnings, "notes": notes}

    # ---- overlay mode ----
    if isinstance(extends, str):
        extends = [extends]
    pick = profile.get("pick")
    pick_set = set(pick) if pick else None

    resolved = {}  # key -> metric (insertion-ordered)
    for sid in extends:
        if sid not in sectors:
            warnings.append("unknown sector in `extends`: %r" % sid)
            continue
        for m in sectors[sid]:
            if pick_set is not None and m["key"] not in pick_set:
                continue
            if m["key"] in resolved:  # shared key across sectors: union aliases, keep first def
                merged = list(resolved[m["key"]].get("aliases", []))
                for a in m.get("aliases", []):
                    if a not in merged:
                        merged.append(a)
                resolved[m["key"]]["aliases"] = merged
                notes.append("merged shared key across sectors: " + m["key"])
            else:
                resolved[m["key"]] = dict(m)

    if pick_set is not None:
        for k in pick:
            if k not in resolved:
                warnings.append("`pick` key not found in %s: %r" % (extends, k))

    # custom metrics (and any legacy `kpis` carried alongside `extends`)
    add_list = list(profile.get("add") or [])
    if profile.get("kpis"):
        notes.append("profile has both `extends` and legacy `kpis`; treating `kpis` as `add`")
        add_list += profile["kpis"]
    add_list += extra_adds
    for m in add_list:
        cm = clean_metric(m)
        if cm["key"] in resolved:
            warnings.append("`add` key collides with an inherited metric (add wins): " + cm["key"])
        resolved[cm["key"]] = cm

    # override tweaks
    for key, patch in (profile.get("override") or {}).items():
        if key in resolved:
            resolved[key].update(patch)
        else:
            warnings.append("`override` key not in resolved set (ignored): %r" % key)

    # ordering: pick first (in pick order), then the rest in insertion order
    if pick:
        ordered = [k for k in pick if k in resolved] + [k for k in resolved if k not in pick]
    else:
        ordered = list(resolved.keys())

    ordered = _drop_headline(ordered, resolved, headline_keys, notes)

    themes = []
    for sid in extends:
        for t in sector_themes.get(sid, []):
            if t not in themes:
                themes.append(t)

    return [resolved[k] for k in ordered], {"mode": "overlay", "extends": extends,
                                            "themes": themes, "warnings": warnings, "notes": notes}


def main():
    ap = argparse.ArgumentParser(description="Resolve an analyst profile into a KPI list.")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    ap.add_argument("--add-from", dest="add_from",
                    help="JSON file: a list of extra metric defs (same shape as profile "
                         "`add:`) to merge into the resolved set — e.g. discovery-confirmed "
                         "KPIs kept for this run only (Step 5.5).")
    ap.add_argument("--out")
    args = ap.parse_args()

    profile = yaml.safe_load(Path(args.profile).read_text()) or {}
    extra_adds = []
    if args.add_from:
        extra_adds = json.loads(Path(args.add_from).read_text())
        if not isinstance(extra_adds, list):
            print("error: --add-from must be a JSON list of metric defs", file=sys.stderr)
            sys.exit(2)
    sectors, headline_keys, sector_themes = load_catalog(args.catalog)
    kpis, summary = resolve(profile, sectors, headline_keys, sector_themes, extra_adds=extra_adds)

    result = {
        "profile": args.profile,
        "add_from": args.add_from,
        "analyst": profile.get("analyst"),
        "slug": profile.get("slug"),
        "mode": summary["mode"],
        "kpi_count": len(kpis),
        "kpi_keys": [m["key"] for m in kpis],
        "kpis": kpis,
        "themes": summary.get("themes", []),
        "custom_kpis_block": render_kpis_block(kpis),
        "themes_block": render_themes_block(summary.get("themes", [])),
        "warnings": summary["warnings"],
        "notes": summary["notes"],
    }
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 1 if summary["warnings"] else 0


if __name__ == "__main__":
    sys.exit(main())
