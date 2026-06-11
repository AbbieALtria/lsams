"""
Convert LSAMS_Presentation.html to a landscape PDF (one slide per page).
Uses WeasyPrint. Run: python generate_pdf.py
"""
from weasyprint import HTML, CSS
import os, pathlib

src  = pathlib.Path(__file__).parent / "LSAMS_Presentation.html"
out  = pathlib.Path(__file__).parent / "LSAMS_Presentation.pdf"

# Override CSS for print: show all slides, one per page, A4 landscape
print_css = CSS(string="""
@page {
    size: 1280px 720px;
    margin: 0;
}

/* Reset screen-mode engine */
html, body {
    width: 1280px;
    height: 720px;
    overflow: visible !important;
    background: #111;
}

/* Hide nav and progress bar */
.nav, .prog { display: none !important; }

/* Make deck flow as block (not fixed) */
.deck {
    position: static !important;
    width: 1280px;
}

/* Every slide: show as a full-page block */
.slide {
    display: flex !important;
    opacity: 1 !important;
    position: relative !important;
    width: 1280px !important;
    height: 720px !important;
    page-break-after: always;
    break-after: page;
    overflow: hidden;
}

/* Slide number chips: hide the absolute-positioned ones */
.snum { display: none !important; }

/* Last slide: no trailing blank page */
.slide:last-of-type {
    page-break-after: avoid;
    break-after: avoid;
}
""")

print(f"Reading:  {src}")
print(f"Writing:  {out}")

HTML(filename=str(src)).write_pdf(
    str(out),
    stylesheets=[print_css],
    presentational_hints=True,
)

size_kb = out.stat().st_size // 1024
print(f"Done — {size_kb} KB  →  {out.name}")
