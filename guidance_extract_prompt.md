# Guidance Extraction Prompt (one release → guidance statements)

You extract ONLY the forward **guidance** a single earnings release states, so a script
can stitch guidance across several quarters into a lineage (to resolve "guidance
unchanged" back to where the number was actually set). You do **not** extract reported
actuals, KPIs, or commentary here — guidance only.

## Inputs (filled per call)

- **Company:** `{{COMPANY}}` (ticker `{{TICKER}}`, synonyms: `{{SYNONYMS}}`)
- **This document's period:** `{{DOC_PERIOD}}` — the quarter whose release this is (e.g.
  "FY25 Q4"). Every record you emit describes what THIS release said.
- **Document:** the earnings release text follows. PDF-sourced text carries
  `--- PAGE <N> ---` markers; cite the page in `source`.

{{DOCUMENT}}

## What to extract — `guidance[]`

One record per **forward-looking** metric the release addresses (outlook / "expects" /
"now sees" / reaffirms / withdraws). Skip reported actuals and anything purely historical.

```
{
  "guide_key": "fy2026__adjusted_eps",   // CANONICAL — must be identical across quarters
  "metric": "FY26 Adjusted EPS",          // human label
  "guide_period": "FY26",                 // the period being guided (NOT this doc's period)
  "unit": "$",                            // $ | $M | $B | % | x | M | k | units | ...
  "basis": "non-GAAP",                    // optional: non-GAAP | GAAP | CC | as-reported | ""
  "status": "cut",                        // see vocabulary below
  "value": "1.45 - 1.79",                 // SIGNED / normalized, as stated THIS print ("" if reaffirmed w/o a number)
  "quote": "...verbatim sentence...",     // exact text from the release
  "source": "2026 Full Year Outlook (p.3)"
}
```

### `guide_key` — the matching key (most important field)

It MUST be byte-identical when the same metric is guided in a different quarter, so build
it deterministically:

`guide_key = <guide_period_norm> + "__" + <metric_snake> [ + "__" + <basis_norm> ]`

- **guide_period_norm:** full year → `fyYYYY` (e.g. "full year 2026" / "FY26" / "2026" →
  `fy2026`); a quarter → `qN_YYYY` (e.g. "Q2 2026" / "second quarter 2026" → `q2_2026`).
- **metric_snake:** the canonical concept in snake_case, basis-word stripped:
  `adjusted_eps`, `adjusted_ebitda`, `adjusted_net_income`, `revenue`, `net_yield`,
  `adjusted_ncc_ex_fuel`, `operating_margin`, `capacity_days`, `occupancy`, … Use the
  SAME stem every quarter (don't let phrasing changes alter it).
- **basis_norm (only if the company guides multiple bases of the same metric):** `cc`
  (constant currency), `as_reported`, `gaap`, `non_gaap`. If only one basis is guided,
  omit it. (e.g. `fy2026__net_yield__cc` vs `fy2026__net_yield__as_reported`.)

### `status` vocabulary (what THIS release did to the guide)

- `initiated` — guidance for this period/metric given for the FIRST time.
- `raised` / `cut` / `narrowed` — explicitly changed vs the company's prior guide.
- `reaffirmed` — explicitly reiterated / "unchanged" / "maintained" (often **no new
  number** → `value: ""`).
- `stated` — a number is given but the release uses no raise/cut/reaffirm language (let
  the script infer the move).
- `withdrawn` — guidance pulled / suspended.

### Rules
- **`value` is SIGNED and normalized.** A decline → negative (`"-3.0% to -5.0%"` or the
  financial convention `"(3.0%) - (5.0%)"`); growth → positive (`"+1.0%"`). Ranges as
  `"lo - hi"`; points as a single number. Strip prose like "approximately/about" but you
  may keep `~`. For a bare `reaffirmed` with no restated figure, use `value: ""`.
- **Quotes are verbatim.** No paraphrase. A record with no real `quote` is useless.
- **Company scope only**; forward-looking only; omit a metric the release doesn't address
  (don't emit `absent` rows — just leave them out).

## Output

Write a single JSON object (no prose, no fences):
```json
{ "doc_period": "{{DOC_PERIOD}}", "ticker": "{{TICKER}}", "guidance": [ ... ] }
```
Then return one sentence: how many guidance records, and which periods they guide (e.g.
"7 records — FY26 + Q2'26").

### Common mistakes
- ✗ Inconsistent `guide_key` across quarters (the #1 failure — the lineage won't stitch).
- ✗ Putting THIS doc's period in `guide_period` (it's the period being *guided*).
- ✗ Unsigned values for declines (a "down 3%" guide must be `-3%`, not `3%`).
- ✗ Emitting reported actuals or KPIs here — guidance only.
