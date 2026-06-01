#!/usr/bin/env python3
"""Validate kpi_catalog.yaml — the cross-sector KPI scaffold.

Checks the invariants the resolver and the picker rely on:
  - structural: every sector has id/label/kpis/themes; every metric has
    key/label/unit/higher_is_better and a non-empty extraction_hint
  - keys are snake_case and unique WITHIN a sector
  - shared keys ACROSS sectors (and vs the standard headline set) describe the
    SAME metric: identical unit / is_pp / higher_is_better — so a company that
    spans sectors (extends: [a, b]) de-dupes cleanly to one row

Run from the repo root:
    .venv/bin/python .claude/skills/earnings-summary/scripts/validate_catalog.py

Prints a JSON summary and exits non-zero (listing the problems) if anything fails.
"""
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("error: pyyaml not installed (pip install -r requirements.txt)", file=sys.stderr)
    sys.exit(2)

CATALOG = Path(__file__).resolve().parent.parent / "kpi_catalog.yaml"
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
REQUIRED_KPI_FIELDS = ("key", "label", "unit", "higher_is_better")


def shape(m):
    """The (unit, is_pp, higher_is_better) signature a shared key must agree on."""
    return (m.get("unit"), bool(m.get("is_pp", False)), bool(m.get("higher_is_better", True)))


def main():
    errors, warnings = [], []

    if not CATALOG.exists():
        print(f"error: {CATALOG} not found", file=sys.stderr)
        return 2
    data = yaml.safe_load(CATALOG.read_text()) or {}

    sectors = data.get("sectors")
    headline = data.get("standard_headline")
    if not isinstance(sectors, list) or not sectors:
        errors.append("top-level `sectors` missing or empty")
        sectors = []
    if not isinstance(headline, list) or not headline:
        errors.append("top-level `standard_headline` missing or empty")
        headline = []

    shapes = {}          # key -> list of (where, shape) for cross-scope consistency
    total_metrics = 0

    def register(where, m):
        if m.get("key"):
            shapes.setdefault(m["key"], []).append((where, shape(m)))

    for s in sectors:
        sid = s.get("id", "<no-id>")
        if not s.get("id"):
            errors.append(f"sector missing `id`: {s.get('label', s)}")
        if not s.get("label"):
            warnings.append(f"[{sid}] missing `label`")
        if not isinstance(s.get("themes"), list) or not s.get("themes"):
            errors.append(f"[{sid}] `themes` missing or empty")

        kpis = s.get("kpis")
        if not isinstance(kpis, list) or not kpis:
            errors.append(f"[{sid}] `kpis` missing or empty")
            kpis = []

        seen = set()
        for m in kpis:
            total_metrics += 1
            ident = m.get("key", m.get("label", "?"))
            for f in REQUIRED_KPI_FIELDS:
                if f not in m or m[f] in (None, ""):
                    errors.append(f"[{sid}] metric {ident}: missing `{f}`")
            key = m.get("key")
            if key:
                if not KEY_RE.match(key):
                    errors.append(f"[{sid}] key not snake_case: {key!r}")
                if key in seen:
                    errors.append(f"[{sid}] duplicate key within sector: {key!r}")
                seen.add(key)
            if "higher_is_better" in m and not isinstance(m["higher_is_better"], bool):
                errors.append(f"[{sid}] {ident}: higher_is_better must be true/false")
            if not str(m.get("extraction_hint", "")).strip():
                errors.append(f"[{sid}] {ident}: empty extraction_hint")
            register(sid, m)

    for m in headline:
        if not m.get("key"):
            errors.append(f"standard_headline entry missing key: {m}")
            continue
        if not m.get("unit"):
            errors.append(f"standard_headline {m['key']}: missing unit")
        register("standard_headline", m)

    # Shared keys (appear in >1 scope) must agree on shape.
    shared = {}
    for key, occ in shapes.items():
        wheres = [w for w, _ in occ]
        if len(wheres) > 1:
            shared[key] = wheres
            if len({sig for _, sig in occ}) > 1:
                detail = "; ".join(f"{w}={sig}" for w, sig in occ)
                errors.append(f"shared key {key!r} disagrees on unit/is_pp/direction: {detail}")

    summary = {
        "catalog": str(CATALOG),
        "sectors": len(sectors),
        "sector_ids": [s.get("id") for s in sectors],
        "total_sector_metrics": total_metrics,
        "unique_keys": len(shapes),
        "shared_keys": shared,
        "headline_metrics": len(headline),
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(summary, indent=2))

    if errors:
        print(f"\nFAIL: {len(errors)} error(s).", file=sys.stderr)
        return 1
    print(f"\nOK: {len(sectors)} sectors, {total_metrics} sector metrics, "
          f"{len(shared)} shared keys, {len(warnings)} warning(s), no errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
