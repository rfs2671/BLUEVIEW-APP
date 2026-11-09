import os, sys
import numpy as np
from PIL import Image

S = 2
OUT = os.path.dirname(os.path.abspath(__file__))

def blur(a, sigma_px):
    if sigma_px < 0.3: return a
    h, w = a.shape; pad = int(3 * sigma_px) + 2
    H, W = h + 2 * pad, w + 2 * pad
    p = np.zeros((H, W)); p[pad:pad + h, pad:pad + w] = a
    fy = np.fft.fftfreq(H)[:, None]; fx = np.fft.rfftfreq(W)[None, :]
    k = np.exp(-2 * (np.pi ** 2) * (sigma_px ** 2) * (fx ** 2 + fy ** 2))
    return np.fft.irfft2(np.fft.rfft2(p) * k, s=(H, W))[pad:pad + h, pad:pad + w]

def shift(a, dx, dy):
    out = np.zeros_like(a); h, w = a.shape
    xs, xd = (0, dx) if dx >= 0 else (-dx, 0); ys, yd = (0, dy) if dy >= 0 else (-dy, 0)
    out[yd:yd + h - abs(dy), xd:xd + w - abs(dx)] = a[ys:ys + h - abs(dy), xs:xs + w - abs(dx)]
    return out

def capsule_sdf(w_dp, h_dp, margin, height, extra_margin_w=None):
    W = int((w_dp + 2 * margin) * S); H = int((height + 2 * margin) * S)
    ys, xs = np.mgrid[0:H, 0:W]
    x = (xs + 0.5) / S; y = (ys + 0.5) / S
    r = h_dp / 2; cy = margin + height / 2
    x0, x1 = margin + (height - h_dp) / 2 + r, margin + w_dp + (height - h_dp) / 2 - r
    # handles a capsule of height h_dp centred in a canvas for `height`
    px = np.clip(x, x0, x1)
    d = np.hypot(x - px, y - cy) - r
    return d, x, y

def smooth(t): t = np.clip(t, 0, 1); return t * t * (3 - 2 * t)
def over(dst, rgb, a):
    a = np.clip(a, 0, 1)[..., None]; da = dst[..., 3:4]; oa = a + da * (1 - a)
    safe = np.where(oa > 1e-6, oa, 1)
    rgb = np.broadcast_to(np.array(rgb, float), dst[..., :3].shape)
    return np.concatenate([(rgb * a + dst[..., :3] * da * (1 - a)) / safe, oa], -1)
def over_img(dst, rgb_img, a):
    a = np.clip(a, 0, 1)[..., None]; da = dst[..., 3:4]; oa = a + da * (1 - a)
    safe = np.where(oa > 1e-6, oa, 1)
    return np.concatenate([(rgb_img * a + dst[..., :3] * da * (1 - a)) / safe, oa], -1)
def cast(img, mask, dx, dy, sg, rgb, a):
    sh = blur(shift(mask, int(round(dx * S)), int(round(dy * S))), sg * S)
    return over(img, rgb, sh * a)

LIGHT = np.array([-0.52, -0.62, 0.80]); LIGHT /= np.linalg.norm(LIGHT)
HALF = LIGHT + np.array([0, 0, 1.0]); HALF /= np.linalg.norm(HALF)

THEME = {
    'light': dict(base=(236, 237, 233), lit=(255, 255, 255), dark=(152, 155, 143), lo=(116, 120, 106), hi=(255, 255, 255), hia=0.85, gain=1.0, tint=(255, 255, 255)),
    'dark':  dict(base=(28, 43, 56), lit=(104, 136, 162), dark=(3, 9, 14), lo=(2, 8, 12), hi=(255, 255, 255), hia=0.06, gain=1.35, tint=(120, 172, 214)),
}

def lighting(h, th, V, ao_sigma=0, ao_k=0, spec=0, spec_p=20, kd=None, extra=None):
    gy, gx = np.gradient(h); gx = gx * S; gy = gy * S
    nz = 1 / np.sqrt(gx ** 2 + gy ** 2 + 1); nx = -gx * nz; ny = -gy * nz
    ndl = nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]
    diff = (ndl - LIGHT[2]) * (kd if kd is not None else V['kd']) * th['gain']
    if extra is not None: diff = diff + extra * th['gain']
    if ao_k > 0:
        diff = diff - np.clip(blur(h, ao_sigma * S) - h, 0, None) * ao_k * th['gain']
    base = np.array(th['base'], float)
    lit = np.array(th['lit'], float); drk = np.array(th['dark'], float)
    pos = np.clip(diff, 0, 1)[..., None]; neg = np.clip(-diff, 0, 1)[..., None]
    rgb = base + (lit - base) * pos + (drk - base) * neg
    if spec > 0:
        ndh = nx * HALF[0] + ny * HALF[1] + nz * HALF[2]
        sp = np.clip(ndh, 0, 1) ** spec_p; sp0 = HALF[2] ** spec_p
        s = np.clip(sp - sp0, 0, 1) * spec * (1.0 if th is THEME['light'] else 1.6)
        rgb = rgb + (255 - rgb) * s[..., None]
    return rgb

def render_key(th, V, pressed):
    H0 = 60; cap = H0 / 2 + V['key_extra']; w = 2 * cap + 60; M = 52
    d, x, y = capsule_sdf(w, H0, M, H0)
    mask = np.clip(0.5 - d * S, 0, 1)
    img = np.zeros(mask.shape + (4,))
    k = V['key']; h0 = k['h0'] * (0.35 if pressed else 1.0)
    # shadows
    for dx, dy, sg, kind, a in (V['key_shadow_pressed'] if pressed else V['key_shadow']):
        if kind == 'hi': img = cast(img, mask, dx, dy, sg, th['hi'], a * th['hia'])
        else: img = cast(img, mask, dx, dy, sg, th['lo'], a * V['shadow_gain'][th_name(th)])
    t = np.clip(-d / (H0 / 2), 0, 1)
    p = k.get('p', 2.3)
    h = h0 * (1 - (1 - t) ** p) ** (1 / p)
    rgb = lighting(h, th, V, ao_sigma=0, ao_k=0, spec=V.get('key_spec', 0), spec_p=V.get('spec_p', 20))
    if V.get('rim'):
        rim = np.exp(np.clip(-d, 0, None) * -1 / V['rim']['w']) * (d < 0)
        rgb = rgb + (np.array(th['tint'], float) - rgb) * (rim * V['rim']['k'])[..., None]
    img = over_img(img, rgb, mask)
    return img, w, M, H0

def render_field(th, V):
    H0 = 60; cap = H0 / 2 + V['field_extra']; w = 2 * cap + 60; M = 28
    d, x, y = capsule_sdf(w, H0, M, H0)
    mask = np.clip(0.5 - d * S, 0, 1)
    img = np.zeros(mask.shape + (4,)); f = V['field']
    # soft lip of light under the lower edge
    img = cast(img, mask, 0, f.get('lip_dy', 1.5), f.get('lip_sg', 1.6), th['hi'], f.get('lip_a', 0.7) * th['hia'])
    if f.get('wall_shadow'):
        for dx, dy, sg, kind, a in f['wall_shadow']:
            if kind == 'hi': img = cast(img, mask, dx, dy, sg, th['hi'], a * th['hia'])
            else: img = cast(img, mask, dx, dy, sg, th['lo'], a * V['shadow_gain'][th_name(th)])
    u = np.clip(-d / f['E'], 0, 1)
    bowl = -f['depth'] * (u * u * (3 - 2 * u)) ** f.get('q', 0.85)
    lip = f.get('lip_h', 0) * np.exp(-(((-d) - f.get('lip_off', 1.8)) / f.get('lip_w', 2.6)) ** 2) * (d < 0.5)
    h = bowl + lip
    floor = -f.get('floor_k', 0) * (u * u * (3 - 2 * u))
    rgb = lighting(h, th, V, ao_sigma=f.get('ao_s', 0), ao_k=f.get('ao_k', 0), spec=V.get('field_spec', 0), spec_p=V.get('spec_p', 20), kd=f.get('kd'), extra=floor)
    if f.get('bounce', 0) > 0:
        # light reflected off the bottom-right wall into the dish: a soft glow low in the bowl
        gy, gx = np.gradient(h); sl = np.clip((-(gx * 0.6 + gy * 0.8)) * S, 0, 1) * (-d > 0)
        bl = blur(sl * (h < -0.5), 4 * S)
        rgb = rgb + (np.array(th['tint'], float) - rgb) * (np.clip(bl, 0, 1) * f['bounce'])[..., None]
    if V.get('rim'):
        rim = np.exp(np.clip(-d, 0, None) * -1 / V['rim']['w']) * (d < 0)
        rgb = rgb + (np.array(th['tint'], float) - rgb) * (rim * V['rim']['k'] * 0.6)[..., None]
    img = over_img(img, rgb, mask)
    return img, w, M, H0

def capsule_sdf_inner(w, H0, M, W_):
    Wc = int((w + 2 * M) * S); Hc = int((H0 + 2 * M) * S)
    ys, xs = np.mgrid[0:Hc, 0:Wc]; x = (xs + 0.5) / S; y = (ys + 0.5) / S
    r = H0 / 2 - W_; cy = M + H0 / 2
    x0, x1 = M + H0 / 2, M + w - H0 / 2
    px = np.clip(x, x0, x1)
    return np.hypot(x - px, y - cy) - r

_theme_name = {}
def th_name(th): return 'light' if th is THEME['light'] else 'dark'

def save(img, w, M, H0, extra, name):
    cap = H0 / 2 + extra; lc = int(round((M + cap) * S)); full = img.shape[1]
    rgb = np.clip(img[..., :3] / 255.0, 0, 1); a = np.clip(img[..., 3:4], 0, 1)
    arr = (np.concatenate([rgb, a], -1) * 255 + 0.5).astype(np.uint8)
    Image.fromarray(arr[:, :lc], 'RGBA').save(f'{OUT}/{name}_L.png', optimize=True)
    Image.fromarray(arr[:, full - lc:], 'RGBA').save(f'{OUT}/{name}_R.png', optimize=True)
    m = full // 2; Image.fromarray(arr[:, m:m + S], 'RGBA').save(f'{OUT}/{name}_M.png', optimize=True)
    return lc / S, arr.shape[0] / S

# ------------------------------------------------------------------ the five steps
def base_shadow(amb, dirc, hi_a=0.8):
    return [(-8, -8, 12, 'hi', hi_a), (0, 6, 12, 'lo', amb), (9, 13, 16, 'lo', dirc)]

VARIANTS = {
 1: dict(name='Soft dish', kd=1.15, key_extra=56, field_extra=44, shadow_gain={'light': 1.0, 'dark': 1.0},
         key=dict(h0=7, p=2.2), key_shadow=base_shadow(0.16, 0.28, 0.8), key_shadow_pressed=[(-3, -3, 5, 'hi', .5), (2, 3, 5, 'lo', .22)],
         field=dict(depth=4.0, E=24, lip_h=0, lip_a=0.7, kd=1.0, floor_k=0.03)),
 2: dict(name='Rolled lip', kd=1.2, key_extra=56, field_extra=44, shadow_gain={'light': 1.0, 'dark': 1.0},
         key=dict(h0=9, p=2.3), key_shadow=base_shadow(0.18, 0.30, 0.85), key_shadow_pressed=[(-3, -3, 5, 'hi', .5), (2, 3, 5, 'lo', .24)],
         field=dict(depth=4.8, E=24, lip_h=1.6, lip_w=4.4, lip_off=2.4, lip_a=0.6, kd=1.25, floor_k=0.05)),
 3: dict(name='Contact and gloss', kd=1.25, key_extra=56, field_extra=44, shadow_gain={'light': 1.0, 'dark': 1.0},
         key_spec=0.12, field_spec=0.10, spec_p=24,
         key=dict(h0=10, p=2.4),
         key_shadow=[(-8, -8, 12, 'hi', .9), (0, 2, 3.5, 'lo', .30), (0, 7, 13, 'lo', .20), (10, 15, 17, 'lo', .30)],
         key_shadow_pressed=[(-3, -3, 5, 'hi', .5), (0, 1, 2, 'lo', .3), (2, 3, 5, 'lo', .22)],
         field=dict(depth=5.4, E=24, lip_h=1.9, lip_w=4.6, lip_off=2.6, ao_s=7, ao_k=0.10, lip_a=0.6, kd=1.45, floor_k=0.07)),
 4: dict(name='Plush', kd=1.1, key_extra=60, field_extra=46, shadow_gain={'light': 1.05, 'dark': 1.0},
         key_spec=0.12, field_spec=0.10, spec_p=12,
         key=dict(h0=14, p=2.1),
         key_shadow=[(-9, -9, 14, 'hi', .9), (0, 2, 4, 'lo', .28), (0, 8, 15, 'lo', .22), (11, 17, 20, 'lo', .30)],
         key_shadow_pressed=[(-3, -3, 6, 'hi', .5), (0, 1, 2, 'lo', .3), (2, 4, 6, 'lo', .24)],
         field=dict(depth=6.8, E=26, lip_h=2.8, lip_w=5.6, lip_off=3.0, ao_s=9, ao_k=0.10, lip_a=0.6, kd=1.6, floor_k=0.09,
                    wall_shadow=[(-4, -4, 6, 'hi', .6), (5, 7, 9, 'lo', .16)])),
 5: dict(name='Subsurface glow', kd=1.1, key_extra=60, field_extra=46, shadow_gain={'light': 1.0, 'dark': 1.0},
         key_spec=0.11, field_spec=0.09, spec_p=12, rim=dict(w=7, k=0.16),
         key=dict(h0=14, p=2.1),
         key_shadow=[(-9, -9, 14, 'hi', .9), (0, 2, 4, 'lo', .26), (0, 8, 16, 'lo', .20), (11, 17, 21, 'lo', .28)],
         key_shadow_pressed=[(-3, -3, 6, 'hi', .5), (0, 1, 2, 'lo', .28), (2, 4, 6, 'lo', .22)],
         field=dict(depth=6.8, E=26, lip_h=2.8, lip_w=5.6, lip_off=3.0, ao_s=9, ao_k=0.10, lip_a=0.6, kd=1.6, floor_k=0.09, bounce=0.26,
                    wall_shadow=[(-4, -4, 6, 'hi', .6), (5, 7, 9, 'lo', .16)])),
}

if __name__ == '__main__':
    only = [int(a) for a in sys.argv[1:]] or list(VARIANTS)
    dims = {}
    for n in only:
        V = VARIANTS[n]
        for tn, th in THEME.items():
            img, w, M, H0 = render_key(th, V, False); dims['key'] = (M, H0, V['key_extra'], save(img, w, M, H0, V['key_extra'], f'v{n}_{tn}_key'))
            img, w, M, H0 = render_key(th, V, True);  save(img, w, M, H0, V['key_extra'], f'v{n}_{tn}_keyp')
            img, w, M, H0 = render_field(th, V);      dims['field'] = (M, H0, V['field_extra'], save(img, w, M, H0, V['field_extra'], f'v{n}_{tn}_field'))
        print('variant', n, V['name'], 'done')
    print(dims)
