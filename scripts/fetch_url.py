#!/usr/bin/env python3
"""Fetch a URL to text using an SEC fair-access User-Agent.

Why: WebFetch is blocked (HTTP 403) by sec.gov, which requires a declared
User-Agent. This helper uses urllib with a contact UA so EDGAR documents (the
8-K / Exhibit 99.1) download cleanly. HTML is reduced to readable text with
table structure preserved (rows -> newlines, cells -> ' | '). For NON-SEC pages
(IR sites, free transcript URLs) prefer WebFetch — it renders better.

Usage:
  python fetch_url.py "<url>" --out "<run_dir>/raw_release.txt"
"""
import argparse
import gzip
import html as html_mod
import json
import re
import sys
import urllib.request
from pathlib import Path

DEFAULT_UA = "financeAI earnings-summary (brianxie45@gmail.com)"


def fetch(url, ua):
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "text/html,application/xhtml+xml,*/*",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        if r.info().get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        charset = r.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def html_to_text(s):
    s = re.sub(r"(?is)<script.*?</script>", " ", s)
    s = re.sub(r"(?is)<style.*?</style>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(td|th)>", " | ", s)        # cell separator
    s = re.sub(r"(?i)</(tr|div|p|h[1-6]|table|li)>", "\n", s)  # block -> newline
    s = re.sub(r"(?s)<[^>]+>", "", s)               # drop remaining tags
    s = html_mod.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\| *(?:\| *)+", " | ", s)         # collapse empty cells
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return "\n".join(line.strip() for line in s.splitlines()).strip()


def main():
    ap = argparse.ArgumentParser(description="Fetch a URL to text (SEC-friendly UA).")
    ap.add_argument("url")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ua", default=DEFAULT_UA)
    args = ap.parse_args()

    try:
        doc = fetch(args.url, args.ua)
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    looks_html = ("<html" in doc.lower() or "<table" in doc.lower()
                  or args.url.lower().endswith((".htm", ".html")))
    text = html_to_text(doc) if looks_html else doc

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(json.dumps({"out": str(out.resolve()), "chars": len(text), "words": len(text.split())}))


if __name__ == "__main__":
    main()
