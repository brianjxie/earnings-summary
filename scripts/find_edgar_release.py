#!/usr/bin/env python3
"""Locate a company's earnings press release (8-K, Item 2.02 / Exhibit 99.1) on
SEC EDGAR from a ticker OR a company name.

Why a script (not live WebFetch): SEC's fair-access policy requires a declared
User-Agent on its JSON endpoints (data.sec.gov), and generic fetchers get 403'd
without one. urllib lets us set the header explicitly, so name->filing resolution
is reliable. The chosen Exhibit 99.1 lives under www.sec.gov/Archives/... which
WebFetch handles fine — so the runbook calls THIS to find the URL, then fetches
the document with WebFetch.

Resolution:
  1. ticker/name -> CIK via www.sec.gov/files/company_tickers.json
  2. recent filings via data.sec.gov/submissions/CIK##########.json
  3. keep 8-K filings whose `items` include 2.02 (Results of Operations)
  4. pick the one matching --date (closest) else the most recent
  5. in that filing's folder, find the EX-99.1 doc (EDGAR type, then filename
     heuristic, then fall back to the filing's primary document)

Output (stdout JSON): selected filing + an ex99_1_url to fetch, plus up to 8
candidates so the runbook can confirm before parsing. Ambiguous company names
return {"ambiguous":[...]} (exit 0). Network/HTTP errors -> stderr JSON, exit 1.

Usage:
  python find_edgar_release.py --ticker CRM
  python find_edgar_release.py --company "Salesforce" --date 2026-05-28
  python find_edgar_release.py --company "Acme" --ua "Your Name you@example.com"
"""
import argparse
import gzip
import json
import re
import sys
import urllib.error
import urllib.request

DEFAULT_UA = "financeAI earnings-summary (brianxie45@gmail.com)"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FOLDER_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"
# Match common EX-99.1 filenames: ex991, ex99-1, ex99_1, exh_991, exhibit991, a
# company-prefixed nclhex991, etc. Allows a short alpha run (e.g. "exh") and an
# optional separator between the ex-prefix and "99" — the older `ex.?` form missed
# two-char gaps like the "h_" in "exh_991.htm".
EX991_NAME_RE = re.compile(r"(?:exhibit|exh|ex)[a-z]{0,4}[._-]?99[._-]?1", re.I)


def http_get(url, ua):
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json, text/html, */*",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        if resp.info().get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def fail(msg):
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(1)


def resolve_cik(args, ua):
    """Return (cik:int, title:str, ticker:str) or print ambiguous + exit."""
    try:
        data = json.loads(http_get(TICKERS_URL, ua))
    except urllib.error.HTTPError as e:
        fail(f"EDGAR ticker map HTTP {e.code} — supply an EDGAR/BamSEC link instead.")
    except Exception as e:
        fail(f"could not fetch EDGAR ticker map ({e}) — supply an EDGAR/BamSEC link instead.")

    rows = list(data.values())
    if args.ticker:
        t = args.ticker.strip().upper()
        hit = next((r for r in rows if r.get("ticker", "").upper() == t), None)
        if not hit:
            fail(f"ticker {t} not found in EDGAR ticker map.")
        return int(hit["cik_str"]), hit.get("title", ""), hit.get("ticker", "")

    name = args.company.strip().lower()
    exact = [r for r in rows if r.get("title", "").lower() == name]
    contains = [r for r in rows if name in r.get("title", "").lower()]
    matches = exact or contains
    if not matches:
        fail(f"no EDGAR company matched '{args.company}'. Try a ticker or an EDGAR link.")
    if len(matches) > 1 and not exact:
        print(json.dumps({"ambiguous": [
            {"title": r.get("title"), "cik": int(r["cik_str"]), "ticker": r.get("ticker")}
            for r in matches[:12]
        ]}, indent=2))
        sys.exit(0)
    r = matches[0]
    return int(r["cik_str"]), r.get("title", ""), r.get("ticker", "")


def find_earnings_8ks(cik, ua):
    """Return recent 8-K filings whose items include 2.02, newest first."""
    try:
        sub = json.loads(http_get(SUBMISSIONS_URL.format(cik=cik), ua))
    except urllib.error.HTTPError as e:
        fail(f"EDGAR submissions HTTP {e.code} for CIK {cik} — supply an EDGAR/BamSEC link.")
    except Exception as e:
        fail(f"could not fetch EDGAR submissions ({e}) — supply an EDGAR/BamSEC link.")

    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    out = []
    for i, form in enumerate(forms):
        if form != "8-K":
            continue
        items = recent.get("items", [""] * len(forms))[i] or ""
        if "2.02" not in items:
            continue
        out.append({
            "filing_date": recent.get("filingDate", [])[i],
            "accession": recent.get("accessionNumber", [])[i],
            "items": items,
            "primary_doc": recent.get("primaryDocument", [])[i],
        })
    return out


def pick(filings, target_date):
    if not filings:
        return None
    if target_date:
        return min(filings, key=lambda f: abs(_days(f["filing_date"]) - _days(target_date)))
    return filings[0]  # submissions.recent is newest-first


def _days(d):
    y, m, dd = (int(x) for x in d.split("-"))
    return y * 372 + m * 31 + dd  # monotonic ordinal; exact spacing not needed


def find_ex991(cik, accession, ua, primary_doc):
    """Locate the EX-99.1 doc URL within a filing folder."""
    acc_nodash = accession.replace("-", "")
    folder = FOLDER_URL.format(cik=cik, acc_nodash=acc_nodash)
    try:
        idx = json.loads(http_get(folder + "index.json", ua))
        items = idx.get("directory", {}).get("item", [])
    except Exception:
        items = []

    # 1) EDGAR type label == EX-99.1
    for it in items:
        if str(it.get("type", "")).upper().replace(" ", "") in ("EX-99.1", "EX-99.01"):
            return folder + it["name"], folder, "type-match"
    # 2) filename heuristic
    docs = [it["name"] for it in items if str(it.get("name", "")).lower().endswith((".htm", ".html", ".txt"))]
    for n in docs:
        if EX991_NAME_RE.search(n):
            return folder + n, folder, "filename-heuristic"
    # 3) fall back to the filing's primary document
    if primary_doc:
        return folder + primary_doc, folder, "primary-doc-fallback"
    return None, folder, "not-found"


def main():
    ap = argparse.ArgumentParser(description="Find an earnings 8-K/EX-99.1 on EDGAR.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ticker")
    g.add_argument("--company")
    ap.add_argument("--date", help="YYYY-MM-DD hint to disambiguate the quarter")
    ap.add_argument("--resolve-candidates", type=int, default=0, dest="resolve_candidates",
                    help="also resolve the Ex-99.1 URL for the top N candidates (for "
                         "multi-quarter guidance lineage); 0 = selected filing only")
    ap.add_argument("--ua", default=DEFAULT_UA, help="User-Agent contact for SEC fair-access")
    args = ap.parse_args()

    cik, title, ticker = resolve_cik(args, args.ua)
    filings = find_earnings_8ks(cik, args.ua)
    if not filings:
        fail(f"no 8-K (Item 2.02) earnings filings found for {title} (CIK {cik}).")

    chosen = pick(filings, args.date)
    ex_url, folder, src = find_ex991(cik, chosen["accession"], args.ua, chosen.get("primary_doc"))

    # Optionally resolve Ex-99.1 for the top N candidates (multi-quarter lineage).
    n_resolve = min(max(args.resolve_candidates, 0), len(filings))
    candidates = []
    for i, f in enumerate(filings[:max(8, n_resolve)]):
        cand = {"filing_date": f["filing_date"], "accession": f["accession"], "items": f["items"]}
        if i < n_resolve:
            c_url, c_folder, c_src = find_ex991(cik, f["accession"], args.ua, f.get("primary_doc"))
            cand.update({"folder_url": c_folder, "ex99_1_url": c_url, "ex99_1_source": c_src})
        candidates.append(cand)

    print(json.dumps({
        "company_title": title,
        "cik": cik,
        "ticker": ticker,
        "selected": {
            "form": "8-K",
            "items": chosen["items"],
            "filing_date": chosen["filing_date"],
            "accession": chosen["accession"],
            "folder_url": folder,
            "ex99_1_url": ex_url,
            "ex99_1_source": src,
        },
        "candidates": candidates,
        "ua": args.ua,
    }, indent=2))


if __name__ == "__main__":
    main()
