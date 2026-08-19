#!/usr/bin/env python3
"""
verify_glyph.py - vet a single contested letter/word without confirmation bias.
Outputs one panel: RAW crop | SAFE-enhanced crop | SHARP crop | DIFF map.
The DIFF map shows GREEN where processing darkened/added ink and RED where it
removed ink. Trust a reading only if the SAFE/SHARP shape is ALSO traceable in
RAW, and if the DIFF shows no green sitting on blank paper.

Usage:
  python verify_glyph.py IMAGE x y w h [--out out.png] [--zoom 4]
    x y w h : crop box in PIXELS (top-left origin)
  or fractional (0-1) coords with --frac:
  python verify_glyph.py IMAGE 0.02 0.44 0.30 0.12 --frac
"""
import argparse, cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont

def enhance_safe(bgr):
    blur = cv2.GaussianBlur(bgr,(0,0),40)
    flat = cv2.divide(bgr,blur,scale=255)
    blue = flat[:,:,0]
    lab  = cv2.cvtColor(flat,cv2.COLOR_BGR2Lab); bstar = 255-lab[:,:,2]
    chosen = blue if blue.std()>=bstar.std() else bstar     # auto channel
    cl = cv2.createCLAHE(clipLimit=2.5,tileGridSize=(8,8)).apply(chosen)
    lo,hi = np.percentile(cl,1),np.percentile(cl,99)
    return np.clip((cl.astype(float)-lo)/(hi-lo),0,1)*255

def sharpen(gray8):
    g = cv2.GaussianBlur(gray8,(0,0),2)
    return cv2.addWeighted(gray8,1.6,g,-0.6,0)

def diffmap(raw_gray, proc_gray):
    def norm(a): a=a.astype(float); a-=a.min(); return a/(a.max()+1e-6)
    ri = 1-norm(raw_gray); pi = 1-norm(proc_gray)   # ink positive
    d = pi-ri
    out = np.zeros((*ri.shape,3),np.uint8)
    out[...,1] = np.clip( d,0,1)*255*3   # green = added/darkened
    out[...,2] = np.clip(-d,0,1)*255*3   # red   = removed
    ctx = np.stack([(1-ri)*160]*3,-1).astype(np.uint8)
    return cv2.addWeighted(ctx,1.0,out,1.0,0)

def upscale(img, z):
    return cv2.resize(img,(img.shape[1]*z,img.shape[0]*z),interpolation=cv2.INTER_NEAREST)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("image"); ap.add_argument("x",type=float); ap.add_argument("y",type=float)
    ap.add_argument("w",type=float); ap.add_argument("h",type=float)
    ap.add_argument("--frac",action="store_true"); ap.add_argument("--zoom",type=int,default=4)
    ap.add_argument("--out",default="glyph_check.png")
    a=ap.parse_args()
    bgr=cv2.imread(a.image); H,W=bgr.shape[:2]
    if a.frac: x,y,w,h=int(a.x*W),int(a.y*H),int(a.w*W),int(a.h*H)
    else: x,y,w,h=map(int,(a.x,a.y,a.w,a.h))
    raw = bgr[y:y+h, x:x+w]
    raw_g = cv2.cvtColor(raw,cv2.COLOR_BGR2GRAY)
    safe = enhance_safe(bgr)[y:y+h, x:x+w].astype(np.uint8)
    shrp = sharpen(safe)
    dmap = diffmap(raw_g, safe)
    z=a.zoom
    tiles=[("RAW (source of truth)",cv2.cvtColor(upscale(raw,z),cv2.COLOR_BGR2RGB)),
           ("SAFE enhance",cv2.cvtColor(upscale(safe,z),cv2.COLOR_GRAY2RGB)),
           ("SHARP (pointer only)",cv2.cvtColor(upscale(shrp,z),cv2.COLOR_GRAY2RGB)),
           ("DIFF  green=added red=lost",cv2.cvtColor(upscale(dmap,z),cv2.COLOR_BGR2RGB))]
    tw=max(t[1].shape[1] for t in tiles); th=max(t[1].shape[0] for t in tiles); bar=38
    canvas=Image.new("RGB",(tw, (th+bar)*len(tiles)+10),(245,245,247))
    d=ImageDraw.Draw(canvas)
    try:f=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",22)
    except:f=ImageFont.load_default()
    yy=5
    for label,im in tiles:
        d.rectangle([0,yy,tw,yy+bar],fill=(30,34,60)); d.text((8,yy+7),label,font=f,fill=(255,255,255))
        canvas.paste(Image.fromarray(im),(0,yy+bar)); yy+=bar+th
    canvas.save(a.out); print("wrote",a.out,canvas.size)

if __name__=="__main__": main()
