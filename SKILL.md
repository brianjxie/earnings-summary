---
name: earnings-summary
description: Produce a buy-side earnings summary memo for one company's quarterly print. Per-analyst profiles persist each analyst's custom KPIs and model estimates; the standard sections (financial summary, beat/miss scorecard, guidance changes, call highlights) are always produced. Locates the earnings press release (8-K / Exhibit 99.1) on EDGAR from a ticker, company name, or BamSEC/EDGAR link, reads the call transcript from a PDF (paste fallback), runs deterministic beat/miss vs the analyst's model AND pasted consensus, and writes a markdown memo. Use when an analyst wants a structured summary of an earnings release.
---

# earnings-summary

Generate a markdown earnings memo for ONE company's quarterly results, tailored
to a named analyst. The skill is **profile-driven**: each analyst has a saved
profile of custom KPIs + per-ticker model estimates, but the standard memo
sections (scorecard, financial summary, guidance changes, call highlights) are
hard-wired and always produced.

The deliverable is a markdown memo, optionally rendered to a styled PDF.
Beat/miss is measured against **two**
benchmarks — the analyst's own model and pasted Street consensus — and all the
arithmetic is done in Python, never by the model.

## Skill files

- `profiles/<analyst-slug>.yaml` — per-analyst profile: a thin OVERLAY over the
  catalog (`extends`/`pick`/`add`/`override`) + per-ticker model estimates,
  output dir, threshold preferences. Auto-loaded if present.
- `profiles/_example.yaml` — annotated profile schema; copy to create a new one.
- `kpi_catalog.yaml` — the cross-sector KPI scaffold: sector-grouped metrics
  (each with key / aliases / unit / direction / extraction_hint) + per-sector
  `themes`, plus the always-pulled `standard_headline` set. Profiles REFERENCE it
  by sector + key (they don't copy definitions).
- `scripts/resolve_kpis.py` — resolve a profile against the catalog into the flat
  KPI list + sector themes + ready-to-paste prompt blocks (`custom_kpis_block` /
  `themes_block`); back-compat for legacy inline-`kpis` profiles.
- `scripts/validate_catalog.py` — structural + shared-key consistency checks on
  the catalog; run after editing it.
- `extraction_prompt.md` — prompt template for the extraction agent.
- `discovery_prompt.md` — prompt template for the pre-extraction discovery agent
  (Step 5.5): flags which standing metrics this print discloses and surfaces
  company-specific KPIs not in the catalog (each verbatim-quoted) for the analyst to
  confirm. Proposes only — never auto-adds.
- `guidance_extract_prompt.md` — prompt for the per-document guidance-only pass (Step 6,
  prior releases): emits canonical `guide_key` + `status` + signed `value` + quote so
  `reconcile_guidance.py` can stitch guidance across quarters.
- `memo_template.md` — the fixed memo skeleton (standard sections).
- `scripts/find_edgar_release.py` — locate the earnings 8-K (Item 2.02) /
  Exhibit 99.1 on EDGAR from a ticker or company name (stdlib only; sets the
  SEC-required User-Agent so name lookup doesn't 403). `--resolve-candidates N`
  also resolves Ex-99.1 URLs for the last N quarters (prior-release lineage, Step 5).
- `scripts/fetch_url.py` — download a URL to text with the SEC fair-access
  User-Agent (WebFetch is **403'd by sec.gov**). Use for EDGAR/SEC links;
  WebFetch for everything else.
- `scripts/extract_pdf_text.py` — PDF → page-tagged text (transcript, or a
  release supplied as PDF). Reuses `lib/pdf_lib.py`.
- `scripts/compute_beat_miss.py` — deterministic beat/miss + delta math; renders
  the markdown scorecard tables. Stdlib + optional pyyaml.
- `scripts/reconcile_guidance.py` — deterministic multi-document guidance lineage
  (Step 7.5): resolves prior-guide + set-as-of provenance across releases, carrying
  forward "reaffirmed"; renders the §4 table. Stdlib only.
- `scripts/render_pdf.py` — render the finished memo .md to a styled, color-coded
  PDF (reportlab; pure-Python, no system libraries). Optional output.
- `requirements.txt` — `pyyaml`, `pdfplumber`, `pypdfium2`, `reportlab`.

Bundled PDF primitive:
- `lib/pdf_lib.py` — PDF text extraction + PNG rendering (for the transcript
  PDF and any release supplied as PDF).

Inputs are polymorphic and auto-detected per source (Step 5): the release is a
link / EDGAR lookup / PDF / paste; the transcript is a PDF / paste / best-effort
URL. Nothing here bypasses paywalls — gated sources fall back to paste.

## Runbook

### Step 1 — Dependency check

```
python -c "import yaml, pdfplumber, pypdfium2; print('ok')"
```
If missing: `pip install -r .claude/skills/earnings-summary/requirements.txt`
(`compute_beat_miss.py` runs without pyyaml; `find_edgar_release.py` is stdlib
only. pdfplumber/pypdfium2 are needed only when a source is a PDF.)

### Step 2 — Intake

One consolidated `AskUserQuestion` round:

1. **Analyst name** (selects/creates the profile).
2. **Company + ticker** (e.g. "Salesforce / CRM").
3. **Fiscal period** exactly as it should read (e.g. "FY26 Q1"). If known, the
   **report date** too — it disambiguates the EDGAR filing.
4. **Release source** — any of: a BamSEC/EDGAR link; just the company/ticker
   (the skill locates the 8-K / Ex-99.1 on EDGAR); a PDF path; or pasted text.
5. **Transcript** — a PDF path (default), pasted text, or "none" for a
   release-only memo. Scope is the full call incl. Q&A.

Echo the parsed inputs back before continuing.

### Step 3 — Analyst profile (metric selection)

The profile is a thin **overlay** over `kpi_catalog.yaml`: it names the sector(s)
the analyst covers and (optionally) narrows/extends the metric set. It does NOT
copy metric definitions — those live in the catalog and are pulled in by the
resolver, so catalog improvements (aliases, hints) flow through automatically.

1. **Slugify** the analyst name (lowercase, kebab-case) and check for
   `.claude/skills/earnings-summary/profiles/<slug>.yaml`.
   - **If present:** resolve it (sub-step 3) and show the analyst the resolved
     KPI list + their sector(s) + output dir + thresholds. Ask:
     `use as-is` / `edit` / `replace`.
   - **If absent:** build an overlay via `AskUserQuestion`:
     a. Which **sector(s)** from `kpi_catalog.yaml` the company belongs to (one or
        more — a company can span sectors, e.g. a fintech lender →
        `[payments_fintech, banks]`) → `extends`.
     b. Show that sector's metrics as a **checklist** (default = all selected) →
        `pick` (omit `pick` to keep the whole sector set). This is the standing
        menu the analyst chooses from.
     c. Offer to **add** any metric not in the catalog (→ `add`: capture key,
        label, aliases, unit, `is_pp`, `higher_is_better`, extraction hint) and to
        **relabel** an inherited metric (→ `override`).
2. **Save** the overlay to `profiles/<slug>.yaml` (schema = `_example.yaml`).
   Tell the analyst it's reused on future runs and editable.
3. **Resolve** the profile to preview its final KPI list:
   ```
   python .claude/skills/earnings-summary/scripts/resolve_kpis.py \
     --profile ".claude/skills/earnings-summary/profiles/<slug>.yaml"
   ```
   Parse stdout JSON: show the analyst `kpis` (the resolved metric list) and
   `themes` (the sector themes that will steer call highlights). **Surface any
   `warnings`** (unknown sector, `pick` typo, `override` miss) before continuing.
   Step 6 re-runs this into the run dir to build the extraction prompt.

The standard headline set (`kpi_catalog.yaml: standard_headline`) is ALWAYS
pulled regardless of the profile — don't ask about those; the resolver drops any
overlay metric that collides with a headline key so a row never duplicates.

### Step 4 — Estimates + consensus

Beat/miss uses two benchmarks; gather both.

1. **My model estimates:** look in `profile.estimates[<ticker>][<period>]`. If
   present, use them and echo them back for confirmation. If absent, ask the
   analyst to paste their estimates for the headline metrics + any benchmarked
   KPIs (revenue $M, EPS $, margins %, plus their KPIs). Offer to **save** the
   pasted estimates into the profile under `estimates[<ticker>][<period>]` so
   next quarter they're remembered.
2. **Consensus:** ask the analyst to paste Street consensus for the same
   metrics (Visible Alpha / Bloomberg / FactSet). Consensus is per-quarter and
   not persisted. If they have none, proceed — beat/miss will show vs-model only
   and YoY.

Keep estimate/consensus keys aligned with metric `key`s (`revenue`, `eps`,
`op_margin`, ...) and custom KPI labels, so they merge cleanly in Step 7.

### Step 5 — Acquire sources

Create the run dir: `<memo_dir>/.cache/<TICKER>_<PERIOD_SLUG>/`
(`memo_dir` from the profile; default `./earnings-memos/`; expand `~`).
`PERIOD_SLUG` = period with spaces removed (e.g. `FY26Q1`).

**Release** — detect the input type and route:

- **Company / ticker only** → locate it on EDGAR:
  ```
  python .claude/skills/earnings-summary/scripts/find_edgar_release.py \
    --ticker <TICKER>  [--date <YYYY-MM-DD report date>]
  ```
  (use `--company "<name>"` if no ticker). If the output is `ambiguous`, show the
  candidates and ask which company. Otherwise **echo `selected`** (company, form,
  items `2.02`, `filing_date`, `accession`) and **confirm with the analyst before
  parsing** — this prevents summarizing the wrong quarter. On confirm, fetch
  `selected.ex99_1_url` with **`fetch_url.py`** (NOT WebFetch — sec.gov 403s it):
  `python scripts/fetch_url.py "<ex99_1_url>" --out "<run_dir>/raw_release.txt"`.
  If the lookup errors (EDGAR throttling), ask for a BamSEC/EDGAR link instead.
- **BamSEC / EDGAR / IR link** → if it's a `sec.gov` URL use `fetch_url.py`
  (WebFetch 403s on SEC); otherwise `WebFetch` it → `raw_release.txt`. If a
  BamSEC link is gated, reconstruct the EDGAR doc URL from the accession
  (BamSEC shows it) and fetch that with `fetch_url.py`.
- **PDF path** → `extract_pdf_text.py "<pdf>" --out "<run_dir>/raw_release.txt"`.
- **Pasted text** → write it to `raw_release.txt`.

**Transcript** — usually a PDF:

- **PDF path** (default) →
  `extract_pdf_text.py "<pdf>" --out "<run_dir>/raw_transcript.txt"`.
  Note any `image_only_pages` it reports (rare for transcripts).
- **Pasted text** → write to `raw_transcript.txt`.
- **Free URL** → `WebFetch` best-effort; if thin/garbled, ask the analyst to paste.
- **None** → mark the run **release-only**; §6 of the memo states "transcript not
  provided" and Q&A is skipped.

**Prior releases (optional — for guidance lineage):** to populate the §4 "Prior Guide"
column when this print says guidance is "unchanged" / "lowered" without restating the old
number, acquire one or more PRIOR quarterly releases. Two ways, combinable:
- **Analyst-supplied** — paths/links to prior 8-K Ex-99.1s, each tagged with its quarter.
- **Auto-fetch (EDGAR)** — `find_edgar_release.py --ticker <T> --resolve-candidates <N>`
  returns the last N earnings 8-Ks each with an `ex99_1_url`; fetch each with `fetch_url.py`
  → `raw_release_<PERIOD>.txt`.

Tag each with `period` + `filing_date`. Start with ~4 quarters; if Step 7.5 flags a guide
whose origin predates the window (`needs_more_history`), fetch older quarters and re-run.
Note that the *immediately* prior filing may be a non-earnings 8-K (Item 2.02 with no
guidance) — the reconciler skips docs that don't address a guide, so it walks back to where
the number was actually set. Skip this entirely for a single-release run.

Never proceed on an empty source. Report:
`Release: <source> (N words); transcript: <source> (M words/pages).`

### Step 5.5 — Release discovery (what does THIS print disclose?)

A quick discovery pass over the acquired release + transcript, BEFORE extraction, so
the analyst confirms the metric plan against what this specific print actually
contains. It does two things — flags which standing metrics are disclosed (and which
are missing this quarter), and surfaces company-specific KPIs the catalog lacks, each
with a verbatim quote. **It proposes; it never auto-adds.**

1. **Resolve** the profile (if not already done this run) to get the standing custom-KPI
   block + themes:
   ```
   python .claude/skills/earnings-summary/scripts/resolve_kpis.py \
     --profile ".claude/skills/earnings-summary/profiles/<slug>.yaml" \
     --out "<run_dir>/resolved_kpis.json"
   ```
2. **Render** `discovery_prompt.md`, substituting `{{COMPANY}}` / `{{TICKER}}` /
   `{{PERIOD}}` / `{{SYNONYMS}}` from intake; `{{STANDING_KPIS}}` = the resolver's
   `custom_kpis_block`; `{{THEMES}}` = its `themes_block`; `{{DOCUMENTS}}` = the same
   `=== RELEASE ===` / `=== TRANSCRIPT ===` bundle Step 6 builds (release-only run →
   release alone). Spawn ONE discovery agent; it writes `<run_dir>/discovery.json`
   (`{disclosed[], candidates[]}`) and returns a short summary.
3. **Derive the gaps deterministically** — do NOT ask the agent for them: `not_disclosed`
   = every standing key (the 6 headline keys + the resolved custom-KPI keys) that is NOT
   present in `discovery.disclosed`. Computing absence (rather than letting the model
   assert it) keeps non-disclosure honest.
4. **Surface to the analyst (staged review):**
   - **Disclosed this quarter** (with the quote) vs **NOT disclosed** (flagged — these
     are recorded absent in the memo, never filled).
   - **Company-specific candidates**, each with label, suggested unit/direction, the
     verbatim quote, and the one-line rationale.
   Ask which candidates to KEEP, and for each kept one, the destination:
   `this run only` / `save to my profile (add:)` / `promote into the catalog`.
5. **Apply the decision (only after approval):**
   - **This run only** → write the kept candidate defs (the `candidates[]` subset — they
     are already in `add:` shape) to `<run_dir>/discovery_kept.json`. Step 6 resolves
     with `--add-from "<run_dir>/discovery_kept.json"`, so they join `{{CUSTOM_KPIS}}`
     for this run without touching the profile.
   - **Save to my profile** → append the kept defs to the profile's `add:` list (schema
     = `_example.yaml`), then re-resolve. Remembered next quarter.
   - **Promote into the catalog** → add the def under the relevant sector in
     `kpi_catalog.yaml`, **re-run `validate_catalog.py`** (must stay `errors: []`), then
     make sure the profile `extends` / `pick`s it. Shared across analysts.
   Nothing persists without the analyst's OK; non-disclosed standing metrics stay absent,
   never invented.

The confirmed set (standing ⊕ kept candidates) is the plan Step 6 extracts.

### Step 6 — Extract

First resolve the profile into the run dir (now that it exists). If Step 5.5 kept any
discovery KPIs **for this run only**, fold them in with `--add-from` (omit it otherwise —
KPIs saved to the profile or promoted to the catalog are already picked up by
re-resolving the profile):
```
python .claude/skills/earnings-summary/scripts/resolve_kpis.py \
  --profile ".claude/skills/earnings-summary/profiles/<slug>.yaml" \
  [--add-from "<run_dir>/discovery_kept.json"] \
  --out "<run_dir>/resolved_kpis.json"
```

Render `extraction_prompt.md`, substituting:
- `{{COMPANY}}`, `{{TICKER}}`, `{{PERIOD}}`, `{{SYNONYMS}}` — from intake.
- `{{CUSTOM_KPIS}}` — the resolver's `custom_kpis_block`, pasted verbatim (it
  already lists each metric's key / unit / aliases / hint / direction).
- `{{THEMES}}` — the resolver's `themes_block`.
- `{{DOCUMENTS}}` — the two raw text files, each clearly delimited with a
  `=== RELEASE ===` / `=== TRANSCRIPT ===` header.

Spawn one extraction agent. It writes `extraction.json` to the run dir and
returns a one-paragraph coverage summary. If JSON parsing fails, retry once with
a stricter "JSON only, no prose" instruction.

Relay the coverage summary, especially **which custom KPIs were not disclosed**.

**Prior-doc guidance passes (only if prior releases were acquired in Step 5):** for EACH
prior release, render `guidance_extract_prompt.md` (substituting `{{COMPANY}}` /
`{{TICKER}}` / `{{SYNONYMS}}`, `{{DOC_PERIOD}}` = that release's quarter, `{{DOCUMENT}}` =
its raw text) and spawn a guidance-only agent → `guidance_<PERIOD>.json`. The current
print's guidance is already in `extraction.json.guidance` (same canonical record shape:
`guide_key` / `status` / `value` / `quote`). These feed the Step 7.5 reconciler.

### Step 7 — Compute beat/miss

1. **Merge** estimates + consensus into the extracted `metrics[]`: for each
   metric, set `my_est` and `consensus` from Step 4 by matching `key` (headline)
   or `label` (KPIs). Carry over each metric's `is_eps` / `is_pp` /
   `higher_is_better`. Write the merged list to `scorecard_input.json` with the
   top-level `inline_band_pct` / `eps_inline_band_abs` / `pp_inline_band` (from
   the profile, or defaults below).
2. Run:
   ```
   python .claude/skills/earnings-summary/scripts/compute_beat_miss.py \
     --in  "<run_dir>/scorecard_input.json" \
     --out "<run_dir>/scorecard.json" \
     --profile ".claude/skills/earnings-summary/profiles/<slug>.yaml"
   ```
3. Parse stdout JSON for `headline`, `counts`, `sections`. The full result
   (`scorecard.json`) carries `tables_md` (per-section markdown tables) and the
   enriched per-metric verdicts.

### Step 7.5 — Reconcile guidance across documents (if priors were acquired)

Stitch the per-document guidance into a lineage so "Prior Guide" reflects where each guide
was last *set*, not just the immediately prior quarter.

1. Assemble `<run_dir>/guidance_docs.json` (current doc first):
   ```json
   {"ticker": "<T>", "current_period": "<PERIOD>",
    "docs": [ {"period": "<PERIOD>", "filing_date": "<YYYY-MM-DD>",
               "guidance": <extraction.json.guidance>},
              {"period": "<prior>", "filing_date": "...",
               "guidance": <guidance_<prior>.json.guidance>}, ... ]}
   ```
2. Run:
   ```
   python .claude/skills/earnings-summary/scripts/reconcile_guidance.py \
     --in "<run_dir>/guidance_docs.json" --out "<run_dir>/reconciled_guidance.json"
   ```
3. Per `guide_key` it resolves: the effective current guide (carrying forward `reaffirmed`),
   `set_as_of` / reaffirmed-through, the **prior distinct value + `prior_as_of`**, the
   `action` (declared status, cross-checked vs range midpoints), and `origin_in_window`. It
   renders `table_md` (Prior Guide · Current · Action · Provenance) and lists any guide whose
   origin predates the window in `needs_more_history` — fetch older quarters and re-run if
   the analyst needs those. Every resolved figure keeps the quote + the period that stated it.

Single-release run: skip this step; §4 uses `extraction.json.guidance` directly and notes
prior guide is unavailable.

### Step 8 — Assemble the memo

Fill `memo_template.md`:
- Paste `tables_md.headline` into §2, `tables_md.segment` into §3,
  `tables_md.kpi` into §5 — **verbatim**. Never re-type numbers; the script's
  tables are the source of truth for every figure and verdict.
- Use `scorecard.json.headline` for the bottom-line one-liner.
- §4 guidance: if Step 7.5 ran, paste `reconciled_guidance.json.table_md` (Prior Guide ·
  Current · Action · Provenance) **verbatim** and surface any `needs_more_history` flag;
  otherwise (single release) build the table from `extraction.json.guidance` with Prior
  Guide marked "unavailable — no prior docs". Either way, the narrative comes from
  `guidance_narrative`.
- Write §1 TL;DR, §3 prose notes, §6 highlights (from `call_highlights`, quotes
  verbatim), and §7 watch items / thesis impact.
- Honor the profile's `tone` (concise vs detailed).

Write the memo to `<memo_dir>/<TICKER>_<PERIOD_SLUG>_earnings.md`.

### Step 8.5 — Render PDF (if requested)

If `profile.output.format` is `pdf` or `both` (default `both` when reportlab is
installed):
```
python .claude/skills/earnings-summary/scripts/render_pdf.py \
  "<memo_dir>/<TICKER>_<PERIOD_SLUG>_earnings.md"
```
Writes `<...>_earnings.pdf` next to the .md, color-coding BEAT/MISS verdicts and
RAISE/CUT/MAINTAIN guidance actions. If reportlab isn't installed, skip with a
note (the .md still ships). For magazine-grade output, the analyst can instead
run `npx md-to-pdf` (headless Chrome) on the .md.

### Step 9 — Summary

Report, in order:
1. `Memo: <path>` (the .md, clickable) and `PDF: <path>` if rendered.
2. **Headline read** (`scorecard.json.headline`) + counts (beat/miss/in-line).
3. **Guidance action** (raise/cut/maintain/initiate) with the one-line driver.
4. **Custom KPIs not disclosed** (from the extraction coverage summary).
5. **Benchmark coverage:** which metrics had model-only vs both benchmarks.
6. `Profile saved: <path>` — note custom KPIs (and any saved estimates) persist.
7. `Cache: <run_dir>` — raw text + extraction + scorecard preserved; delete to
   force a clean re-run.

## Defaults

- **Inline bands:** ±2.0% (revenue / dollar metrics), ±2 cents (EPS), ±0.5pp
  (rate / margin metrics). Overridable in `profile.preferences`.
- **Headline verdict benchmark:** consensus when present, else the model. (The
  table always shows both deltas; the single "Read" column picks one.)
- **EPS basis:** whatever the company headlines and consensus is set on
  (usually non-GAAP) — stated in the metric label.
- **`is_pp` metrics:** any `%`-unit level (margins, retention, growth rates) is
  read in points, not percent.
- **Missing consensus:** memo proceeds with model-only beat/miss + YoY; note it.
- **Memo dir:** `profile.output.memo_dir`, default `./earnings-memos/`.
- **EDGAR User-Agent:** `find_edgar_release.py` declares a contact UA (SEC fair
  access). Override with `--ua "Name email"` if needed.
- **Transcript:** supplied as a PDF (or pasted); not auto-fetched from a URL
  unless you pass one explicitly.
- **Output format:** `profile.output.format` ∈ `markdown` | `pdf` | `both`
  (default `both`). PDF needs `reportlab`; falls back to markdown-only if absent.

## Standard sections (always produced)

1. Header + bottom-line one-liner
2. TL;DR
3. Scorecard (Actual vs My Model vs Street, with BEAT/MISS/IN-LINE)
4. Financial summary (revenue/segments, margins, EPS, cash flow)
5. Guidance changes (prior vs new vs Street, with action)
6. Key KPIs (analyst's custom fields)
7. Management commentary & call highlights (prepared remarks + Q&A)
8. Watch items & thesis impact

## Why this design

- **Profiles, not one-off questions:** an analyst's KPIs and model estimates are
  stable quarter to quarter. Persisting them mirrors the saved-template pattern
  used elsewhere in the suite and removes repeated setup.
- **Deterministic math:** beat/miss and deltas are computed in Python so the
  memo never depends on the model's arithmetic — the same rationale behind the
  deterministic validation gates used elsewhere in the suite.
- **Dual benchmark:** buy-side cares about "vs my number" and "vs the Street."
  Both columns are always shown; the headline read uses the configured one.
- **Verbatim quotes + sourcing:** every metric carries a `source` and every
  call highlight a verbatim quote, so the analyst can spot-check fast.
- **Discovery proposes, the analyst disposes:** Step 5.5 reads the actual print to flag
  what's disclosed and to surface company-specific KPIs the catalog misses, but the
  analyst confirms before anything is tracked or persisted — the same
  propose→approve→write discipline as the rest of the suite. A non-disclosed metric is
  recorded absent, never fabricated; kept KPIs can teach the profile or the catalog.

## Known limitations

- **Release lookup:** `find_edgar_release.py` reads EDGAR's submissions API;
  fiscal-period → filing-date mapping isn't automatic, so pass `--date` (the
  report date) to disambiguate, or confirm from the candidate list. EDGAR may
  throttle automated lookups — fall back to a pasted BamSEC/EDGAR link.
- **Fetch reliability:** IR pages and transcript hosts (Motley Fool, Seeking
  Alpha) are often JS-heavy or paywalled. The skill falls back to pasted text /
  PDF; it does not bypass paywalls.
- **Consensus is manual:** there is no licensed consensus feed. Beat/miss vs
  Street is only as good as the pasted numbers (and their period/basis must
  match the actuals).
- **Guidance lineage needs the prior releases:** §4 "Prior Guide" is reconciled across the
  documents you supply/fetch (Steps 5 + 7.5), so it's only as deep as that window — if a
  live guide was set before the oldest release provided, `reconcile_guidance.py` flags it
  (`needs_more_history`) rather than guessing; add older quarters. Cross-quarter matching
  relies on a stable `guide_key`, so a relabeled/re-based metric can break a chain (the flag
  surfaces it).
- **No charts/figures from the release** are parsed — text and tables only.
- **One company per run.** Multi-company roll-ups are out of scope.
- **No 10-Q/10-K yet:** scope is the press release + call; balance-sheet /
  footnote detail beyond the release isn't ingested. (Planned add-on.)
- **Estimate/actual basis mismatches** (GAAP vs non-GAAP, reported vs organic)
  are the analyst's responsibility to align when pasting — the skill compares
  whatever shares a metric `key`.
- **Discovery is a second model pass:** Step 5.5 reads the documents before extraction
  to shape the plan, so a full run makes two passes over the text. It's deliberately
  lightweight (it names metrics, never extracts values); skip it for a pure
  catalog-driven run when the print's disclosures are already known.
- **Profiles and the `.cache/` run dirs are per-machine state.** If you don't
  want them committed, add them to `.gitignore` (the example profile is safe to
  commit as schema documentation).
