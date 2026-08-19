#!/usr/bin/env python3
"""
pdf_to_png.py - render PDF manuscript scans to high-res, lossless PNG:
the format all three engines (Claude, Transkribus, ChatGPT) accept and that
preserves faint ink (unlike JPEG, which smears it, or TIFF, which chat UIs
reject).

Usage:
  python pdf_to_png.py INPUT.pdf [--dpi 400] [--outdir pages] [--pages 1-3,7]
Notes:
  * Renders in COLOUR (RGB). Never let the PDF hand you a bitonal/grayscale
    page - faint iron-gall ink survives best in colour.
  * DPI is the RENDER target. If the PDF only *wraps* low-res JPEGs, rendering
    at 400 won't add real detail; the script prints the effective pixel size so
    you can sanity-check (a full page should be ~3000-5000 px on the long side).
"""
import argparse, os, sys
import pypdfium2 as pdfium
from ingest import validate_file, IngestRejected

def parse_pages(spec, n):
    if not spec: return list(range(n))
    out=[]
    for part in spec.split(","):
        if "-" in part:
            a,b=part.split("-"); out+=list(range(int(a)-1,int(b)))
        else: out.append(int(part)-1)
    return [p for p in out if 0<=p<n]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("pdf"); ap.add_argument("--dpi",type=int,default=400)
    ap.add_argument("--outdir",default="pages"); ap.add_argument("--pages",default="")
    a=ap.parse_args()

    try:
        validate_file(a.pdf)
    except IngestRejected as e:
        print(f"REJECTED: {e}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(a.outdir,exist_ok=True)
    doc=pdfium.PdfDocument(a.pdf)
    scale=a.dpi/72.0
    pages=parse_pages(a.pages,len(doc))
    base=os.path.splitext(os.path.basename(a.pdf))[0]
    for i in pages:
        page=doc[i]
        pil=page.render(scale=scale, draw_annots=False).to_pil().convert("RGB")
        w,h=pil.size; longside=max(w,h)
        out=os.path.join(a.outdir,f"{base}_p{i+1:03d}.png")
        pil.save(out,"PNG")
        flag = "  <-- LOW: source PDF is probably low-res; higher DPI won't help" if longside<2500 else ""
        print(f"page {i+1}: {w}x{h}px  ({longside}px long side){flag}  -> {out}")
    print("done. PNG is the working format; keep the PDF as archival master.")

if __name__=="__main__": main()
