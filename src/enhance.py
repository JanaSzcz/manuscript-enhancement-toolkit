#!/usr/bin/env python3
"""
enhance.py - reveal faded handwriting for HTR/LLM reading WITHOUT fabricating
strokes. Order of operations = flat-field -> channel pick -> CLAHE -> levels,
then an OPTIONAL sharpen/upscale that is a POINTER only (never your evidence).

Golden rules baked in:
  * never binarize (destroys faint strokes; engines want grayscale)
  * output stays 8-bit GRAYSCALE PNG
  * emits BOTH channel candidates so you pick per document
  * the aggressive sharpened file is written separately and clearly named

Usage:
  python enhance.py IMAGE.png [--sigma 40] [--clip 2.5] [--upscale 1.7]
                              [--outdir enhanced]
"""
import argparse, os, sys, cv2, numpy as np
from ingest import validate_file, IngestRejected

def flatfield(bgr, sigma):
    return cv2.divide(bgr, cv2.GaussianBlur(bgr,(0,0),sigma), scale=255)

def levels(gray, lop=1, hip=99):
    lo,hi=np.percentile(gray,lop),np.percentile(gray,hip)
    return (np.clip((gray.astype(float)-lo)/(hi-lo),0,1)*255).astype(np.uint8)

def enhance_page(bgr, sigma=40, clip=2.5):
    """flat-field -> channel pick -> CLAHE -> levels. Pure function (array in,
    array out): same input + params always yields the same bytes.

    Returns (cand, best) where cand is {"blue": uint8 array, "bstar": uint8
    array} (both channel candidates, so a caller can inspect either) and
    best is the key of the higher-contrast one. This is the ONE place that
    implements the safe-enhancement math; the CLI (main(), below) and
    app.py both call it rather than reimplementing it.
    """
    flat=flatfield(bgr,sigma)
    blue=flat[:,:,0]
    bstar=255-cv2.cvtColor(flat,cv2.COLOR_BGR2Lab)[:,:,2]
    cl=lambda ch: cv2.createCLAHE(clipLimit=clip,tileGridSize=(8,8)).apply(ch)
    cand={"blue":levels(cl(blue)), "bstar":levels(cl(bstar))}
    best=max(cand, key=lambda k: cand[k].std())
    return cand, best

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("image"); ap.add_argument("--sigma",type=float,default=40)
    ap.add_argument("--clip",type=float,default=2.5); ap.add_argument("--upscale",type=float,default=1.7)
    ap.add_argument("--outdir",default="enhanced")
    a=ap.parse_args()

    try:
        validate_file(a.image)
    except IngestRejected as e:
        print(f"REJECTED: {e}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(a.outdir,exist_ok=True)
    base=os.path.splitext(os.path.basename(a.image))[0]
    bgr=cv2.imread(a.image)
    cand,best=enhance_page(bgr,a.sigma,a.clip)

    # pick higher-contrast channel automatically, but write both so you can judge
    for name,img in cand.items():
        tag="_BEST" if name==best else ""
        cv2.imwrite(os.path.join(a.outdir,f"{base}_safe_{name}{tag}.png"), img)

    # sharpened + upscaled POINTER version from the best channel
    safe=cand[best]
    up=cv2.resize(safe,(int(safe.shape[1]*a.upscale),int(safe.shape[0]*a.upscale)),
                  interpolation=cv2.INTER_LANCZOS4)
    g=cv2.GaussianBlur(up,(0,0),2)
    sharp=cv2.addWeighted(up,1.6,g,-0.6,0)
    cv2.imwrite(os.path.join(a.outdir,f"{base}_pointer_sharp.png"), sharp)

    print(f"channel scores: blue={cand['blue'].std():.1f}  bstar={cand['bstar'].std():.1f}  -> BEST={best}")
    print("READ from *_safe_*_BEST.png ; use *_pointer_sharp.png only to locate;")
    print("ALWAYS confirm final readings against the untouched original.")
    print("Tip: also run the ORIGINAL through the engine - sometimes it scores higher.")

if __name__=="__main__": main()
