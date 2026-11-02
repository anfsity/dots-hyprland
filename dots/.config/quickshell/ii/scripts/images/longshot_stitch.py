#!/usr/bin/env python3
"""Register vertical screen captures and join them without resampling the text.

Matching uses FFT proposals from independent image strips, then checks the
entire overlap in tiles. Uncertain/repetitive matches are rejected. A narrow
minimum-cost seam chooses original pixels, rather than blurring glyphs.
"""

import argparse
from dataclasses import dataclass
import json
import sys

import numpy as np
from PIL import Image


def load_rgb(path):
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)


def gray(image):
    if image.ndim == 2:
        return image.astype(np.float32, copy=False)
    return (image[..., 0].astype(np.float32) * np.float32(0.299)
            + image[..., 1].astype(np.float32) * np.float32(0.587)
            + image[..., 2].astype(np.float32) * np.float32(0.114))


def _zncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    energy = float(np.sum(a * a) * np.sum(b * b))
    return float(np.clip(np.sum(a * b) / np.sqrt(energy), -1, 1)) if energy > 1e-6 else 0.0


def _small(image, width=192):
    # Area averaging retains thin text that column subsampling would miss.
    if image.shape[1] <= width:
        return image
    return np.asarray(Image.fromarray(image).resize(
        (width, image.shape[0]), Image.Resampling.BOX), dtype=np.float32)


def _fixed_edges(a, b):
    """Find stationary edge bands; these restrict matching/seams, not output."""
    static = np.quantile(np.abs(a - b), 0.8, axis=1) < 2.5
    limit = min(len(static) // 4, 200)

    def edge(rows):
        for index in range(limit):
            if np.count_nonzero(~rows[index:index + 6]) >= 3:
                return index + int(np.flatnonzero(~rows[index:index + 6])[0])
        return limit

    return edge(static), edge(static[::-1])


def _proposals(a, b, min_overlap):
    """Normalized linear cross correlations for several horizontal strips."""
    height, width = a.shape
    shifts = np.arange(-height + min_overlap, height - min_overlap + 1)
    if not len(shifts):
        return [0]
    nfft = 1 << (2 * height - 1).bit_length()
    # Vertical derivatives suppress flat backgrounds and stationary sidebars.
    a = np.gradient(a, axis=0)
    b = np.gradient(b, axis=0)
    curves = []
    candidates = {0}
    for columns in np.array_split(np.arange(width), min(5, max(1, width // 24))):
        x, y = a[:, columns], b[:, columns]
        if min(float(np.std(x)), float(np.std(y))) < 0.3:
            continue
        spectrum = np.fft.rfft(x, n=nfft, axis=0) * np.conj(np.fft.rfft(y, n=nfft, axis=0))
        numerator = np.fft.irfft(spectrum, n=nfft, axis=0).sum(axis=1)[shifts % nfft]
        ex = np.r_[0.0, np.cumsum(np.sum(x * x, axis=1), dtype=np.float64)]
        ey = np.r_[0.0, np.cumsum(np.sum(y * y, axis=1), dtype=np.float64)]
        ax, bx = np.maximum(shifts, 0), np.maximum(-shifts, 0)
        count = height - np.abs(shifts)
        denominator = np.sqrt((ex[ax + count] - ex[ax]) * (ey[bx + count] - ey[bx]))
        curve = numerator / np.maximum(denominator, 1e-6)
        curves.append(curve)
        for sign in (-1, 1):
            indices = np.flatnonzero(shifts * sign > 0)
            for index in sorted(indices, key=lambda i: curve[i], reverse=True)[:3]:
                candidates.add(int(shifts[index]))
    if curves:
        curve = np.median(curves, axis=0)
        peaks = np.flatnonzero((curve >= np.r_[-np.inf, curve[:-1]])
                               & (curve >= np.r_[curve[1:], -np.inf]))
        for index in sorted(peaks, key=lambda i: curve[i], reverse=True)[:12]:
            candidates.add(int(shifts[index]))
    return sorted(candidates)


def _verify(a, b, shift):
    count = len(a) - abs(shift)
    if count < 8:
        return -1.0, 0.0
    x = a[max(0, shift):max(0, shift) + count]
    y = b[max(0, -shift):max(0, -shift) + count]
    scores = []
    for rows in np.array_split(np.arange(count), min(3, max(1, count // 24))):
        for columns in np.array_split(np.arange(a.shape[1]), min(5, max(1, a.shape[1] // 24))):
            left, right = x[np.ix_(rows, columns)], y[np.ix_(rows, columns)]
            if min(float(left.std()), float(right.std())) < 1.0:
                continue
            luminance = _zncc(left, right)
            edges = _zncc(np.diff(left, axis=0), np.diff(right, axis=0))
            scores.append(0.55 * luminance + 0.45 * edges)
    if not scores:
        return -1.0, 0.0
    scores = np.asarray(scores)
    # Median tolerates a cursor or animation; the mean still penalizes mismatched
    # unique content in an otherwise repetitive page.
    return float(0.65 * np.median(scores) + 0.35 * np.mean(scores)), float(np.mean(scores > 0.65))


def _alignment_error(a, b, shift):
    count = len(a) - abs(shift)
    x = a[max(0, shift):max(0, shift) + count]
    y = b[max(0, -shift):max(0, -shift) + count]
    x = (x - x.mean()) / max(float(x.std()), 1.0)
    y = (y - y.mean()) / max(float(y.std()), 1.0)
    # Contrast-normalized residual distinguishes line numbers/unique glyphs
    # from a similar repeated paragraph. Clipping limits animated outliers.
    return float(np.minimum(np.abs(x - y), 2).mean())


@dataclass(frozen=True)
class Alignment:
    shift: int = 0
    confidence: float = 0.0
    status: str = "no-overlap"
    fixed_top: int = 0
    fixed_bottom: int = 0


def match_scroll(before, after, min_overlap=40, max_overlap=0, threshold=0.8,
                 trim_right=0, auto_trim=True):
    a, b = gray(before), gray(after)
    if a.shape != b.shape:
        raise ValueError("The capture region changed size")
    if min(a.shape) < 8:
        return Alignment()
    if float(np.mean(np.abs(a - b))) < 0.15:
        return Alignment(confidence=1.0, status="unchanged")
    right = a.shape[1] - min(trim_right, a.shape[1] - 8)
    # Ignore the scrollbar by default, but preserve every output column.
    if not trim_right and right >= 80:
        right -= max(2, right // 50)
    a, b = _small(a[:, :right]), _small(b[:, :right])
    top, bottom = _fixed_edges(a, b) if auto_trim else (0, 0)
    stop = len(a) - bottom
    a, b = a[top:stop], b[top:stop]
    if len(a) < min_overlap + 4:
        return Alignment(fixed_top=top, fixed_bottom=bottom)
    proposals = _proposals(a, b, min_overlap)
    ranked = []
    for shift in proposals:
        if max_overlap and shift and len(a) - abs(shift) > max_overlap:
            continue
        score, support = _verify(a, b, shift)
        ranked.append((score, support, shift))
    ranked.sort(reverse=True)
    if not ranked:
        return Alignment(fixed_top=top, fixed_bottom=bottom)
    score, support, shift = ranked[0]
    if score < threshold or support < 0.6:
        return Alignment(confidence=max(0.0, score), fixed_top=top, fixed_bottom=bottom)
    if shift == 0:
        return Alignment(confidence=score, status="unchanged", fixed_top=top, fixed_bottom=bottom)
    rivals = [item for item in ranked[1:] if abs(item[2] - shift) > 3
              and item[0] >= score - 0.025 and item[1] >= 0.6]
    if rivals:
        error = _alignment_error(a, b, shift)
        if any(error + 0.002 >= _alignment_error(a, b, rival[2]) * 0.65 for rival in rivals):
            return Alignment(confidence=score, status="ambiguous", fixed_top=top, fixed_bottom=bottom)
    return Alignment(shift, min(1.0, score), "added" if shift > 0 else "backtracking", top, bottom)


def seam_path(before, after, shift, top=0, bottom=0, minimum=0):
    """A left-to-right minimum-cost cut, constrained to matching content.

    The cost avoids strong text edges. No feathering or geometric resampling is
    applied to the saved pixels, so letters stay sharp even at fractional scale.
    """
    low = max(top, minimum - shift, 0)
    high = len(before) - bottom - shift - 1
    if high < low:
        raise ValueError("Not enough overlap for a continuous seam")
    # Choose the neighborhood on a narrow descriptor. Only the final 33-row
    # search band is expanded to full width, including on 4K monitors.
    step = max(1, before.shape[1] // 192)
    a, b = gray(before[:, ::step]), gray(after[:, ::step])
    row_cost = np.mean(np.abs(a[shift + low:shift + high + 1] - b[low:high + 1]), axis=1)
    edge = np.abs(np.diff(b, axis=0, prepend=b[:1]))
    row_cost += np.mean(edge[low:high + 1], axis=1) * 0.4
    # Prefer a central cut when many white rows have equal cost.
    row_cost += np.abs(np.arange(len(row_cost)) - (len(row_cost) - 1) / 2) * 0.015
    center = low + int(np.argmin(row_cost))
    band_low, band_high = max(low, center - 16), min(high + 1, center + 17)
    a = before[shift + band_low:shift + band_high].astype(np.float32)
    b = after[band_low:band_high].astype(np.float32)
    cost = np.mean(np.abs(a - b), axis=2)
    luminance = gray(after[max(0, band_low - 1):band_high])
    edge = np.abs(np.diff(luminance, axis=0, prepend=luminance[:1]))[-len(cost):]
    cost += edge * 0.4
    energy = cost[:, 0].copy()
    parents = np.empty(cost.shape, dtype=np.int8)
    for column in range(1, cost.shape[1]):
        options = np.stack((np.r_[np.inf, energy[:-1]] + 0.5, energy,
                            np.r_[energy[1:], np.inf] + 0.5))
        choice = np.argmin(options, axis=0)
        parents[:, column] = choice.astype(np.int8) - 1
        energy = cost[:, column] + np.min(options, axis=0)
    path = np.empty(cost.shape[1], dtype=np.int32)
    path[-1] = int(np.argmin(energy))
    for column in range(len(path) - 1, 0, -1):
        path[column - 1] = path[column] + parents[path[column], column]
    return path + band_low


class ManualStitcher:
    """Keep finalized strips and a replaceable tail; never re-copy a tall image."""

    def __init__(self, first, min_overlap=40, max_overlap=0, threshold=0.8,
                 trim_right=0, max_pixels=64_000_000, auto_trim=True):
        self._tail = first.copy()
        self._tail_start = 0
        self._parts = []
        self._thumbs = []
        self._committed_height = 0
        self.frames = 1
        self.height, self.width = first.shape[:2]
        self.frame_height = self.height
        self.min_overlap, self.max_overlap = min_overlap, max_overlap
        self.threshold, self.trim_right = threshold, trim_right
        self.max_pixels, self.auto_trim = max_pixels, auto_trim
        self.last_match = Alignment(status="unchanged", confidence=1.0)
        self._preview_width = min(192, self.width)
        if self.height * self.width > max_pixels:
            raise ValueError("Capture region exceeds the image size limit")

    @property
    def image(self):
        return np.concatenate([*self._parts, self._tail[self._tail_start:]], axis=0)

    def _thumbnail(self, image, height):
        return np.asarray(Image.fromarray(image).resize(
            (self._preview_width, height), Image.Resampling.LANCZOS))

    def _append(self, image):
        if len(image):
            self._parts.append(image.copy())
            scale = self._preview_width / self.width
            height = round((self._committed_height + len(image)) * scale) - round(self._committed_height * scale)
            self._committed_height += len(image)
            if height > 0:
                self._thumbs.append(self._thumbnail(image, height))

    def preview(self):
        scale = self._preview_width / self.width
        tail_height = max(1, round(self.height * scale) - round(self._committed_height * scale))
        image = Image.fromarray(np.concatenate([
            *self._thumbs, self._thumbnail(self._tail[self._tail_start:], tail_height)], axis=0))
        image.thumbnail((192, 4096), Image.Resampling.LANCZOS)
        return image

    def add(self, frame):
        if frame.shape != self._tail.shape:
            raise ValueError("The capture region changed size")
        match = match_scroll(self._tail, frame, self.min_overlap, self.max_overlap,
                             self.threshold, self.trim_right, self.auto_trim)
        self.last_match = match
        if match.status != "added":
            return match.status
        if (self.height + match.shift) * self.width > self.max_pixels:
            return "limit"
        path = seam_path(self._tail, frame, match.shift, match.fixed_top,
                         match.fixed_bottom, self._tail_start)
        first, last = int(path.min()), int(path.max()) + 1
        self._append(self._tail[self._tail_start:match.shift + first])
        rows = np.arange(first, last)[:, None]
        band = np.where((rows < path[None, :])[:, :, None],
                        self._tail[match.shift + first:match.shift + last], frame[first:last])
        self._append(band)
        self._tail, self._tail_start = frame.copy(), last
        self.height += match.shift
        self.frames += 1
        return "added"


def best_overlap(acc_gray, new_gray, min_overlap=40, max_overlap=0, downscale=8, trim_right=0):
    """Compatibility API for callers that only need a downward overlap."""
    height = min(len(acc_gray), len(new_gray))
    result = match_scroll(acc_gray[-height:], new_gray[:height], min_overlap,
                          max_overlap, trim_right=trim_right)
    if result.status not in {"added", "unchanged"}:
        return 0, result.confidence
    return height - result.shift, result.confidence


def detect_direction(before, after, min_overlap=40, downscale=8, min_corr=0.5):
    if before.shape != after.shape:
        return "none"
    result = match_scroll(before, after, min_overlap, threshold=min_corr)
    return {"added": "down", "backtracking": "up"}.get(result.status, "none")


def stitch(paths, min_overlap=40, max_overlap=0, threshold=0.8, downscale=8, trim_right=0):
    if not paths:
        raise ValueError("No frames")
    stitcher = ManualStitcher(load_rgb(paths[0]), min_overlap, max_overlap, threshold, trim_right)
    scores, reason = [], "end"
    for path in paths[1:]:
        result = stitcher.add(load_rgb(path))
        if result == "added":
            scores.append(round(stitcher.last_match.confidence, 4))
        elif result not in {"unchanged", "backtracking"}:
            reason = result
            break
    return stitcher.image, stitcher.frames, scores, reason


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames", nargs="+")
    parser.add_argument("--output")
    parser.add_argument("--min-overlap", type=int, default=40)
    parser.add_argument("--max-overlap", type=int, default=0)
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--downscale", type=int, default=8, help="compatibility option")
    parser.add_argument("--trim-right", type=int, default=0)
    parser.add_argument("--detect-dir", action="store_true")
    args = parser.parse_args(argv)
    if args.detect_dir:
        print(detect_direction(load_rgb(args.frames[0]), load_rgb(args.frames[1]), args.min_overlap)
              if len(args.frames) > 1 else "none")
        return 0
    if not args.output:
        parser.error("--output is required")
    image, used, scores, reason = stitch(args.frames, args.min_overlap, args.max_overlap,
                                         args.threshold, args.downscale, args.trim_right)
    Image.fromarray(image).save(args.output)
    print(json.dumps({"frames": len(args.frames), "used": used, "width": image.shape[1],
                      "height": image.shape[0], "ok": used > 1, "reason": reason, "seams": scores}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
