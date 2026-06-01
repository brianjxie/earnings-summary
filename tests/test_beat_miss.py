#!/usr/bin/env python3
"""Unit tests for compute_beat_miss: verdict direction (incl. lower-is-better) and
fmt_value unit formatting. Pure stdlib; no fixtures needed.

Run from the repo root:
  .venv/bin/python .claude/skills/earnings-summary/tests/test_beat_miss.py
Exit code 0 = PASS, 1 = FAIL.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import compute_beat_miss as cbm  # noqa: E402

BANDS = {"pct": 2.0, "eps_abs": 0.02, "pp": 0.5}
fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r}, want {want!r}")


# --- verdict_vs: direction, including LOWER-IS-BETTER metrics ---
check("hib beat (above)", cbm.verdict_vs({"actual": 110, "higher_is_better": True}, 100, BANDS), "BEAT")
check("hib miss (below)", cbm.verdict_vs({"actual": 90, "higher_is_better": True}, 100, BANDS), "MISS")
# lower-is-better $ metric (e.g. costs, opex): actual BELOW the benchmark => BEAT
check("lib beat (below)", cbm.verdict_vs({"actual": 90, "higher_is_better": False}, 100, BANDS), "BEAT")
check("lib miss (above)", cbm.verdict_vs({"actual": 110, "higher_is_better": False}, 100, BANDS), "MISS")
# lower-is-better is_pp metric (e.g. gross-to-net): -1.0pp vs est, beyond the 0.5pp band => BEAT
check("lib pp beat", cbm.verdict_vs({"actual": 29.0, "is_pp": True, "higher_is_better": False}, 30.0, BANDS), "BEAT")
check("lib pp miss", cbm.verdict_vs({"actual": 31.0, "is_pp": True, "higher_is_better": False}, 30.0, BANDS), "MISS")
# in-line within the pp band (0.3pp <= 0.5)
check("pp inline", cbm.verdict_vs({"actual": 30.3, "is_pp": True, "higher_is_better": True}, 30.0, BANDS), "IN-LINE")
# is_eps cent band: within 2c => IN-LINE; beyond => by direction
check("eps inline", cbm.verdict_vs({"actual": 2.46, "is_eps": True, "higher_is_better": True}, 2.45, BANDS), "IN-LINE")
check("eps beat", cbm.verdict_vs({"actual": 2.50, "is_eps": True, "higher_is_better": True}, 2.45, BANDS), "BEAT")
# % band: 1% move <= 2% => IN-LINE
check("pct inline", cbm.verdict_vs({"actual": 101, "higher_is_better": True}, 100, BANDS), "IN-LINE")
# no benchmark => None
check("no benchmark", cbm.verdict_vs({"actual": 100, "higher_is_better": True}, None, BANDS), None)

# --- fmt_value: Stage 4 unit additions ---
check("fmt x (leverage)", cbm.fmt_value(5.3, "x"), "5.30x")
check("fmt x (book-to-bill)", cbm.fmt_value(1.05, "x"), "1.05x")
check("fmt ratio", cbm.fmt_value(1.25, "ratio"), "1.25")
check("fmt days", cbm.fmt_value(45, "days"), "45 days")
check("fmt bps", cbm.fmt_value(120, "bps"), "120 bps")
# --- fmt_value: regression on existing units ---
check("fmt %", cbm.fmt_value(103.8, "%"), "103.8%")
check("fmt $M", cbm.fmt_value(2300, "$M"), "$2,300M")
check("fmt $B", cbm.fmt_value(2.3, "$B"), "$2.30B")
check("fmt $", cbm.fmt_value(0.23, "$"), "$0.23")
check("fmt M", cbm.fmt_value(103, "M"), "103M")
check("fmt empty-unit", cbm.fmt_value(5700000, ""), "5,700,000")
check("fmt non-numeric", cbm.fmt_value(None, "$M"), "")

verdict = "PASS" if not fails else "FAIL"
print(f"{verdict} - {len(fails)} failure(s)")
for f in fails:
    print("  FAIL:", f)
sys.exit(0 if not fails else 1)
