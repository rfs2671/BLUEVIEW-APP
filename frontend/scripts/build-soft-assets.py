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

# The straight run between two corners is a TILE of MID dp, drawn at its natural size and REPEATED (never
# stretched) by the app. Stretching a thin strip a long way drew wrongly on phones: nothing at all for a one-pixel
# strip, then faded edges, bands and hairlines for wider ones. Corners are never stretched and always drew right.
MID = 256
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
        r.save(f'{OUT}/{name}_full{suffix}.png', optimize=True)  # whole picture, for iPhone's cap-insets stretch
        assert W == (2 * cap + MID) * scale, (name, W)
        r.crop((0, 0, c, r.size[1])).save(f'{OUT}/{name}_L{suffix}.png', optimize=True)
        r.crop((c, 0, c + MID * scale, r.size[1])).save(f'{OUT}/{name}_M{suffix}.png', optimize=True)
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
    # slimmer panels for selectors, date bars and segmented tracks (smallest body 56dp)
    'slim': dict(r=18, m=32, run=10, E=18, raised=True),
    'slimw': dict(r=18, m=28, run=10, E=16, raised=False),
}
PEBBLE = dict(r=22, m=32, E=20, raised=True)  # the round 44dp button, one fixed-size picture


RAISED_SHADOW_PRESSED = [(-3, -3, 4, 'hi', 0.5), (0, 2, 4, 'lo', 0.20), (3, 5, 6, 'lo', 0.22)]


# A SELECTED card or button stays pressed in, like the text fields: the same bowl, a little shallower.
import copy
V_DENT = copy.deepcopy(V)
V_DENT['field'].update(depth=3.4, E=20)
# on the navy sidebar rail the shading is subtle, so its dent is deeper and the floor of the hollow a touch darker
V_DENT_RAIL = copy.deepcopy(V)
V_DENT_RAIL['field'].update(depth=5.6, E=18, floor_k=0.16, kd=1.5)


def panel_image(tn, spec, w, h, pressed=False, dent=False):
    th = sl.THEME[tn]; sl._theme_name = tn
    if dent:
        return ms.field_img(tn, V_DENT_RAIL if tn.startswith('rail') else V_DENT, w, h, spec['r'], m=spec['m'])
    if not spec['raised']:
        return ms.field_img(tn, V, w, h, spec['r'], m=spec['m'])
    d, x, y = ms.rbox(w, h, spec['r'], spec['m'])
    mask = np.clip(.5 - d * RENDER_S, 0, 1)
    img = np.zeros(mask.shape + (4,))
    for dx, dy, sg, kind, a in (RAISED_SHADOW_PRESSED if pressed else RAISED_SHADOW):
        img = sl.cast(img, mask, dx, dy, sg, th['hi'] if kind == 'hi' else th['lo'], a * (th['hia'] if kind == 'hi' else V['shadow_gain'][tn]))
    t = np.clip(-d / spec['E'], 0, 1); p = V['key']['p']
    hgt = V['key']['h0'] * (0.35 if pressed else 1.0) * (1 - (1 - t) ** p) ** (1 / p)
    return ms.finish(sl.over_img(img, sl.lighting(hgt, th, V), mask))


PLATEAU = {}


def save_nine(tn, name, spec, pressed=False, dent=False):
    C = spec['m'] + spec['r'] + spec['run']              # corner size in dp
    body = 2 * (spec['r'] + spec['run']) + MID            # body size that leaves a MID dp middle
    im = panel_image(tn, spec, body, body, pressed, dent)
    a = np.asarray(im).astype(int)
    c = C * RENDER_S
    seam = max(np.abs(a[:, c - 3] - a[:, c + 1]).max(), np.abs(a[c - 3, :] - a[c + 1, :]).max())
    print(name, tn, im.size, 'seam delta', seam)
    for scale, suffix in ((1, ''), (2, '@2x'), (3, '@3x')):
        r = resample(im, scale); k = C * scale; W = r.size[0]
        r.save(f'{OUT}/{name}_{tn}_full{suffix}.png', optimize=True)
        assert W == (2 * C + MID) * scale
        xs = {'l': (0, k), 'c': (k, k + MID * scale), 'r': (W - k, W)}
        mid = (k + MID * scale // 2); q = 2 * scale
        centre = r.crop((mid - q, mid - q, mid + q, mid + q))
        if scale == 1:
            PLATEAU.setdefault(tn, {})[name] = tuple(int(v) for v in np.asarray(centre)[q, q])
        for ry, (y0, y1) in (('t', xs['l']), ('m', xs['c']), ('b', xs['r'])):
            for cx, (x0, x1) in (('l', xs['l']), ('c', xs['c']), ('r', xs['r'])):
                if ry == 'm' and cx == 'c':
                    centre.save(f'{OUT}/{name}_{tn}_mc{suffix}.png', optimize=True)  # small: the app fills the middle with a colour
                else:
                    r.crop((x0, y0, x1, y1)).save(f'{OUT}/{name}_{tn}_{ry}{cx}{suffix}.png', optimize=True)


def save_pill(tn, spec, pressed=False, dent=False):
    C = spec['m'] + spec['r'] + spec['run']
    w = 2 * (C - spec['m']) + MID
    im = panel_image(tn, spec, w, spec['h'], pressed, dent)
    save_pieces(im, f'pill{"p" if pressed else ("d" if dent else "")}_{tn}', C, spec['m'])


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


def write_asset_map():
    """Writes src/components/softAssets.js: static require() paths for every asset, so the bundler finds each file."""
    req = lambda n: f"require('../../assets/soft/{n}.png')"
    L = ['// GENERATED by scripts/build-soft-assets.py. Do not edit by hand.', '// The soft-silicone surfaces, pre-rendered in the real light/dark colours at @1x/@2x/@3x.', '']
    themes = ('light', 'dark')
    L.append('// 3-piece capsules (key, field): left cap, repeating middle tile, right cap.')
    L.append('export const SOFT = {')
    for tn in themes:
        L.append(f'  {tn}: {{')
        for k in ('key', 'keyp', 'field'):
            L.append(f"    {k}: {{ L: {req(f'{k}_{tn}_L')}, M: {req(f'{k}_{tn}_M')}, R: {req(f'{k}_{tn}_R')} }},")
        L.append('  },')
    L.append('};')
    L.append('export const SOFT_DIMS = {')
    L.append(f"  key:   {{ body: {KEY['body']}, margin: {KEY['margin']}, capW: {KEY['cap']}, imgH: {KEY['body'] + 2 * KEY['margin']} }},")
    L.append(f"  keyp:  {{ body: {KEY['body']}, margin: {KEY['margin']}, capW: {KEY['cap']}, imgH: {KEY['body'] + 2 * KEY['margin']} }},")
    L.append(f"  field: {{ body: {FIELD['body']}, margin: {FIELD['margin']}, capW: {FIELD['cap']}, imgH: {FIELD['body'] + 2 * FIELD['margin']} }},")
    L.append('};')
    L.append('')
    L.append('export const SOFT_LOGO = {')
    for tn in themes:
        L.append(f"  {tn}: {req(f'logo_{tn}')},")
    L.append('};')
    L.append('')
    L.append('// Stretchable panels, nine pieces: four corners, four repeating tiles, a small centre (the app fills the middle with a colour).')
    kinds = ('card', 'cardp', 'cardd', 'well', 'slim', 'slimp', 'slimd', 'slimw')
    L.append('export const SOFT_PANEL = {')
    for tn in themes:
        L.append(f'  {tn}: {{')
        for k in kinds:
            parts = ', '.join(f"{a}{b}: {req(f'{k}_{tn}_{a}{b}')}" for a in 'tmb' for b in 'lcr')
            L.append(f'    {k}: {{ {parts} }},')
        L.append('  },')
    L.append('};')
    dims = {}
    for k, sp in (('card', 'card'), ('cardp', 'card'), ('cardd', 'card'), ('well', 'well'), ('slim', 'slim'), ('slimp', 'slim'), ('slimd', 'slim'), ('slimw', 'slimw')):
        P = PANELS[sp]; dims[k] = (P['m'], P['m'] + P['r'] + P['run'], P['r'], 2 * (P['r'] + P['run']))
    L.append('export const SOFT_PANEL_DIMS = {')
    for k, (m, c, r, mn) in dims.items():
        L.append(f'  {k}: {{ margin: {m}, corner: {c}, radius: {r}, min: {mn} }},')
    L.append('};')
    L.append('')
    L.append('// Whole pictures, for iPhone: one image stretched with fixed corners (cap insets).')
    L.append('export const SOFT_FULL = {')
    for tn in themes:
        items = [f"{k}: {req(f'{k}_{tn}_full')}" for k in ('key', 'keyp', 'field')]
        items += [f"{k}: {req(f'{k}_{tn}_full')}" for k in kinds]
        items += [f"{k}: {req(f'{k}_{tn}_full')}" for k in ('pill', 'pillp', 'pilld')]
        L.append(f"  {tn}: {{ {', '.join(items)} }},")
    for tn in ('raild', 'raill'):
        items = [f"{k}: {req(f'{k}_{tn}_full')}" for k in ('pill', 'pillp', 'pilld')]
        L.append(f"  {tn}: {{ {', '.join(items)} }},")
    L.append('};')
    L.append('')
    L.append('// Small raised pill, fixed height 44: left cap, repeating tile, right cap. Keys: tone + "" (raised), "p" (pressed), "d" (dent).')
    L.append('export const SOFT_PILL = {')
    for tn in themes + ('raild', 'raill'):
        for suf in ('', 'p', 'd'):
            L.append(f"  {tn}{suf}: {{ L: {req(f'pill{suf}_{tn}_L')}, M: {req(f'pill{suf}_{tn}_M')}, R: {req(f'pill{suf}_{tn}_R')} }},")
    L.append('};')
    C = PANELS['pill']['m'] + PANELS['pill']['r'] + PANELS['pill']['run']
    L.append(f"export const SOFT_PILL_DIMS = {{ body: 44, margin: {PANELS['pill']['m']}, capW: {C}, imgH: {44 + 2 * PANELS['pill']['m']} }};")
    L.append('')
    L.append('// The round 44dp button, one fixed-size picture per state: up, down (pressed), dent (selected).')
    L.append('export const SOFT_PEBBLE = {')
    for tn in themes + ('raild', 'raill'):
        L.append(f"  {tn}: {{ up: {req(f'pebble_{tn}')}, down: {req(f'pebblep_{tn}')}, dent: {req(f'pebbled_{tn}')} }},")
    L.append('};')
    L.append(f"export const SOFT_PEBBLE_DIMS = {{ body: 44, margin: {PEBBLE['m']}, img: {44 + 2 * PEBBLE['m']} }};")
    L.append('')
    out = os.path.join(HERE, '..', 'src', 'components', 'softAssets.js')
    with open(out, 'w') as f:
        f.write('\n'.join(L) + '\n')


def main():
    for tn in ('light', 'dark'):
        k = ms.key_img(tn, V, 2 * (KEY['cap'] - KEY['margin']) + MID, KEY['body'], m=KEY['margin'])
        kp = ms.key_img(tn, V, 2 * (KEY['cap'] - KEY['margin']) + MID, KEY['body'], pressed=True, m=KEY['margin'])
        f = ms.field_img(tn, V, 2 * (FIELD['cap'] - FIELD['margin']) + MID, FIELD['body'], FIELD['body'] // 2, m=FIELD['margin'])
        for nm, im, d in ((f'key_{tn}', k, KEY), (f'keyp_{tn}', kp, KEY), (f'field_{tn}', f, FIELD)):
            print(nm, im.size, 'seam delta', check_seamless(im, d['cap']))
            save_pieces(im, nm, d['cap'], d['margin'])
        save_nine(tn, 'card', PANELS['card']); save_nine(tn, 'cardp', PANELS['card'], True); save_nine(tn, 'well', PANELS['well']); save_nine(tn, 'slim', PANELS['slim']); save_nine(tn, 'slimp', PANELS['slim'], True); save_nine(tn, 'slimw', PANELS['slimw']); save_nine(tn, 'cardd', PANELS['card'], dent=True); save_nine(tn, 'slimd', PANELS['slim'], dent=True); save_pill(tn, PANELS['pill']); save_pill(tn, PANELS['pill'], True); save_pill(tn, PANELS['pill'], dent=True)
        for pressed, dent, nm in ((False, False, 'pebble'), (True, False, 'pebblep'), (False, True, 'pebbled')):
            im = panel_image(tn, PEBBLE, 44, 44, pressed, dent)
            for scale, suffix in ((1, ''), (2, '@2x'), (3, '@3x')):
                resample(im, scale).save(f'{OUT}/{nm}_{tn}{suffix}.png', optimize=True)
        lg = logo(tn)
        for scale, suffix in ((1, ''), (2, '@2x'), (3, '@3x')):
            resample(lg, scale).save(f'{OUT}/logo_{tn}{suffix}.png', optimize=True)
        print('logo', tn, lg.size)


    # The sidebar rail is its own navy plane (theme.js `bar`: #131E27 in the dark theme, #243746 in the light one), so
    # its controls are rendered on THAT colour: a raised pill on a ground of the same material.
    for tn, base in (('raild', (19, 30, 39)), ('raill', (36, 55, 70))):
        sl.THEME[tn] = dict(sl.THEME['dark'], base=base,
                            lit=tuple(min(255, c + d) for c, d in zip(base, (76, 93, 106))),
                            dark=tuple(int(c * 0.12) for c in base), lo=(2, 8, 12))
        V['shadow_gain'][tn] = 1.0
        save_pill(tn, PANELS['pill']); save_pill(tn, PANELS['pill'], True); save_pill(tn, PANELS['pill'], dent=True)
        for pressed, dent, nm in ((False, False, 'pebble'), (True, False, 'pebblep'), (False, True, 'pebbled')):
            im = panel_image(tn, PEBBLE, 44, 44, pressed, dent)
            for scale, suffix in ((1, ''), (2, '@2x'), (3, '@3x')):
                resample(im, scale).save(f'{OUT}/{nm}_{tn}{suffix}.png', optimize=True)
    write_asset_map()

    import json
    out = os.path.join(HERE, '..', 'src', 'components', 'softPlateau.js')
    with open(out, 'w') as f:
        f.write('// Generated by scripts/build-soft-assets.py. The flat colour in the middle of each panel, [r, g, b, a].\n')
        f.write('export const SOFT_PLATEAU = ' + json.dumps({tn: {k: list(v) for k, v in d.items()} for tn, d in PLATEAU.items()}, indent=2) + ';\n')


if __name__ == '__main__':
    main()
