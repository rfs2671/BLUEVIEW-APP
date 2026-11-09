#!/usr/bin/env python3
"""
Renders the soft-silicone surfaces used by the login and register screens
(src/components/SoftSilicone.jsx) as images, so every device draws exactly the
same thing. React Native cannot draw inner shadows or stacked shadows, and
iPhone and Android each draw single shadows differently, so the look is baked
here once instead of being computed on the phone.

Each surface is a capsule cut into three pieces (left cap, one-column middle,
right cap) so it stretches to any width without distortion:
    assets/soft/<surface>_<theme>_{L,M,R}.png

    key     the raised Sign In key
    keyp    the same key pressed in
    field   the pressed-in dish a text field sits in

Colours come from the app's own palette (src/styles/theme.js): the surface is
the screen background, paper #ECEDE9 (light) or navy #1C2B38 (dark); the light
and dark shadows are lighter and darker versions of it. Light comes from the
top left.

Run:  python3 scripts/build-soft-assets.py
Needs numpy and Pillow.
"""
import os
import numpy as np
from PIL import Image

S = 2                      # pixels per dp (set per output density below)
OUT = os.path.join(os.path.dirname(__file__), '..', 'assets', 'soft')

# ---------------------------------------------------------------- geometry
KEY_H, KEY_M = 60, 52      # key height and the room around it for its shadow (dp)
FIELD_H, FIELD_M = 62, 30     # the field is a raised silicone wall around a deep dish
WALL = 8                       # thickness of that wall (dp)
KEY_EXTRA, FIELD_EXTRA = 48, 24   # straight run kept in each cap beyond the semicircle (the key's long shadow needs more)


def blur(a, sigma_px):
    """Gaussian blur of a 2-D float array (separable, zero padded)."""
    if sigma_px < 0.3:
        return a
    r = int(np.ceil(3 * sigma_px))
    x = np.arange(-r, r + 1)
    k = np.exp(-(x ** 2) / (2 * sigma_px ** 2))
    k /= k.sum()
    p = np.pad(a, ((r, r), (r, r)))
    tmp = np.apply_along_axis(lambda m: np.convolve(m, k, mode='valid'), 1, p)
    return np.apply_along_axis(lambda m: np.convolve(m, k, mode='valid'), 0, tmp)


def shift(a, dx_px, dy_px):
    out = np.zeros_like(a)
    h, w = a.shape
    xs, xd = (0, dx_px) if dx_px >= 0 else (-dx_px, 0)
    ys, yd = (0, dy_px) if dy_px >= 0 else (-dy_px, 0)
    ww, hh = w - abs(dx_px), h - abs(dy_px)
    out[yd:yd + hh, xd:xd + ww] = a[ys:ys + hh, xs:xs + ww]
    return out


def capsule(w_dp, h_dp, margin, height):
    """Anti-aliased capsule mask and signed distance (dp, negative inside)."""
    W, H = int((w_dp + 2 * margin) * S), int((height + 2 * margin) * S)
    ys, xs = np.mgrid[0:H, 0:W]
    x = (xs + 0.5) / S
    y = (ys + 0.5) / S
    r = height / 2
    x0, x1 = margin + r, margin + w_dp - r
    cy = margin + height / 2
    px = np.clip(x, x0, x1)
    d = np.hypot(x - px, y - cy) - r
    return np.clip(0.5 - d * S, 0, 1), d, x, y


def over(dst, rgb, alpha):
    """Composite a flat colour with per-pixel alpha over an RGBA float image."""
    a = np.clip(alpha, 0, 1)[..., None]
    da = dst[..., 3:4]
    oa = a + da * (1 - a)
    safe = np.where(oa > 1e-6, oa, 1)
    orgb = (np.array(rgb, float) * a + dst[..., :3] * da * (1 - a)) / safe
    return np.concatenate([orgb, oa], axis=-1)


def over_img(dst, rgb_img, alpha):
    a = np.clip(alpha, 0, 1)[..., None]
    da = dst[..., 3:4]
    oa = a + da * (1 - a)
    safe = np.where(oa > 1e-6, oa, 1)
    orgb = (rgb_img * a + dst[..., :3] * da * (1 - a)) / safe
    return np.concatenate([orgb, oa], axis=-1)


def inset(mask, dx, dy, sigma, rgb, alpha, img):
    """CSS-style inset shadow, clipped to the shape."""
    inv = 1 - mask
    sh = blur(shift(inv, int(round(dx * S)), int(round(dy * S))), sigma * S)
    return over(img, rgb, np.clip(sh, 0, 1) * mask * alpha)


def outer(mask, dx, dy, sigma, rgb, alpha, img):
    sh = blur(shift(mask, int(round(dx * S)), int(round(dy * S))), sigma * S)
    return over(img, rgb, sh * alpha)


def ring(d, rgb, alpha, img):
    """A one-dp line just inside the edge."""
    r = np.clip(0.5 - (np.abs(d + 0.5) - 0.5) * S, 0, 1)
    return over(img, rgb, r * alpha)


def hexrgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lerp(a, b, t):
    return np.array(a, float) + (np.array(b, float) - np.array(a, float)) * t[..., None]


# ----------------------------------------------------------------- surfaces
THEMES = {
    'light': dict(
        key_top='#F8F9F6', key_bottom='#DCDED8',
        hi=(255, 255, 255), lo=(124, 128, 114),
        edge=((255, 255, 255), 0.95),
        key_outer=[(-12, -12, 13, 'hi', 0.95), (14, 18, 16, 'lo', 0.46)],
        key_in=[(1, 1, 1, 'hi', 0.95), (-3, -4, 3.5, 'lo', 0.22)],
        keyp_in=[(6, 7, 6.5, 'lo', 0.40), (-5, -6, 5.5, 'hi', 0.90)],
        f_outer=[(-5, -5, 6, (255, 255, 255), 0.90), (7, 9, 9, (124, 128, 114), 0.40)],
        f_wall=((247, 248, 245), (222, 224, 218)),
        f_wall_in=[(1.5, 1.5, 1.5, (255, 255, 255), 0.95), (-3, -4, 4, (124, 128, 114), 0.22)],
        f_edge=((255, 255, 255), 0.90),
        f_floor=((206, 209, 201), (238, 239, 235)),
        f_dish_in=[(9, 10, 10, (124, 128, 114), 0.46), (-6, -7, 7, (255, 255, 255), 0.92), (0, 0, 6, (124, 128, 114), 0.09), (1, 1, 1.2, (110, 114, 102), 0.24)],
    ),
    'dark': dict(
        key_top='#2C4050', key_bottom='#1F2F3C',
        hi=(255, 255, 255), lo=(2, 8, 12),
        edge=((255, 255, 255), 0.14),
        key_outer=[(-9, -9, 10, 'hi', 0.05), (14, 18, 15, 'lo', 0.80)],
        key_in=[(1, 1, 0.5, 'hi', 0.13), (-3, -4, 3.5, (0, 0, 0), 0.34)],
        keyp_in=[(6, 7, 6.5, 'lo', 0.72), (-5, -6, 5.5, 'hi', 0.05)],
        f_outer=[(-5, -5, 6, (255, 255, 255), 0.05), (7, 9, 9, (2, 8, 12), 0.78)],
        f_wall=((46, 66, 82), (35, 54, 68)),
        f_wall_in=[(1.5, 1.5, 1, (255, 255, 255), 0.13), (-3, -4, 4, (0, 0, 0), 0.32)],
        f_edge=((255, 255, 255), 0.12),
        f_floor=((13, 21, 28), (33, 48, 60)),
        f_dish_in=[(9, 10, 9, (0, 0, 0), 0.85), (-6, -7, 7, (255, 255, 255), 0.07), (0, 0, 6, (0, 0, 0), 0.20), (1, 1, 1.2, (0, 0, 0), 0.40)],
    ),
}


def pick(c, th):
    return th[c] if isinstance(c, str) else c


def render_key(th, pressed):
    cap = KEY_H / 2 + KEY_EXTRA
    w = 2 * cap + 60
    mask, d, x, y = capsule(w, KEY_H, KEY_M, KEY_H)
    img = np.zeros(mask.shape + (4,))
    if not pressed:
        for dx, dy, sg, c, a in th['key_outer']:
            img = outer(mask, dx, dy, sg, pick(c, th), a, img)
    ty = np.clip((y - KEY_M) / KEY_H, 0, 1)
    top, bot = hexrgb(th['key_top']), hexrgb(th['key_bottom'])
    if pressed:
        top, bot = bot, top
    body = lerp(top, bot, ty)
    img = over_img(img, body, mask)
    ins = th['keyp_in'] if pressed else th['key_in']
    for dx, dy, sg, c, a in ins:
        img = inset(mask, dx, dy, sg, pick(c, th), a, img)
    img = ring(d, th['edge'][0], th['edge'][1], img)
    return img, w, KEY_M, KEY_H


def render_field(th):
    """A raised silicone wall around a deep dish: thick, plush, like a keywave key pressed in."""
    cap = FIELD_H / 2 + FIELD_EXTRA
    w = 2 * cap + 40
    outer_mask, d_o, x, y = capsule(w, FIELD_H, FIELD_M, FIELD_H)
    inner_mask, d_i, _, _ = capsule(w - 2 * WALL, FIELD_H - 2 * WALL, FIELD_M + WALL, FIELD_H - 2 * WALL)
    img = np.zeros(outer_mask.shape + (4,))
    # 1. the wall casts its own soft shadows
    for dx, dy, sg, c, a in th['f_outer']:
        img = outer(outer_mask, dx, dy, sg, c, a, img)
    # 2. the wall itself, lit from the top left
    ty = np.clip((y - FIELD_M) / FIELD_H, 0, 1)
    img = over_img(img, lerp(th['f_wall'][0], th['f_wall'][1], ty), outer_mask)
    for dx, dy, sg, c, a in th['f_wall_in']:
        img = inset(outer_mask, dx, dy, sg, c, a, img)
    img = ring(d_o, th['f_edge'][0], th['f_edge'][1], img)
    # 3. the dish floor: darker at the top left, easing toward the bottom right; kept constant in the
    #    straight middle so the stretched slice joins the caps without a seam
    xs = x - FIELD_M
    tx = np.where(xs < cap, np.clip(xs / cap, 0, 1) * 0.5,
                  np.where(xs > w - cap, 0.5 + np.clip((xs - (w - cap)) / cap, 0, 1) * 0.5, 0.5))
    tyi = np.clip((y - FIELD_M - WALL) / (FIELD_H - 2 * WALL), 0, 1)
    t = 0.6 * tx + 0.4 * tyi
    img = over_img(img, lerp(th['f_floor'][0], th['f_floor'][1], t), inner_mask)
    # 4. the dish's inner shadows: this is where the depth comes from
    for dx, dy, sg, c, a in th['f_dish_in']:
        img = inset(inner_mask, dx, dy, sg, c, a, img)
    return img, w, FIELD_M, FIELD_H


def save_slices(img, w, margin, height, name, extra, sfx=''):
    cap = height / 2 + extra
    lc = int(round((margin + cap) * S))
    full_w = img.shape[1]
    rgb = np.clip(img[..., :3] / 255.0, 0, 1)          # colours are carried as 0..255, alpha as 0..1
    alpha = np.clip(img[..., 3:4], 0, 1)
    arr = (np.concatenate([rgb, alpha], axis=-1) * 255 + 0.5).astype(np.uint8)
    Image.fromarray(arr[:, :lc], 'RGBA').save(os.path.join(OUT, name + '_L' + sfx + '.png'), optimize=True)
    Image.fromarray(arr[:, full_w - lc:], 'RGBA').save(os.path.join(OUT, name + '_R' + sfx + '.png'), optimize=True)
    mid = full_w // 2
    Image.fromarray(arr[:, mid:mid + S], 'RGBA').save(os.path.join(OUT, name + '_M' + sfx + '.png'), optimize=True)
    return lc / S, arr.shape[0] / S


def suffix(density):
    return '' if density == 1 else '@%dx' % density


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    info = {}
    # One set per screen density (1x, 2x, 3x). React Native picks the one that matches the device,
    # so each piece is drawn pixel for pixel, with no resampling to soften its edges.
    for density in (1, 2, 3):
        S = density
        for theme, th in THEMES.items():
            for name, args in (('key', (th, False)), ('keyp', (th, True))):
                img, w, m, h = render_key(*args)
                info[f'{name}_{theme}'] = save_slices(img, w, m, h, f'{name}_{theme}', KEY_EXTRA, suffix(density))
            img, w, m, h = render_field(th)
            info[f'field_{theme}'] = save_slices(img, w, m, h, f'field_{theme}', FIELD_EXTRA, suffix(density))
    for k, v in info.items():
        print(k, 'cap width dp %.1f, height dp %.1f' % v)
