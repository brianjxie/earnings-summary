#!/usr/bin/env python3
"""Render an earnings-summary memo (.md) to a styled PDF.

Pure-Python, pip-only (reportlab) — NO system libraries, no LaTeX, no browser.
A focused parser turns the memo's known markdown subset (headings, tables,
blockquote, bullets, hr, inline bold/italic/code/links) into reportlab
flowables, and color-codes scorecard verdicts (BEAT/MISS/IN-LINE) and guidance
actions (RAISE/CUT/MAINTAIN/UPDATE/INITIATE).

reportlab's built-in Helvetica uses WinAnsi encoding, so em dashes, curly
quotes, bullets and ± render correctly without bundling any font file.

Usage:
  python render_pdf.py "<memo.md>" [--out "<memo.pdf>"]
"""
import argparse
import html as html_mod
import json
import re
import sys
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

NAVY = colors.HexColor("#0b3d66")
GRID = colors.HexColor("#cccccc")
BAND = colors.HexColor("#f6f8fa")
INK = colors.HexColor("#1a1a1a")

VERDICT_HEX = {
    "BEAT": "#0a7d2c", "RAISE": "#0a7d2c",
    "MISS": "#c0202c", "CUT": "#c0202c",
    "IN-LINE": "#666666", "MAINTAIN": "#666666",
    "UPDATE": "#1f5fbf", "INITIATE": "#1f5fbf",
}

styles = {
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=16, textColor=NAVY,
                         leading=19, spaceAfter=2),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12, textColor=NAVY,
                         leading=15, spaceBefore=11, spaceAfter=3),
    "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10, textColor=colors.HexColor("#333333"),
                         leading=12, spaceBefore=7, spaceAfter=2),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9, textColor=INK,
                           leading=12.5, spaceAfter=3),
    "quote": ParagraphStyle("quote", fontName="Helvetica", fontSize=9.5, textColor=INK,
                            leading=13, leftIndent=2, spaceAfter=2),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=7, textColor=INK, leading=8.6),
    "cellh": ParagraphStyle("cellh", fontName="Helvetica-Bold", fontSize=7,
                            textColor=colors.white, leading=8.6),
    "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=9, textColor=INK,
                             leading=12.5, leftIndent=12, bulletIndent=2, spaceAfter=2),
}


def inline(text):
    """Convert the memo's inline markdown to reportlab markup."""
    s = html_mod.escape(text, quote=False)
    codes = []
    s = re.sub(r"`([^`]+)`", lambda m: (codes.append(m.group(1)), f"\x00{len(codes)-1}\x00")[1], s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<link href="\2" color="#0b3d66">\1</link>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", s)
    s = re.sub(r"\x00(\d+)\x00",
               lambda m: f'<font face="Courier">{html_mod.escape(codes[int(m.group(1))], quote=False)}</font>', s)
    return s


def cell(raw, header):
    plain = raw.replace("*", "").strip()
    if not header and plain in VERDICT_HEX:
        return Paragraph(f'<b><font color="{VERDICT_HEX[plain]}">{plain}</font></b>', styles["cell"])
    return Paragraph(inline(raw) or "&nbsp;", styles["cellh"] if header else styles["cell"])


def make_table(rows, usable):
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    if ncols >= 5:
        first = 0.22 * usable
    elif ncols == 4:
        first = 0.28 * usable
    else:
        first = usable / ncols
    rest = (usable - first) / (ncols - 1) if ncols > 1 else usable
    colw = [first] + [rest] * (ncols - 1)

    data = [[cell(c, header=(r == 0)) for c in row] for r, row in enumerate(rows)]
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.25, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    for r in range(2, len(rows), 2):
        ts.append(("BACKGROUND", (0, r), (-1, r), BAND))
    t = Table(data, colWidths=colw, repeatRows=1)
    t.setStyle(TableStyle(ts))
    return t


def is_table_sep(line):
    return bool(re.match(r"^\|?[\s:|-]+\|?$", line)) and "-" in line


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def parse(md_text, usable):
    flow = []
    lines = md_text.splitlines()
    i, n = 0, len(lines)
    para = []

    def flush_para():
        if para:
            flow.append(Paragraph(inline(" ".join(para).strip()), styles["body"]))
            para.clear()

    while i < n:
        line = lines[i]
        s = line.strip()

        if s.startswith("|") and i + 1 < n and is_table_sep(lines[i + 1]):
            flush_para()
            block = [split_row(line)]
            i += 2  # skip header + separator
            while i < n and lines[i].strip().startswith("|"):
                block.append(split_row(lines[i]))
                i += 1
            flow.append(make_table(block, usable))
            flow.append(Spacer(1, 5))
            continue

        if s.startswith("#"):
            flush_para()
            m = re.match(r"^(#{1,6})\s+(.*)", s)
            level, txt = len(m.group(1)), m.group(2)
            key = {1: "h1", 2: "h2", 3: "h3"}.get(level, "h3")
            flow.append(Paragraph(inline(txt), styles[key]))
            if level == 1:
                flow.append(HRFlowable(width="100%", thickness=1.4, color=NAVY,
                                       spaceBefore=2, spaceAfter=4))
            i += 1
            continue

        if re.match(r"^(---+|\*\*\*+)$", s):
            flush_para()
            flow.append(HRFlowable(width="100%", thickness=0.6,
                                   color=colors.HexColor("#cdd9e5"), spaceBefore=6, spaceAfter=6))
            i += 1
            continue

        if s.startswith("> "):
            flush_para()
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            inner = Paragraph(inline(" ".join(quote).strip()), styles["quote"])
            box = Table([[inner]], colWidths=[usable])
            box.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f7fb")),
                ("LINEBEFORE", (0, 0), (0, -1), 3, NAVY),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            flow.append(box)
            flow.append(Spacer(1, 5))
            continue

        if re.match(r"^[-*]\s+", s):
            flush_para()
            txt = re.sub(r"^[-*]\s+", "", s)
            flow.append(Paragraph(inline(txt), styles["bullet"], bulletText="•"))
            i += 1
            continue

        if not s:
            flush_para()
            i += 1
            continue

        para.append(s)
        i += 1

    flush_para()
    return flow


def main():
    ap = argparse.ArgumentParser(description="Render an earnings memo .md to PDF.")
    ap.add_argument("md")
    ap.add_argument("--out")
    args = ap.parse_args()

    src = Path(args.md).expanduser()
    if not src.exists():
        print(json.dumps({"error": f"memo not found: {src}"}), file=sys.stderr)
        sys.exit(1)

    out_pdf = Path(args.out).expanduser() if args.out else src.with_suffix(".pdf")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    margin = 0.6 * inch
    usable = letter[0] - 2 * margin
    doc = SimpleDocTemplate(str(out_pdf), pagesize=letter,
                            leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=margin,
                            title=src.stem)
    doc.build(parse(src.read_text(), usable))
    print(json.dumps({"pdf": str(out_pdf.resolve())}))


if __name__ == "__main__":
    main()
