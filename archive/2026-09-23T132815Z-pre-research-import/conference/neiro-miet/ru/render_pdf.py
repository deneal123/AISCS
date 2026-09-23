# /// script
# dependencies = ["mammoth>=1.11"]
# ///
"""Render an auxiliary PDF preview from the DOCX with headless Microsoft Edge.

Microsoft Word remains the authoritative pagination and final-PDF renderer.
"""

from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path

import mammoth


HERE = Path(__file__).resolve().parent
DOCX = HERE / "article.docx"
HTML = HERE / "article.html"
PDF = HERE / "article.preview.pdf"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


STYLE_MAP = """
p[style-name='Article Title'] => h1.article-title:fresh
p[style-name='Author Block'] => p.author:fresh
p[style-name='Article Abstract'] => p.abstract:fresh
p[style-name='Section Heading'] => h2:fresh
p[style-name='Subsection Heading'] => h3:fresh
p[style-name='Figure Caption'] => p.caption:fresh
p[style-name='Table Number'] => p.table-number:fresh
p[style-name='Table Title'] => p.table-title:fresh
p[style-name='Bibliography Entry'] => p.ref:fresh
p[style-name='UDK'] => p.udk:fresh
"""


CSS = """
@page { size: A4; margin: 20mm 20mm 17.5mm 19mm; }
* { box-sizing: border-box; }
body { width: auto; margin: 0; color: #000; font-family: 'Times New Roman', serif;
       font-size: 10pt; line-height: 1.0; }
p { margin: 0; text-align: justify; text-indent: 7.5mm; orphans: 2; widows: 2; }
p.udk { font-weight: bold; text-indent: 0; text-align: left; margin-bottom: 2pt; }
h1.article-title { margin: 5pt 0 3pt; font-size: 10pt; line-height: 1.05;
                   text-align: center; font-weight: bold; page-break-after: avoid; }
p.author { text-align: center; text-indent: 0; font-style: italic; margin: 0 0 1pt;
           page-break-after: avoid; }
p.abstract { margin: 1pt 7.5mm; text-indent: 7.5mm; font-size: 9pt; font-style: italic; }
h2 { margin: 6pt 0 2pt; font-size: 10pt; font-weight: bold; text-align: left;
     page-break-after: avoid; }
h3 { margin: 4pt 0 1pt; font-size: 10pt; font-weight: bold; font-style: italic;
     text-align: left; page-break-after: avoid; }
p.caption { text-align: center; text-indent: 0; font-size: 10pt; font-style: italic;
            margin: 0 0 2pt; page-break-before: avoid; }
p.table-number { text-align: right; text-indent: 0; font-weight: bold;
                 font-style: italic; margin-top: 6pt; page-break-after: avoid; }
p.table-title { text-align: center; text-indent: 0; font-weight: bold;
                margin-bottom: 3.6pt; page-break-after: avoid; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; margin: 0 0 2pt;
        page-break-inside: auto; }
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
td, th { border: 0.5pt solid #000; padding: 0.7mm 0.8mm; text-align: center;
         vertical-align: middle; font-size: 10pt; line-height: 1.0; }
td p, th p { margin: 0; text-indent: 0; text-align: center; }
thead th { background: #fff; font-weight: bold; }
img { display: block; max-width: 100%; max-height: 49mm; margin: 2pt auto 0; }
p.ref { margin: 0; padding-left: 5.5mm; text-indent: -5.5mm; font-size: 10pt;
        line-height: 1.0; }
strong { font-weight: bold; }
em { font-style: italic; }
"""


def image_converter(image):
    with image.open() as image_bytes:
        encoded = base64.b64encode(image_bytes.read()).decode("ascii")
    return {"src": f"data:{image.content_type};base64,{encoded}"}


def main():
    with DOCX.open("rb") as source:
        result = mammoth.convert_to_html(source, style_map=STYLE_MAP, convert_image=mammoth.images.img_element(image_converter))
    html = f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><style>{CSS}</style></head><body>{result.value}</body></html>"
    HTML.write_text(html, encoding="utf-8")
    if not EDGE.exists():
        raise FileNotFoundError(EDGE)
    if PDF.exists():
        PDF.unlink()
    with tempfile.TemporaryDirectory(prefix="aspa-edge-") as profile:
        cmd = [str(EDGE), "--headless", "--disable-gpu", "--no-pdf-header-footer",
               "--run-all-compositor-stages-before-draw", f"--user-data-dir={profile}",
               f"--print-to-pdf={PDF}", HTML.as_uri()]
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if run.returncode != 0 or not PDF.exists():
            raise RuntimeError(f"Edge PDF failed ({run.returncode}): {run.stderr[-1000:]}")
    print(PDF)


if __name__ == "__main__":
    main()
