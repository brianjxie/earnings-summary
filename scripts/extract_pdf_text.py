#!/usr/bin/env python3
"""Extract full text from a PDF (transcript, or a release supplied as PDF).

Reuses lib/pdf_lib.py — the bundled PDF primitive. Writes the
concatenated per-page text to --out with `--- PAGE <N> ---` headers so the
extraction agent can cite page numbers, and reports any image-only pages (little
extractable text — likely an embedded screenshot/table) so the runbook can
decide whether to render them to PNG and read them visually.

Usage:
  python extract_pdf_text.py "<pdf path>" --out "<run_dir>/raw_transcript.txt"
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.pdf_lib import extract_pages_to_cache, IMAGE_TEXT_THRESHOLD  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Extract PDF text for earnings-summary.")
    ap.add_argument("pdf", help="path to the PDF")
    ap.add_argument("--out", required=True, help="output .txt path")
    args = ap.parse_args()

    pdf_path = Path(args.pdf).expanduser()
    if not pdf_path.exists():
        print(json.dumps({"error": f"PDF not found: {pdf_path}"}), file=sys.stderr)
        sys.exit(1)

    try:
        total_pages, page_text, _cover = extract_pages_to_cache(pdf_path, cover_page_count=0)
    except Exception as e:  # whole-PDF open failure
        print(json.dumps({"error": f"could not open PDF: {e}"}), file=sys.stderr)
        sys.exit(1)

    parts, image_only, total_chars = [], [], 0
    for p in range(1, total_pages + 1):
        text = (page_text.get(p, "") or "").strip()
        total_chars += len(text)
        if len(text) < IMAGE_TEXT_THRESHOLD:
            image_only.append(p)
        parts.append(f"--- PAGE {p} ---\n{text}")

    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n\n".join(parts))

    note = (
        "All pages have extractable text."
        if not image_only
        else (f"{len(image_only)} page(s) had little/no extractable text — likely image "
              "tables. If a needed value is missing, render those pages to PNG and read visually.")
    )
    print(json.dumps({
        "out": str(out_path.resolve()),
        "pages": total_pages,
        "chars": total_chars,
        "image_only_pages": image_only,
        "note": note,
    }, indent=2))


if __name__ == "__main__":
    main()
