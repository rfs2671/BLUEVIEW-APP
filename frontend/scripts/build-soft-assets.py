#!/usr/bin/env python3
"""Bakes the soft-silicone login surfaces and the raised logo into PNGs.

Run:  python3 scripts/build-soft-assets.py        (needs numpy and pillow)

Writes assets/soft/:
  key / keyp / field  x  light / dark  x  L, M, R  x  @1x, @2x, @3x
  logo_light / logo_dark  x  @1x, @2x, @3x

Everything is rendered ONCE at 3x with the height-field renderer in soft_lab/
(light from the top left, real theme colours: paper #ECEDE9 and navy #1C2B38),
then resampled to 1x and 2x so each density is cut on whole pixels. Each control is
three pieces: a left cap, a one-column middle that the app stretches, a right cap.
The caps carry a long straight run so the middle column is identical along its
length: stretching it cannot show a seam.
"""
import os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'soft_lab'))
import silicone_lab as sl
import mock_surfaces as ms

RENDER_S = 3
sl.S = RENDER_S
ms.S = RENDER_S
V = sl.VARIANTS[1]  # "Soft dish"
OUT = os.path.join(HERE, '..', 'assets', 'soft')
os.makedirs(OUT, exist_ok=True)

KEY = dict(body=60, margin=52, cap=138)    # cap = margin + 30 radius + 56 straight run
FIELD = dict(body=60, margin=28, cap=102)  # cap = margin + 30 radius + 44 straight run


def resample(im, scale):
    """Resize premultiplied so soft shadow edges do not get dark fringes."""
    w, h = im.size
    nw, nh = round(w * scale / RENDER_S), round(h * scale / RENDER_S)
    if (nw, nh) == (w, h):
        return im
    a = np.asarray(im).astype(np.float64) / 255.0
    pm = np.concatenate([a[..., :3] * a[..., 3:4], a[..., 3:4]], -1)
    chans = [Image.fromarray(pm[..., i].astype(np.float32), 'F').resize((nw, nh), Image.LANCZOS) for i in range(4)]
    pm = np.stack([np.asarray(c) for c in chans], -1)
    al = np.clip(pm[..., 3:4], 0, 1)
    rgb = np.where(al > 1e-6, pm[..., :3] / np.maximum(al, 1e-6), 0)
    out = np.concatenate([np.clip(rgb, 0, 1), al], -1)
    return Image.fromarray((out * 255 + 0.5).astype(np.uint8), 'RGBA')


def save_pieces(im, name, cap, margin):
    """Cut a full-width render into L (cap), M (1 dp column) and R (cap) for each density."""
    for scale, suffix in ((1, ''), (2, '@2x'), (3, '@3x')):
        r = resample(im, scale)
        c = cap * scale
        W = r.size[0]
        assert W == (2 * cap + 1) * scale, (name, W)
        r.crop((0, 0, c, r.size[1])).save(f'{OUT}/{name}_L{suffix}.png', optimize=True)
        r.crop((c, 0, c + scale, r.size[1])).save(f'{OUT}/{name}_M{suffix}.png', optimize=True)
        r.crop((W - c, 0, W, r.size[1])).save(f'{OUT}/{name}_R{suffix}.png', optimize=True)


def check_seamless(im, cap):
    a = np.asarray(im).astype(int)
    c = cap * RENDER_S
    d = max(np.abs(a[:, c - 3] - a[:, c + 1]).max(), np.abs(a[:, c + RENDER_S] - a[:, c + RENDER_S + 3]).max())
    return d


# ---- stretchable panels (cards, wells, small pills) ------------------------------------------
# A panel is cut in NINE pieces (four corners, four one-pixel edges, a one-pixel centre) so it can
# be any size, which is what lets a card grow when its content does (an opened list, a long
# address) without text ever running off the surface. The corners carry a straight run past the
# curve so the stretched edges line up with them. The smallest panel is 2 * (radius + run).
RAISED_SHADOW = [(-5, -5, 6, 'hi', 0.8), (0, 4, 7, 'lo', 0.16), (6, 9, 10, 'lo', 0.26)]
PANELS = {
    # name: radius, margin, run, edge (width of the rounded rise), raised?
    'card': dict(r=20, m=32, run=20, E=22, raised=True),
    'well': dict(r=26, m=28, run=22, E=24, raised=False),
    'pill': dict(r=22, m=32, run=22, E=22, raised=True, h=44),  # three-piece, fixed height
}


def panel_image(tn, spec, w, h):
    th = sl.THEME[tn]; sl._theme_name = tn
    if not spec['raised']:
        return ms.field_img(tn, V, w, h, spec['r'], m=spec['m'])
    d, x, y = ms.rbox(w, h, spec['r'], spec['m'])
    mask = np.clip(.5 - d * RENDER_S, 0, 1)
    img = np.zeros(mask.shape + (4,))
    for dx, dy, sg, kind, a in RAISED_SHADOW:
        img = sl.cast(img, mask, dx, dy, sg, th['hi'] if kind == 'hi' else th['lo'], a * (th['hia'] if kind == 'hi' else V['shadow_gain'][tn]))
    t = np.clip(-d / spec['E'], 0, 1); p = V['key']['p']
    hgt = V['key']['h0'] * (1 - (1 - t) ** p) ** (1 / p)
    return ms.finish(sl.over_img(img, sl.lighting(hgt, th, V), mask))


def save_nine(tn, name, spec):
    C = spec['m'] + spec['r'] + spec['run']              # corner size in dp
    body = 2 * (spec['r'] + spec['run']) + 1              # body size that leaves a 1 dp middle
    im = panel_image(tn, spec, body, body)
    a = np.asarray(im).astype(int)
    c = C * RENDER_S
    seam = max(np.abs(a[:, c - 3] - a[:, c + 1]).max(), np.abs(a[c - 3, :] - a[c + 1, :]).max())
    print(name, tn, im.size, 'seam delta', seam)
    for scale, suffix in ((1, ''), (2, '@2x'), (3, '@3x')):
        r = resample(im, scale); k = C * scale; W = r.size[0]
        assert W == (2 * C + 1) * scale
        xs = {'l': (0, k), 'c': (k, k + scale), 'r': (W - k, W)}
        for ry, (y0, y1) in (('t', xs['l']), ('m', xs['c']), ('b', xs['r'])):
            for cx, (x0, x1) in (('l', xs['l']), ('c', xs['c']), ('r', xs['r'])):
                r.crop((x0, y0, x1, y1)).save(f'{OUT}/{name}_{tn}_{ry}{cx}{suffix}.png', optimize=True)


def save_pill(tn, spec):
    C = spec['m'] + spec['r'] + spec['run']
    w = 2 * (C - spec['m']) + 1
    im = panel_image(tn, spec, w, spec['h'])
    save_pieces(im, f'pill_{tn}', C, spec['m'])


def logo(theme):
    """The logo, raised from the surface and lit like the keys. Same 2103x1080 canvas as the
    entrance animation, so the particles land exactly on it."""
    W_DP, H_DP = 389, 200  # the box the login screen draws it in (contain)
    src = Image.open(os.path.join(HERE, '..', 'assets', 'logo-header-light.png')).convert('RGBA')
    w, h = W_DP * RENDER_S, H_DP * RENDER_S
    a = np.asarray(src.getchannel('A').resize((w, h), Image.LANCZOS)).astype(float) / 255.0
    th = dict(sl.THEME[theme])
    if theme == 'light':
        th.update(base=(38, 57, 72), lit=(132, 160, 182), dark=(8, 15, 22))
        kd = 1.5
    else:
        th.update(base=(236, 237, 233), lit=(255, 255, 255), dark=(150, 153, 141))
        kd = 1.3
    Vl = dict(V); Vl['kd'] = kd
    soft = sl.blur(a, 2.6 * RENDER_S)
    prof = np.clip(soft * 1.5, 0, 1); prof = prof * prof * (3 - 2 * prof)
    hgt = 6.0 * prof
    sh = sl.THEME[theme]
    mask = np.clip(a, 0, 1)
    img = np.zeros(mask.shape + (4,))
    gain = 1.0 if theme == 'light' else 1.6
    img = sl.cast(img, mask, -4, -4, 5, sh['hi'], 0.85 * sh['hia'])
    img = sl.cast(img, mask, 0, 2, 2.5, sh['lo'], 0.22 * gain)
    img = sl.cast(img, mask, 6, 9, 9, sh['lo'], 0.30 * gain)
    rgb = sl.lighting(hgt, th, Vl, spec=0.06)
    return ms.finish(sl.over_img(img, rgb, mask))


def main():
    for tn in ('light', 'dark'):
        k = ms.key_img(tn, V, 2 * (KEY['cap'] - KEY['margin']) + 1, KEY['body'], m=KEY['margin'])
        kp = ms.key_img(tn, V, 2 * (KEY['cap'] - KEY['margin']) + 1, KEY['body'], pressed=True, m=KEY['margin'])
        f = ms.field_img(tn, V, 2 * (FIELD['cap'] - FIELD['margin']) + 1, FIELD['body'], FIELD['body'] // 2, m=FIELD['margin'])
        for nm, im, d in ((f'key_{tn}', k, KEY), (f'keyp_{tn}', kp, KEY), (f'field_{tn}', f, FIELD)):
            print(nm, im.size, 'seam delta', check_seamless(im, d['cap']))
            save_pieces(im, nm, d['cap'], d['margin'])
        save_nine(tn, 'card', PANELS['card']); save_nine(tn, 'well', PANELS['well']); save_pill(tn, PANELS['pill'])
        lg = logo(tn)
        for scale, suffix in ((1, ''), (2, '@2x'), (3, '@3x')):
            resample(lg, scale).save(f'{OUT}/logo_{tn}{suffix}.png', optimize=True)
        print('logo', tn, lg.size)


if __name__ == '__main__':
    main()
