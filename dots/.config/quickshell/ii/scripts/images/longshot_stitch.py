#!/usr/bin/env python3
"""Stitch a sequence of vertically-scrolling screenshots into one tall image.

The frames are expected to be captured top-to-bottom while the content scrolls.
Consecutive frames overlap; we find that overlap by matching the top of the next
frame against the bottom of the accumulated image, then append only the new
rows.

Matching uses zero-normalized cross-correlation (ZNCC) rather than a plain pixel
difference. That matters on fractional-scale displays: scrolling by a whole
number of text lines still shifts the composited output by a non-integer number
of physical pixels, so the same text is re-rasterized with a different phase and
a pixel-exact comparison fails even though the content is identical. ZNCC is
robust to that brightness/contrast re-rendering.

Also usable as a direction detector:

    longshot_stitch.py --detect-dir before.png after.png
    -> prints "down", "up" or "none"
"""

import argparse
import json
import sys

import numpy as np
from PIL import Image


def load_rgb(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)


def gray(img):
    """Integer-ish luma in float32, shape (H, W)."""
    return (
        0.299 * img[..., 0].astype(np.float32)
        + 0.587 * img[..., 1].astype(np.float32)
        + 0.114 * img[..., 2].astype(np.float32)
    )


def _mad(a, b):
    """Mean absolute difference between two equally shaped arrays."""
    return float(np.abs(a - b).mean())


def _zncc(a, b):
    """Zero-normalized cross-correlation of two arrays, in [-1, 1]."""
    x = a.ravel().astype(np.float32)
    y = b.ravel().astype(np.float32)
    x = x - x.mean()
    y = y - y.mean()
    denom = float(np.linalg.norm(x)) * float(np.linalg.norm(y))
    if denom < 1e-6:
        return 0.0
    return float(np.dot(x, y) / denom)


def best_overlap(acc_gray, new_gray, min_overlap=40, max_overlap=0, downscale=8,
                 trim_right=0):
    """Find k such that the last k rows of ``acc_gray`` match the first k rows
    of ``new_gray`` (i.e. how many rows the new frame repeats).

    A short band from near the top of the new frame is used as a template and
    slid over the accumulated image at full vertical resolution. This avoids the
    phase problem you get when downsampling rows: a scroll offset is rarely a
    multiple of the downscale factor, so 2D-downsampled frames can never align.
    Only columns are downsampled (for speed).

    Returns (k, zncc). ``k == 0`` means no plausible overlap was found.
    """
    if trim_right > 0:
        acc_gray = acc_gray[:, :-trim_right] if acc_gray.shape[1] > trim_right else acc_gray
        new_gray = new_gray[:, :-trim_right] if new_gray.shape[1] > trim_right else new_gray

    ha, hb = acc_gray.shape[0], new_gray.shape[0]
    if ha < 2 or hb < 2:
        return 0, -1.0

    # Downsample columns only, keeping every row.
    cstep = max(1, max(acc_gray.shape[1], new_gray.shape[1]) // 160)
    a = acc_gray[:, ::cstep]
    b = new_gray[:, ::cstep]
    ha, hb = a.shape[0], b.shape[0]

    # Probe band from near the top of the new frame. It must live inside the
    # overlap, so keep its start within the guaranteed min_overlap region.
    t = min(128, hb // 2)
    if t < 4:
        return 0, -1.0
    max_start = max(0, min(min_overlap, hb - t))
    best_probe = None
    best_var = -1.0
    best_st = 0
    for st in range(0, max_start + 1, max(1, max_start // 5 or 1)):
        band = b[st:st + t]
        var = float(band.var())
        if var > best_var:
            best_var = var
            best_probe = band
            best_st = st
    if best_probe is None:
        return 0, -1.0

    # Offset s in the accumulated image where the probe starts.
    # new row best_st aligns with acc row s; overlap k = ha - (s - best_st).
    s_lo = max(0, ha - hb - t)            # overlap cannot exceed new height
    if max_overlap and max_overlap > 0:
        s_lo = max(s_lo, ha - max_overlap)
    s_hi = ha - t
    if s_hi < s_lo:
        return 0, -1.0

    candidates = [(_zncc(a[s:s + t], best_probe), s)
                  for s in range(s_lo, s_hi + 1)]
    if not candidates:
        return 0, -1.0
    candidates.sort(reverse=True)         # highest correlation first

    # Verify the *whole* overlap for the plausible candidates, not just the
    # probe band. This filters out coincidental matches on repetitive content.
    probe_best = candidates[0][0]
    probe_cut = probe_best - 0.1
    pool = [s for c, s in candidates if c >= probe_cut][:200]
    best_k = 0
    best_full = -1.0
    for s in pool:
        k = ha - (s - best_st)
        if k <= 0 or k > hb:
            continue
        full = _zncc(a[ha - k:ha], b[0:k])
        # Tie-break towards the larger overlap (smaller scroll assumption).
        if full > best_full or (full == best_full and k > best_k):
            best_full = full
            best_k = k
    if best_k == 0:
        return 0, -1.0
    return best_k, best_full


def detect_direction(before, after, min_overlap=40, downscale=8, min_corr=0.5):
    """Return 'down', 'up' or 'none' describing how the view scrolled."""
    a = gray(before)
    b = gray(after)
    if a.shape != b.shape:
        return "none"
    if _mad(a, b) < 0.05:
        return "none"
    # Scrolling down -> new frame's top repeats the previous frame's bottom.
    _, down = best_overlap(a, b, min_overlap=min_overlap, downscale=downscale)
    # Scrolling up -> new frame's bottom repeats the previous frame's top.
    _, up = best_overlap(b, a, min_overlap=min_overlap, downscale=downscale)
    if max(down, up) < min_corr:
        return "none"
    return "down" if down >= up else "up"


def stitch(paths, min_overlap=40, max_overlap=0, threshold=0.8, downscale=8,
           trim_right=0):
    frames = [load_rgb(p) for p in paths]
    if not frames:
        raise SystemExit("no frames")

    acc = frames[0]
    frame_h, frame_w = acc.shape[:2]
    used = 1
    seam_scores = []
    stopped_reason = "end"

    for f in frames[1:]:
        if f.shape[0] != frame_h or f.shape[1] != frame_w:
            stopped_reason = "size-mismatch"
            break
        k, corr = best_overlap(
            gray(acc), gray(f),
            min_overlap=min_overlap, max_overlap=max_overlap,
            downscale=downscale, trim_right=trim_right,
        )
        # k >= frame height means nothing new was revealed.
        if k < min_overlap or corr < threshold or k >= f.shape[0] - 1:
            stopped_reason = "no-overlap"
            break
        acc = np.vstack([acc, f[k:]])
        seam_scores.append(round(corr, 4))
        used += 1

    return acc, used, seam_scores, stopped_reason


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("frames", nargs="+", help="frame image paths, top to bottom")
    ap.add_argument("--output", help="where to write the stitched PNG")
    ap.add_argument("--min-overlap", type=int, default=40)
    ap.add_argument("--max-overlap", type=int, default=0,
                    help="0 = auto (whole frame)")
    ap.add_argument("--threshold", type=float, default=0.8,
                    help="minimum ZNCC for an overlap to be accepted")
    ap.add_argument("--downscale", type=int, default=8,
                    help="(unused; kept for compatibility)")
    ap.add_argument("--trim-right", type=int, default=0,
                    help="ignore this many right-hand pixels when matching "
                         "(useful to ignore scrollbars)")
    ap.add_argument("--detect-dir", action="store_true",
                    help="only compare the first two frames and print the "
                         "scroll direction")
    args = ap.parse_args(argv)

    if args.detect_dir:
        if len(args.frames) < 2:
            print("none")
            return 0
        print(detect_direction(
            load_rgb(args.frames[0]), load_rgb(args.frames[1]),
            min_overlap=args.min_overlap, downscale=args.downscale,
        ))
        return 0

    if not args.output:
        ap.error("--output is required unless --detect-dir is used")

    acc, used, seams, reason = stitch(
        args.frames,
        min_overlap=args.min_overlap,
        max_overlap=args.max_overlap,
        threshold=args.threshold,
        downscale=args.downscale,
        trim_right=args.trim_right,
    )
    Image.fromarray(acc).save(args.output)
    print(json.dumps({
        "frames": len(args.frames),
        "used": used,
        "width": int(acc.shape[1]),
        "height": int(acc.shape[0]),
        "ok": used > 1,
        "reason": reason,
        "seams": seams,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
