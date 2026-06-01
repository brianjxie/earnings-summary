"""PDF scanning primitives.

Consumed here by scripts/extract_pdf_text.py (transcript / release PDFs). This
is a general-purpose primitive — a caller keeps its own scope-specific keyword
lists, scoring function, exhibit patterns, and selection thresholds; this module
owns:
  - constants whose values must match across both scanners (boilerplate
    signatures, date patterns, year regex, image-only threshold)
  - the pdfplumber text-extraction loop
  - the pypdfium2 PNG rendering loop
  - report-date extraction and page-range merging helpers
"""
import logging
import re
from pathlib import Path

logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfplumber").setLevel(logging.ERROR)

import pdfplumber
import pypdfium2 as pdfium


DATE_PATTERNS = [
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+20\d{2}\b",
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+20\d{2}\b",
    r"\b\d{1,2}[/\-]\d{1,2}[/\-](?:20\d{2}|\d{2})\b",
    r"\b20\d{2}[/\-]\d{1,2}[/\-]\d{1,2}\b",
]

# Disclaimer/boilerplate signature phrases — pages with >=2 of these are
# treated as legalese, not model content.
BOILERPLATE_SIGNATURES = [
    "salespeople, traders",
    "supervised by the",
    "this research is for our clients only",
    "investors should consider this report",
    "regulation analyst certification",
    "global investment research",
    "disclosure appendix",
]

# Years 2020-2049. Used to detect multi-year column layouts (a model table
# typically has 5+ distinct year tokens) and to extract the model horizon
# (max_year) from scored pages.
YEAR_RE = re.compile(r"\b20[2-4]\d[EF]?\b")

# Pages with fewer than this many extracted characters are treated as
# "image-only" — the table is likely an embedded screenshot and the text
# extractor saw nothing useful. These pages get force-rendered to PNG.
IMAGE_TEXT_THRESHOLD = 200


def extract_report_date(text):
    """Return the first date-looking substring matching DATE_PATTERNS, or None."""
    for pat in DATE_PATTERNS:
        m = re.search(pat, text)
        if m:
            return m.group(0)
    return None


def merge_ranges(pages, context=1, max_page=None):
    """Expand each page by +/- context, then merge adjacent pages into ranges.

    pages: iterable of 1-based page numbers
    context: number of adjacent pages to include on each side
    max_page: optional cap (drop expanded pages > max_page)
    Returns a list of [start, end] inclusive ranges.
    """
    if not pages:
        return []
    expanded = set()
    for p in pages:
        for q in range(max(1, p - context), p + context + 1):
            expanded.add(q)
    if max_page is not None:
        expanded = {p for p in expanded if p <= max_page}
    expanded_sorted = sorted(expanded)
    ranges = []
    start = prev = expanded_sorted[0]
    for p in expanded_sorted[1:]:
        if p == prev + 1:
            prev = p
        else:
            ranges.append([start, prev])
            start = prev = p
    ranges.append([start, prev])
    return ranges


def extract_pages_to_cache(pdf_path, cover_page_count=3):
    """Open pdf_path with pdfplumber and extract per-page text.

    Returns (total_pages, page_text_cache, cover_text) where:
      total_pages       int
      page_text_cache   {1-based page_num: extracted_text_or_empty_str}
      cover_text        "\\n".join of the first cover_page_count pages

    Per-page text-extraction errors are swallowed (text becomes ""). Whole-PDF
    open errors propagate — callers wrap in their own try/except to format
    the error for stdout/stderr.
    """
    page_text_cache = {}
    cover_parts = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            page_text_cache[i] = text
            if i <= cover_page_count:
                cover_parts.append(text)
    return total_pages, page_text_cache, "\n".join(cover_parts)


def render_pages_to_pngs(
    pdf_path,
    pages_to_render,
    images_dir,
    image_only_pages,
    exhibit_pages,
    pages_text,
    scale=2.0,
):
    """Render each page in pages_to_render to images_dir/p{NNNN}.png.

    Returns a list of dicts: {page, image_path, extracted_chars, reason}.
    Reason precedence: image_only > exhibit_title > top_scoring.

    image_only_pages / exhibit_pages: sets used only to derive the reason tag.
    pages_text: {str(page_num): text} — used to compute extracted_chars.
    Per-page render failures are swallowed (best-effort). Failure to open the
    PDF for rendering propagates — callers warn and continue with empty list.
    """
    pdf_path = Path(pdf_path)
    images_dir = Path(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    image_pages = []
    pdf_doc = pdfium.PdfDocument(str(pdf_path))
    try:
        for p in pages_to_render:
            try:
                page = pdf_doc[p - 1]
                bitmap = page.render(scale=scale)
                pil = bitmap.to_pil()
                png_path = images_dir / f"p{p:04d}.png"
                pil.save(str(png_path))
                if p in image_only_pages:
                    reason = "image_only"
                elif p in exhibit_pages:
                    reason = "exhibit_title"
                else:
                    reason = "top_scoring"
                image_pages.append({
                    "page": p,
                    "image_path": str(png_path.resolve()),
                    "extracted_chars": len(pages_text.get(str(p), "").strip()),
                    "reason": reason,
                })
            except Exception:
                pass
    finally:
        pdf_doc.close()
    return image_pages
