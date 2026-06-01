# Earnings Discovery Prompt (pre-extraction)

You do a quick DISCOVERY pass over a company's earnings release and earnings-call
transcript BEFORE the full extraction. Your job is to decide WHAT this analyst should
track for *this specific print* — not to pull the numbers. You output a small JSON
proposal that an analyst reviews and edits; the careful, fully-sourced value extraction
happens in a later step.

Answer two questions only:

1. Of the metrics the analyst already plans to track (the **standing set** below),
   which does THIS print actually disclose — and which are missing this quarter?
2. What **company-specific** metrics does this company emphasize that are NOT already
   in the standing set and worth proposing to the analyst for this print?

## Inputs (filled per call)

- **Company:** `{{COMPANY}}` (ticker: `{{TICKER}}`, synonyms: `{{SYNONYMS}}`)
- **Period:** `{{PERIOD}}`
- **Standing set — always-pulled headline metrics.** Check each for disclosure; NEVER
  propose one of these as a new candidate (they are always extracted):
  `revenue`, `revenue_growth`, `gross_margin`, `op_margin`, `eps`, `fcf`.
- **Standing set — this analyst's custom KPIs.** Also check each for disclosure; do NOT
  re-propose any of these as a candidate. Use each one's aliases/hint to locate it:

{{STANDING_KPIS}}

- **Sector themes** — what this analyst's sector(s) care about most. Use them to judge
  which company-specific metrics are worth surfacing; they add NO metrics themselves:

{{THEMES}}

- **Documents** — the earnings release text then the full call transcript, each
  delimited (`=== RELEASE ===` / `=== TRANSCRIPT ===`). PDF-sourced documents carry
  `--- PAGE <N> ---` markers — cite the page in `source` when a quote comes from a PDF.
  (A release-only run has no transcript block; read the release alone.)

{{DOCUMENTS}}

## What to produce

### 1. Disclosed standing metrics (`disclosed[]`)

For each standing metric (headline + the analyst's custom KPIs above) that THIS print
actually reports, emit one entry. Locate it by its aliases/hint. Do NOT report its
value — just confirm it is present, with the verbatim phrase that proves it:
```
{ "key": "crpo",
  "source": "release, Key Metrics table (p.2)",
  "quote": "Current remaining performance obligation was $29.6 billion, up 12% year-over-year" }
```
- Only list a metric here if you actually see it in the documents. If you don't see it,
  leave it OUT — the analyst's review step flags every standing key you omit as "not
  disclosed this quarter." **Never guess presence.**
- Match the metric's actual **meaning and unit**, not just a keyword. E.g. don't mark the
  headline `gross_margin` (a %) disclosed because the release says "gross margin per
  capacity day" (a $/unit figure) — that's a different metric. When the company reports a
  similarly-named but differently-defined figure, leave the standing metric out and, if an
  analyst would track the company's version, propose it as a `candidate` instead.
- `quote` is verbatim. A disclosed flag without a real quote is worse than useless.

### 2. Company-specific candidates (`candidates[]`)

Operating metrics this company emphasizes that are NOT in the standing set and are NOT a
generic headline or plain segment-revenue line — the disclosures THIS company leads with
(a "key metrics" table, a figure management repeats, a unit-economics number). Emit each
in the **same shape as a catalog metric**, so a kept candidate can be added directly:
```
{
  "key": "paid_net_adds",                 // suggested stable snake_case id
  "label": "Paid Net Additions",          // display name
  "aliases": ["paid net adds", "net subscriber additions"],
  "unit": "M",                            // % | $ | $M | $B | M | k | units | x
  "is_pp": false,                         // true ONLY for % LEVELS (margins, rates, retention)
  "higher_is_better": true,               // false for cost / churn / loss / discount-type metrics
  "extraction_hint": "Net new paid subscribers added in the quarter.",
  "section": "kpi",
  "source": "release, p.1",
  "quote": "We added 5.1 million paid net additions in the quarter",
  "rationale": "Core subscriber-growth KPI the company leads with; not in the catalog."
}
```
Rules for candidates:
- MUST be a recurring, quantifiable metric an analyst would compare next quarter — NOT a
  one-off event. A new hire, a lawsuit, a buyback authorization, an acquisition are
  `notable` items the extractor handles, **not** candidates.
- MUST carry a verbatim `quote` proving the company discloses it. No quote → drop it.
- Do NOT propose anything already in the standing set above, nor a generic headline
  metric (`revenue`, `revenue_growth`, `gross_margin`, `op_margin`, `eps`, `fcf`), nor a
  plain segment-revenue line — those are all extracted automatically.
- Suggest `unit` / `is_pp` / `higher_is_better` conservatively, following the conventions
  in the comments above. If you are unsure of direction, default `higher_is_better: true`
  and say so in `rationale`. `section` is informational; additions resolve to `kpi`.
- Cap at the **~8 highest-signal** candidates. This is a shortlist for the analyst to
  approve, not an exhaustive scrape — quality over quantity.

## Output

Write a single JSON file (no prose, no markdown fences) with this shape:
```json
{
  "company": "{{COMPANY}}", "ticker": "{{TICKER}}", "period": "{{PERIOD}}",
  "disclosed": [ ... ],
  "candidates": [ ... ]
}
```

Then return a 2-3 sentence summary: how many standing metrics are disclosed vs missing
(name the missing ones), and the top company-specific candidates you surfaced.

### Common mistakes to avoid
- ✗ Extracting values or computing beat/miss — that is the next step. Discovery NAMES
  metrics; it does not score them.
- ✗ Proposing a candidate that is already a standing metric, a headline metric, or a
  plain segment-revenue line.
- ✗ A `disclosed` entry or a candidate with no verbatim `quote`, or a paraphrased quote.
- ✗ Proposing one-off narrative facts as metrics (those are `notable`, not KPIs).
- ✗ Marking a metric disclosed because the analyst tracks it — list it only if THIS
  print actually shows it.
