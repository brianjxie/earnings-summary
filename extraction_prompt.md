# Earnings Extraction Prompt

You extract structured data from a company's earnings release and earnings-call
transcript. Your output is consumed by a script (for beat/miss math) and an
analyst memo, so every number is keyed and every qualitative point is sourced.

## Inputs (filled per call)

- **Company:** `{{COMPANY}}`  (ticker: `{{TICKER}}`, synonyms: `{{SYNONYMS}}`)
- **Period:** `{{PERIOD}}` (e.g. "FY26 Q1")
- **Analyst's custom KPIs:** the extra metrics this analyst tracks (resolved from
  their profile + the sector catalog). Pull these IN ADDITION to the standard
  headline set; use each metric's aliases + hint to locate it, and emit its
  `key` / `unit` / `is_pp` / `higher_is_better` exactly as given here.

{{CUSTOM_KPIS}}

- **Sector themes:** the topics this analyst's sector(s) care about most. These
  add NO metrics — use them to PRIORITIZE what you surface in call highlights
  (§3) and notable items (§4).

{{THEMES}}

- **Documents:** the earnings release text and the full call transcript follow.
  Each document is delimited; the release is the authoritative source for
  reported numbers, the transcript for guidance language and management/Q&A
  commentary. PDF-sourced documents carry `--- PAGE <N> ---` markers — when a
  value or quote comes from a PDF page, cite that page number in its `source`.

  `{{DOCUMENTS}}`

## What to extract

### 1. Metrics (`metrics[]`)

Always pull this **standard headline set** (section: `"headline"`):
`revenue`, `revenue_growth` (YoY %), `gross_margin`, `op_margin`, `eps`
(specify GAAP vs non-GAAP in the label — prefer the basis the company headlines
and consensus is set on), `fcf`. Add `net_income` if disclosed.

Then pull **segment revenue** lines (section: `"segment"`) for each reported
segment / product line, and the **analyst's custom KPIs** (section: `"kpi"`)
using the aliases provided to locate them.

For each metric emit:
```
{
  "key": "revenue",                 # stable snake_case id; for custom KPIs use the KPI label verbatim
  "label": "Total Revenue",         # display name
  "unit": "$M",                     # "$M" | "$B" | "$" | "%" | "M" | "k" | "units" | ...
  "section": "headline",            # headline | segment | kpi
  "actual": 9130,                   # number only — no $, no commas, no unit, no "M"
  "prior_year": 8250,               # same period last year, if disclosed
  "prior_q": 9450,                  # immediately prior quarter, if disclosed
  "is_eps": false,                  # true ONLY for per-share metrics
  "is_pp": false,                   # true for rate/percentage LEVELS (margins, retention, growth rates)
  "higher_is_better": true,         # false for cost / loss / churn / GTN-type metrics
  "source": "Q1 release, Financial Highlights table"   # where you found `actual`
}
```

Rules:
- **Numbers only.** `"actual": 9130`, never `"$9,130M"` or `"9130"`. Convert the
  company's reported figure to the metric's `unit` ($M for most revenue lines,
  $B only if the catalog says so). Record the original phrasing in `source`.
- **Do NOT fill `my_est` or `consensus`** — those are injected later from the
  analyst's model and pasted consensus. Leave them out entirely.
- **`is_pp` = true** for any metric whose unit is `%` and represents a level
  (gross/operating margin, NRR, NIM, organic growth %, a YoY growth rate).
  Their deltas are read in points, not percent.
- **Omit, don't null.** If a metric isn't disclosed, leave it out of `metrics[]`.
  Do not emit `"actual": null`.
- **Company scope only.** Ignore figures the company cites for competitors or
  end-markets. Only this company's reported results.

### 2. Guidance (`guidance[]`)

For each forward metric the company guides, emit ONE record in the canonical shape below
(identical to `guidance_extract_prompt.md`, so the multi-document reconciler can stitch
this print together with prior quarters). Capture only what THIS release states — the
**prior guide** and the net **action vs prior** are derived later by
`reconcile_guidance.py`, not by you.
```
{
  "guide_key": "fy2026__revenue",   # CANONICAL, identical across quarters: <guide_period_norm>__<metric_snake>[__<basis>]
  "metric": "FY26 Revenue",
  "guide_period": "FY26",            # the period being GUIDED (not this print's quarter)
  "unit": "$B",
  "basis": "",                       # non-GAAP | GAAP | CC | as-reported | "" (only if multiple bases are guided)
  "status": "raised",                # initiated | raised | cut | narrowed | reaffirmed | stated | withdrawn
  "value": "40.7 - 41.1",            # SIGNED/normalized as stated THIS print (decline -> negative; "" if reaffirmed w/o a number)
  "quote": "...verbatim sentence...",
  "source": "guidance table in release"
}
```
- **`guide_key`** must be byte-identical when the same metric is guided in another quarter
  (that's how the lineage stitches): `fy2026` / `q2_2026` period stem + snake_case metric +
  optional basis (`cc`, `as_reported`, …). See `guidance_extract_prompt.md` for the recipe.
- **`status`**: `reaffirmed` = explicitly unchanged/reiterated (often `value: ""`);
  `initiated` = first time for this period; `raised`/`cut`/`narrowed` = explicit change;
  `stated` = a number with no change language; `withdrawn` = pulled.
- **`value` is SIGNED/normalized** (a "down 3%" guide is `-3%`); ranges as `"lo - hi"`.
- Also write a 2-4 sentence **`guidance_narrative`** summarizing the net change in posture
  (raised/cut, by how much, the reason management gave, and any segment/margin change),
  with the key driver quoted.

### 3. Call highlights (`call_highlights`)

From the transcript:
```
"call_highlights": {
  "prepared_remarks": [
    {"theme": "AI/Agentforce traction", "speaker": "Marc Benioff (CEO)",
     "point": "one-sentence paraphrase", "quote": "verbatim sentence", "source": "prepared remarks"}
  ],
  "qa": [
    {"topic": "Margin trajectory FY27", "asked_by": "Analyst, Morgan Stanley",
     "exchange": "what was asked + how management answered, 1-2 sentences",
     "quote": "the most load-bearing verbatim sentence from the answer",
     "source": "Q&A"}
  ]
}
```
- 4-8 prepared-remark themes; 4-8 Q&A items. Prioritize: the **sector themes**
  listed in the inputs above, guidance color, demand/pipeline commentary,
  margin/cost actions, capital allocation, and any point where management was
  evasive or pushed back. `quote` must be verbatim.

### 4. Notable items (`notable[]`)

One-line flags an analyst should not miss: one-time items, accounting changes,
buyback/dividend actions, segment realignments, management changes, M&A,
litigation. Each `{ "item": "...", "source": "..." }`. Omit if none.

## Output

Write a single JSON file (no prose, no markdown fences) with this shape:
```json
{
  "company": "{{COMPANY}}", "ticker": "{{TICKER}}", "period": "{{PERIOD}}",
  "report_date": "<date the company reported, e.g. 'May 28, 2026'>",
  "currency": "USD",
  "metrics": [ ... ],
  "guidance": [ ... ],
  "guidance_narrative": "...",
  "call_highlights": { "prepared_remarks": [ ... ], "qa": [ ... ] },
  "notable": [ ... ]
}
```

Then return a one-paragraph summary (under 120 words): how many metrics you
pulled (headline/segment/kpi), which custom KPIs you could NOT find and why,
and the net guidance action.

### Common mistakes to avoid
- ✗ `"actual": "$9.13B"` — must be a unitless number in the metric's `unit`.
- ✗ Filling `my_est` / `consensus` — leave them out.
- ✗ Inventing a KPI value because the analyst asked for it — if it isn't
  disclosed, omit it and say so in the summary.
- ✗ Paraphrasing a `quote` — quotes are verbatim or absent.
- ✗ Mixing GAAP and non-GAAP within one metric — pick the headline basis and
  state it in the label.
