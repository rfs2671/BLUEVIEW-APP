"""Deterministic enhancement for CP daily-log site photos.

CP photos arrive under-exposed, flat/hazy and soft: shot on a dirty phone lens
in poor interior light, then already downscaled client-side to 1280px wide at
JPEG q0.6 before upload. This module makes them presentable in the daily report
without inventing detail.

PIPELINE (order matters)
  1. EXIF transpose      — honour the camera's rotation flag before anything.
  2. Exposure stretch    — clip a small percentile off each end of the LUMA
                           histogram and rescale. Luma-based, not per-channel:
                           a per-channel stretch silently performs white
                           balance too, which would fight step 3 and make both
                           untunable. Keeping them orthogonal is deliberate.
  3. Bounded gray-world  — partial pull of each channel mean toward the global
                           mean. BOUNDED on purpose: full gray-world assumes
                           the average scene is neutral grey, but a tungsten-lit
                           wood-framed interior genuinely IS warm, and a full
                           correction neutralises that into grey — "corrected"
                           into looking wrong. See GRAY_WORLD_STRENGTH.
  4. CLAHE on LAB L only — the main win for dim interiors: local contrast
                           without touching a/b, so colour is preserved. Run
                           on L alone; CLAHE on RGB channels shifts hue.
  5. Unsharp mask        — recover softness. Modest radius/amount; the input is
                           already JPEG-compressed, so aggressive sharpening
                           amplifies block artefacts and rings edges.
  6. Encode ×2           — enhanced (long edge 1800, q85) and thumbnail
                           (long edge 400, q80) from the SAME enhanced array,
                           one decode, one enhancement pass.

DEPENDENCIES: numpy + Pillow only, both already in requirements. CLAHE is
implemented here in numpy (see _clahe_l_channel) rather than pulling in
opencv-python-headless, which measured 112 MB installed — for one function,
that is a bad trade in image size and in pip-install time on every CI run.
Pillow does RGB<->LAB natively, so the colour conversion needs no third party
either.

NOT AI. No upscaling, no generative fill, no hallucinated detail. Every step is
a deterministic point or local operator over pixels that were already in the
frame. The same input always produces the same output.
"""

from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass
from typing import Tuple

import numpy as np
from PIL import Image, ImageFilter, ImageOps

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════
# TUNING CONSTANTS
#
# THESE ARE STARTING VALUES AND HAVE NOT BEEN TUNED AGAINST REAL PHOTOS.
#
# They are textbook defaults plus judgement, calibrated against nothing. Three
# in particular decide whether output looks professional or looks processed:
#
#   CLAHE_CLIP_LIMIT — too high turns dim interiors into noisy, HDR-looking
#     mush and amplifies JPEG blocking in flat areas (sky, bare drywall). Too
#     low and a dark interior stays dark. Useful range roughly 1.5-3.0.
#
#   UNSHARP_AMOUNT — too high puts white halos on every high-contrast edge
#     (scaffold against sky, rebar against concrete), which reads as "cheaply
#     sharpened" and is worse than the original softness.
#
#   GRAY_WORLD_STRENGTH — 1.0 fully neutralises the scene's average colour.
#     On a warm interior that is usually WRONG: the warmth is real. Partial
#     correction removes the worst of a colour cast while leaving the scene
#     looking like the place the CP was standing in.
#
# Tune by running the pipeline over a real batch of CP photos — a dim interior,
# a hazy/flat exterior, a backlit shot, and one already well-exposed (which
# must come out looking essentially unchanged, NOT over-cooked). Judge on a
# phone screen, not a calibrated monitor: that is where the report is read.
# ══════════════════════════════════════════════════════════════════════════

# Fraction of the luma histogram clipped off EACH end before rescaling.
EXPOSURE_CLIP_PCT = 0.5

# How much of the full stretch to actually apply. 1.0 = normalise the frame to
# span 0-255; 0.0 = leave exposure alone.
#
# BOUNDED for the same reason gray-world is. A full stretch forces EVERY photo
# to span the full range, including one that legitimately has no deep shadows —
# a sunlit facade gets its black point dragged down, which darkens the whole
# frame and manufactures crushed shadows that were never in the scene. Measured
# on the four real CP photos: at 1.0 the well-exposed control lost 31 mean
# points and 2.2% of the frame went to black; at 0.35 it loses 20 and 0.2%,
# while the dark basement RECOVERS MORE shadow detail (44.2% -> 27.7% crushed,
# versus 39.2% at full strength) because CLAHE downstream is handed a less
# crushed histogram to work with.
EXPOSURE_STRENGTH = 0.5

# ── ADAPTIVE GATE ─────────────────────────────────────────────────────────
# Every strength below is multiplied by a per-photo "needs help" score in
# [0,1]. A well-exposed photo scores near zero and passes through essentially
# untouched; a dark one scores 1.0 and gets everything.
#
# Measured on the four real CP photos:
#   facade    mean 160  std 42  crushed  0%  -> score 0.17  (leave alone)
#   barricade mean 137  std 38  crushed  0%  -> score 0.32  (mild)
#   plywood   mean 138  std 31  crushed  0%  -> score 0.59  (moderate)
#   basement  mean  33  std 39  crushed 44%  -> score 1.00  (everything)
#
# The three terms answer three different questions, and are combined with max()
# not a sum: a photo needs help if it is TOO DARK, or has CRUSHED SHADOWS, or
# is FLAT — any one of those alone is enough, and summing them would double
# count a dark photo (which is usually also crushed).
GATE_TARGET_MEAN = 118.0     # midtone a correctly exposed frame sits near
GATE_DARK_KNEE = 70.0        # mean this far below target => full darkness need
GATE_FLAT_STD_GOOD = 40.0    # std at/above this is contrasty, not flat
GATE_FLAT_KNEE = 8.0         # std this far below "good" => full flatness need
GATE_CRUSH_REF = 0.20        # this fraction under luma 16 => full crush need
GATE_FLAT_WEIGHT = 0.7       # flatness alone should not trigger max treatment

# ── SHADOW LIFT ───────────────────────────────────────────────────────────
# CLAHE redistributes LOCAL contrast; it does not brighten. A basement at mean
# 33 stays a basement at mean 33 no matter how the local histogram is shuffled.
# This is the step that actually makes a dark photo readable.
#
# Implemented as a gamma curve on the RGB values: y = x**(1/gamma). Monotonic,
# fixes both endpoints (0->0, 255->255) so highlights cannot blow, and lifts
# the lower/mid range hardest — which is exactly the region that is unreadable.
SHADOW_LIFT_MAX_GAMMA = 2.4  # at gate 1.0; 1.0 = no lift

# ── DENOISE ───────────────────────────────────────────────────────────────
# Lifting shadows multiplies whatever was hiding in them: sensor noise and JPEG
# blocking. Applied ONLY where the lift was aggressive, and weighted per-pixel
# toward the dark regions that were actually lifted — bright, correctly-exposed
# areas keep their full texture.
DENOISE_MAX = 0.7            # blend weight at full lift, in the darkest pixels
DENOISE_SHADOW_CUTOFF = 0.45 # normalised luma above which no denoise is applied

# ── DEBLOCKING ────────────────────────────────────────────────────────────
# Many CP photos never pass through the app's camera: they arrive via WhatsApp
# from the CP's own camera roll, already heavily re-compressed. Lifting shadows
# on those amplifies JPEG's 8x8 block structure into visible tiles.
#
# The 3x3 median above is the WRONG tool for it. A median is built for
# impulse/speckle noise — isolated outlier pixels — and blocking is not that.
# Blocking is a STRUCTURED, PERIODIC step discontinuity at known coordinates:
# every 8th column and row. A median sees that step as legitimate local
# structure (it is consistent across the whole boundary, not an outlier) and
# preserves it, while softening the real texture either side. That is the worst
# of both outcomes, and it is what the earlier sheets showed.
#
# This filter instead exploits the one thing we know: WHERE the artefact is. It
# only touches pixels straddling an 8-aligned boundary, and only when the step
# there looks like an artefact rather than a real edge — small step, flat
# neighbourhood. A genuine edge that happens to fall on a block boundary has a
# large step and survives untouched.
#
# Removing a known compression artefact is not invention: the block edge was
# added by the encoder, it was never in the scene.
DEBLOCK_MAX = 1.0            # filter strength at full shadow lift
DEBLOCK_EDGE_THRESHOLD = 24.0  # luma step above this is a REAL edge, left alone

# CLAHE. clip limit is the contrast ceiling per tile, expressed as a multiple
# of the average bin count; tile grid is how local the adaptation is. The clip
# limit is INTERPOLATED by the gate between MIN (well-exposed, barely touched)
# and MAX (dark, aggressive).
# Driven by the FLATNESS term, not the composite score. Haze destroys LOCAL
# contrast while leaving the global range intact (the barricade's top band
# still spans p1=80..p99=213), so only CLAHE can recover it and the clip limit
# is the ceiling on how much it may. Measured: clip 2.19 -> 6.0 takes that
# band's std from 38.5 to 47.9, while a finer tile grid did nothing (38.5 at
# 8x8, 36.3 at 32x32 — slightly WORSE).
#
# Decoupling from the score also fixes the basement: it is dark, not flat, so
# it now gets a modest clip and the shadow lift does the work — which is what
# was amplifying its JPEG blocking.
CLAHE_CLIP_MIN = 1.1
CLAHE_CLIP_MAX = 3.5
CLAHE_TILE_GRID = (8, 8)

# Unsharp mask. PIL takes `percent` as an integer; UNSHARP_AMOUNT is a fraction
# and is converted below. threshold skips low-contrast areas so sensor noise
# and JPEG mosquito artefacts are not sharpened.
UNSHARP_RADIUS = 2.0
UNSHARP_AMOUNT = 0.3
UNSHARP_THRESHOLD = 3

# White balance bounds.
#   STRENGTH: 0.0 = no correction at all, 1.0 = full gray-world.
#   MAX_GAIN: hard ceiling on any single channel gain, so a legitimately
#             monochrome scene (grey concrete, night shot) cannot be tinted
#             violently by an extreme channel mean.
GRAY_WORLD_STRENGTH = 0.45
GRAY_WORLD_MAX_GAIN = 1.35

# Output encoding.
ENHANCED_MAX_EDGE = 1800
ENHANCED_QUALITY = 85
THUMB_MAX_EDGE = 400
THUMB_QUALITY = 80

# Refuse absurd inputs rather than OOM the worker.
MAX_INPUT_PIXELS = 50_000_000


@dataclass
class GateScore:
    """Why a photo scored the way it did. Logged so a bad result on a real
    jobsite photo can be diagnosed without re-running anything."""
    score: float
    dark: float
    crush: float
    flat: float
    mean: float
    std: float
    crushed_frac: float

    def __str__(self) -> str:
        return (f"score={self.score:.2f} (dark={self.dark:.2f} crush={self.crush:.2f} "
                f"flat={self.flat:.2f}) mean={self.mean:.1f} std={self.std:.1f} "
                f"crushed={self.crushed_frac * 100:.1f}%")


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def compute_gate(rgb: np.ndarray) -> GateScore:
    """How much help does this photo need, in [0,1]?

    Three independent questions, combined with max() rather than a sum: a photo
    needs work if it is too dark, OR has crushed shadows, OR is flat. Summing
    would double-count, since a dark photo is usually also a crushed one.
    """
    luma = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    mean = float(luma.mean())
    std = float(luma.std())
    crushed = float((luma < 16).mean())

    dark = _clamp01((GATE_TARGET_MEAN - mean) / GATE_DARK_KNEE)
    crush = _clamp01(crushed / GATE_CRUSH_REF)
    flat = _clamp01((GATE_FLAT_STD_GOOD - std) / GATE_FLAT_KNEE)

    score = max(dark, crush, GATE_FLAT_WEIGHT * flat)
    return GateScore(score, dark, crush, flat, mean, std, crushed)


def _shadow_lift(rgb: np.ndarray, amount: float) -> np.ndarray:
    """Gamma curve lifting the lower histogram. amount in [0,1].

    y = x**(1/gamma) on normalised values: monotonic, endpoints fixed (black
    stays black, white stays white), and the gain falls off toward the
    highlights — so a blown doorway does not get pushed further.
    """
    if amount <= 0.001:
        return rgb
    gamma = 1.0 + (SHADOW_LIFT_MAX_GAMMA - 1.0) * amount
    norm = np.clip(rgb, 0.0, 255.0) / 255.0
    return np.power(norm, 1.0 / gamma) * 255.0


def _deblock_jpeg(rgb_u8: np.ndarray, strength: float) -> np.ndarray:
    """Smooth across 8x8 JPEG block boundaries, and only there.

    For each boundary it inspects the four pixels straddling it (p1 p0 | q0 q1)
    and equalises part of the p0/q0 step. Two soft masks decide how much:

      * step mask — a large jump across the boundary is a REAL edge (a scaffold
        pole, a doorway) that happens to land on a block line. Left alone.
      * texture mask — if the neighbourhood either side is already busy, the
        step is detail rather than an artefact. Left alone.

    Both fall off smoothly, so nothing switches on or off abruptly between
    adjacent boundaries (which would itself be visible).
    """
    if strength <= 0.01:
        return rgb_u8

    out = rgb_u8.astype(np.float32).copy()
    h, w = out.shape[:2]
    luma = out.mean(axis=2)
    thr = DEBLOCK_EDGE_THRESHOLD

    # ── vertical boundaries: between column 8k-1 and 8k ──
    cols = np.arange(8, w - 1, 8)
    if cols.size:
        p1, p0 = luma[:, cols - 2], luma[:, cols - 1]
        q0, q1 = luma[:, cols], luma[:, cols + 1]
        step = q0 - p0
        tex = 0.5 * (np.abs(p1 - p0) + np.abs(q1 - q0))
        m = np.clip(1.0 - np.abs(step) / thr, 0.0, 1.0)
        m *= np.clip(1.0 - tex / thr, 0.0, 1.0)
        d = (0.25 * step * m * strength)[:, :, None]
        out[:, cols - 1, :] += d
        out[:, cols, :] -= d

    # ── horizontal boundaries: between row 8k-1 and 8k ──
    rows = np.arange(8, h - 1, 8)
    if rows.size:
        luma = out.mean(axis=2)          # recompute after the vertical pass
        p1, p0 = luma[rows - 2, :], luma[rows - 1, :]
        q0, q1 = luma[rows, :], luma[rows + 1, :]
        step = q0 - p0
        tex = 0.5 * (np.abs(p1 - p0) + np.abs(q1 - q0))
        m = np.clip(1.0 - np.abs(step) / thr, 0.0, 1.0)
        m *= np.clip(1.0 - tex / thr, 0.0, 1.0)
        d = (0.25 * step * m * strength)[:, :, None]
        out[rows - 1, :, :] += d
        out[rows, :, :] -= d

    return np.clip(out, 0.0, 255.0).astype(np.uint8)


def _denoise_shadows(rgb_u8: np.ndarray, amount: float) -> np.ndarray:
    """Median-blend the lifted shadows only.

    Weighted per pixel by how dark that pixel was: a lifted basement floor gets
    smoothed, a correctly-exposed wall in the same frame keeps its texture. A
    3x3 median is chosen over a blur because it kills isolated hot pixels and
    JPEG mosquito noise without softening edges the way a Gaussian would.
    """
    if amount <= 0.01:
        return rgb_u8
    med = np.asarray(
        Image.fromarray(rgb_u8).filter(ImageFilter.MedianFilter(size=3))
    ).astype(np.float32)
    base = rgb_u8.astype(np.float32)
    luma_n = base.mean(axis=2, keepdims=True) / 255.0
    shadow_mask = np.clip(1.0 - luma_n / DENOISE_SHADOW_CUTOFF, 0.0, 1.0)
    w = amount * shadow_mask
    return np.clip(base * (1.0 - w) + med * w, 0.0, 255.0).astype(np.uint8)


@dataclass
class EnhanceResult:
    enhanced_jpeg: bytes
    thumbnail_jpeg: bytes
    enhanced_size: Tuple[int, int]
    thumbnail_size: Tuple[int, int]
    elapsed_ms: int


def _exposure_stretch(rgb: np.ndarray, clip_pct: float) -> np.ndarray:
    """Percentile stretch driven by LUMA, applied uniformly to all channels.

    Uniform application is the point: it changes exposure without changing the
    colour balance, leaving white balance entirely to the next step.
    """
    luma = (0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2])
    lo = float(np.percentile(luma, clip_pct))
    hi = float(np.percentile(luma, 100.0 - clip_pct))
    if hi - lo < 1e-3:
        return rgb  # degenerate (blank/blown frame) — leave it alone
    return np.clip((rgb - lo) * (255.0 / (hi - lo)), 0.0, 255.0)


def _gray_world_white_balance(rgb: np.ndarray, strength: float) -> np.ndarray:
    """BOUNDED gray-world: pull each channel mean PART WAY toward the global
    mean, never all the way, and never past a hard per-channel gain ceiling.

    The exponent is the bound: gain**strength with strength<1 is a partial
    correction (strength 0 -> gain 1.0 -> no change; strength 1 -> full
    gray-world). This is what stops a warm tungsten interior being scrubbed
    to neutral grey.
    """
    means = rgb.reshape(-1, 3).mean(axis=0)
    if float(means.min()) < 1e-3:
        return rgb  # a fully empty channel — no meaningful correction
    target = float(means.mean())
    raw_gains = target / means
    gains = np.power(raw_gains, strength)
    gains = np.clip(gains, 1.0 / GRAY_WORLD_MAX_GAIN, GRAY_WORLD_MAX_GAIN)
    return np.clip(rgb * gains, 0.0, 255.0)


def _clahe_l_channel(l_chan: np.ndarray, clip_limit: float) -> np.ndarray:
    """Contrast Limited Adaptive Histogram Equalisation, numpy only.

    Standard CLAHE: split into a tile grid, build a clipped-and-redistributed
    CDF per tile, then bilinearly interpolate between the four surrounding tile
    mappings so tile boundaries do not show as seams.

    The clip-and-redistribute step is what separates CLAHE from plain adaptive
    equalisation: bins above the limit are truncated and the removed mass is
    spread evenly, which caps how much local contrast (and therefore noise) any
    one tile can gain.
    """
    h, w = l_chan.shape
    gy, gx = CLAHE_TILE_GRID
    th = int(np.ceil(h / gy))
    tw = int(np.ceil(w / gx))

    # Pad to a whole number of tiles; edge padding avoids inventing dark/light
    # borders that would pull the edge tiles' histograms.
    pad_h, pad_w = gy * th - h, gx * tw - w
    padded = np.pad(l_chan, ((0, pad_h), (0, pad_w)), mode="edge") if (pad_h or pad_w) else l_chan

    tiles = padded.reshape(gy, th, gx, tw).transpose(0, 2, 1, 3).reshape(gy, gx, th * tw)

    n_px = th * tw
    limit = max(1.0, clip_limit * n_px / 256.0)
    luts = np.empty((gy, gx, 256), dtype=np.float32)
    for i in range(gy):
        for j in range(gx):
            hist = np.bincount(tiles[i, j], minlength=256).astype(np.float32)
            excess = float(np.maximum(hist - limit, 0.0).sum())
            hist = np.minimum(hist, limit) + excess / 256.0
            cdf = np.cumsum(hist)
            span = float(cdf[-1] - cdf[0])
            luts[i, j] = ((cdf - cdf[0]) / span * 255.0) if span > 1e-6 else np.arange(256)

    # Bilinear blend between the four nearest tile CENTRES.
    ys = np.clip(np.arange(h, dtype=np.float32) / th - 0.5, 0, gy - 1)
    xs = np.clip(np.arange(w, dtype=np.float32) / tw - 0.5, 0, gx - 1)
    i0 = np.floor(ys).astype(np.int32)
    j0 = np.floor(xs).astype(np.int32)
    i1 = np.minimum(i0 + 1, gy - 1)
    j1 = np.minimum(j0 + 1, gx - 1)
    wy = (ys - i0)[:, None]
    wx = (xs - j0)[None, :]

    def _map(ii: np.ndarray, jj: np.ndarray) -> np.ndarray:
        return luts[ii[:, None], jj[None, :], l_chan]

    out = (
        _map(i0, j0) * (1.0 - wy) * (1.0 - wx)
        + _map(i0, j1) * (1.0 - wy) * wx
        + _map(i1, j0) * wy * (1.0 - wx)
        + _map(i1, j1) * wy * wx
    )
    return np.clip(out, 0, 255).astype(np.uint8)


def _clahe_on_lab_l(rgb_u8: np.ndarray, clip_limit: float) -> np.ndarray:
    """CLAHE applied to the L channel of LAB, a/b untouched.

    Pillow does the RGB<->LAB conversion natively.
    """
    lab = np.asarray(Image.fromarray(rgb_u8, mode="RGB").convert("LAB"))
    l_eq = _clahe_l_channel(lab[:, :, 0], clip_limit)
    merged = np.dstack([l_eq, lab[:, :, 1], lab[:, :, 2]])
    return np.asarray(Image.fromarray(merged, mode="LAB").convert("RGB"))


def _fit_long_edge(img: Image.Image, max_edge: int) -> Image.Image:
    """Downscale so the LONGEST edge is max_edge. Never upscales — upscaling
    would invent detail, which this pipeline does not do."""
    w, h = img.size
    longest = max(w, h)
    if longest <= max_edge:
        return img
    scale = max_edge / float(longest)
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def _encode_jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def enhance_photo(jpeg_bytes: bytes) -> EnhanceResult:
    """Run the full pipeline. Raises on any failure — callers MUST catch and
    fall back to the original; a failed enhancement is never fatal to a photo.
    """
    started = time.perf_counter()

    img = Image.open(io.BytesIO(jpeg_bytes))
    if (img.width * img.height) > MAX_INPUT_PIXELS:
        raise ValueError(f"input too large: {img.width}x{img.height}")

    img = ImageOps.exif_transpose(img)   # honour camera rotation first
    img = img.convert("RGB")

    arr = np.asarray(img).astype(np.float32)

    # ── the gate decides how hard everything below pushes ──
    gate = compute_gate(arr)
    g = gate.score
    logger.info("[photo-enhance] gate %s", gate)

    # 1. exposure — bounded AND gated
    stretched = _exposure_stretch(arr, EXPOSURE_CLIP_PCT)
    arr = arr + (EXPOSURE_STRENGTH * g) * (stretched - arr)

    # 2. shadow lift — driven by darkness/crush, NOT flatness. A flat but
    #    correctly-exposed photo needs contrast, not brightening.
    lift = max(gate.dark, gate.crush)
    arr = _shadow_lift(arr, lift)

    # 3. deblock — BEFORE CLAHE, which would otherwise sharpen block edges into
    #    hard tiles. Runs before the median too: a median smears the step and
    #    leaves the deblocker less signal to detect.
    arr_u8 = np.clip(arr, 0, 255).astype(np.uint8)
    arr_u8 = _deblock_jpeg(arr_u8, DEBLOCK_MAX * lift)

    # 4. denoise — the speckle the lift amplified, which deblocking does not touch
    arr_u8 = _denoise_shadows(arr_u8, DENOISE_MAX * lift)

    # 5. white balance — gated
    arr = _gray_world_white_balance(arr_u8.astype(np.float32), GRAY_WORLD_STRENGTH * g)

    # 6. CLAHE — clip limit driven by FLATNESS, not the composite score
    clip = CLAHE_CLIP_MIN + (CLAHE_CLIP_MAX - CLAHE_CLIP_MIN) * gate.flat
    arr = _clahe_on_lab_l(np.clip(arr, 0, 255).astype(np.uint8), clip)

    # 7. unsharp — gated
    enhanced = Image.fromarray(arr).filter(ImageFilter.UnsharpMask(
        radius=UNSHARP_RADIUS,
        percent=int(round(UNSHARP_AMOUNT * g * 100)),
        threshold=UNSHARP_THRESHOLD,
    ))

    # Both derivatives come from the SAME enhanced image — one decode, one
    # enhancement pass, two encodes.
    full = _fit_long_edge(enhanced, ENHANCED_MAX_EDGE)
    thumb = _fit_long_edge(enhanced, THUMB_MAX_EDGE)

    return EnhanceResult(
        enhanced_jpeg=_encode_jpeg(full, ENHANCED_QUALITY),
        thumbnail_jpeg=_encode_jpeg(thumb, THUMB_QUALITY),
        enhanced_size=full.size,
        thumbnail_size=thumb.size,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
