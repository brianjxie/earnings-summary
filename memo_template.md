<!--
  Standard memo skeleton for the earnings-summary skill. The assembling agent
  fills every {{PLACEHOLDER}}, pastes the script-rendered scorecard tables
  verbatim (never re-typing numbers), and writes the narrative around them.

  Sections 1-7 are ALWAYS present. Section 8 (custom KPIs) is always present but
  its rows come from the analyst's profile. Delete a section's body only if the
  data genuinely doesn't exist — and say so explicitly ("Not disclosed").

  Verdicts (BEAT / MISS / IN-LINE) and all deltas come from compute_beat_miss.py.
  Do not compute or restate numbers by hand.
-->

# {{COMPANY}} ({{TICKER}}) — {{PERIOD}} Earnings Summary

*Reported {{REPORT_DATE}} · Prepared by {{ANALYST}} · Sources: {{RELEASE_SOURCE}} · {{TRANSCRIPT_SOURCE}}*
<!-- RELEASE_SOURCE: markdown link to the EDGAR/BamSEC filing (or the accession #).
     TRANSCRIPT_SOURCE: the transcript PDF filename, or "transcript not provided". -->

> **Bottom line:** {{ONE_LINE_HEADLINE}}
> *(from scorecard: {{HEADLINE_FROM_SCRIPT}})*

## 1. TL;DR
<!-- 3-5 bullets: the beat/miss read, the guidance action, and the 1-2 things
     that actually move the thesis. Lead with what's decision-relevant. -->
- {{TLDR_BULLET_1}}
- {{TLDR_BULLET_2}}
- {{TLDR_BULLET_3}}

## 2. Scorecard — Actual vs My Model vs Street
<!-- Paste tables_md.headline verbatim from the compute script. -->
{{SCORECARD_HEADLINE_TABLE}}

<!-- One or two sentences interpreting the headline read: quality of the beat
     (driver vs one-time), mix, and whether the print supports or pressures the thesis. -->
{{SCORECARD_READ}}

## 3. Financial Summary
<!-- Revenue + segment detail, margins, EPS bridge, cash flow, balance-sheet
     notes. Paste tables_md.segment if segments were extracted. YoY/QoQ already
     computed in the tables — interpret, don't restate. -->
{{SEGMENT_TABLE}}

- **Revenue:** {{REVENUE_NOTE}}
- **Margins:** {{MARGIN_NOTE}}
- **EPS / below the line:** {{EPS_NOTE}}
- **Cash flow & balance sheet:** {{CASH_NOTE}}

## 4. Guidance Changes
<!-- Table of each guided metric: prior vs new vs Street, with the action. -->
| Metric | Prior Guide | New Guide | Street | Action |
|---|---|---|---|---|
| {{GUIDE_ROW}} |

**Read:** {{GUIDANCE_NARRATIVE}}

## 5. Key KPIs ({{ANALYST}}'s tracked fields)
<!-- Paste tables_md.kpi verbatim. These are the analyst's custom fields from
     their profile; beat/miss columns populate only where an estimate/consensus
     was supplied. -->
{{KPI_TABLE}}

{{KPI_READ}}

## 6. Management Commentary & Call Highlights
<!-- Release-only run (no transcript): replace this section body with
     "_Transcript not provided — call commentary omitted._" -->
**Prepared remarks**
<!-- 4-6 themes, each with a verbatim quote attributed to the speaker. -->
- **{{REMARK_THEME}}** — {{REMARK_POINT}} *"{{REMARK_QUOTE}}"* — {{SPEAKER}}

**Q&A**
<!-- 4-6 exchanges; prioritize guidance color, demand, margins, capital
     allocation, and any management pushback/evasion. -->
- **{{QA_TOPIC}}** ({{QA_ASKED_BY}}): {{QA_EXCHANGE}} *"{{QA_QUOTE}}"*

## 7. Watch Items & Thesis Impact
<!-- The analyst-facing "so what". Open questions the print didn't answer,
     what to verify in the 10-Q, and net read on the thesis (incrementally
     positive / neutral / negative and why). Keep it honest and short. -->
- {{WATCH_ITEM}}
- **Thesis impact:** {{THESIS_IMPACT}}

<!-- Notable items (one-time/buyback/mgmt change/M&A), if any: -->
{{NOTABLE_ITEMS}}

---
*Beat/miss bands: ±{{BAND_PCT}}% (revenue/$ metrics), ±${{BAND_EPS}} (EPS), ±{{BAND_PP}}pp (rates). Verdicts measured vs {{BENCHMARK_CONVENTION}}.*
