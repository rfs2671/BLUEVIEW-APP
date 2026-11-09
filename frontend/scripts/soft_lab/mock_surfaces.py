import numpy as np, io, base64
from PIL import Image
import silicone_lab as sl
from silicone_lab import S, THEME, VARIANTS, blur, shift, smooth, over, over_img, cast, lighting, capsule_sdf

def rbox(w, h, r, m):
    W = int((w + 2 * m) * S); H = int((h + 2 * m) * S)
    ys, xs = np.mgrid[0:H, 0:W]; x = (xs + .5) / S; y = (ys + .5) / S
    cx = m + w / 2; cy = m + h / 2
    qx = np.abs(x - cx) - (w / 2 - r); qy = np.abs(y - cy) - (h / 2 - r)
    d = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r
    return d, x, y

def finish(img):
    rgb = np.clip(img[..., :3] / 255.0, 0, 1); a = np.clip(img[..., 3:4], 0, 1)
    return Image.fromarray((np.concatenate([rgb, a], -1) * 255 + .5).astype(np.uint8), 'RGBA')

def field_img(tn, V, w, h, r, m=28, groove=False):
    th = THEME[tn]; sl._theme_name = tn
    d, x, y = rbox(w, h, r, m); mask = np.clip(.5 - d * S, 0, 1)
    img = np.zeros(mask.shape + (4,)); f = V['field']
    img = cast(img, mask, 0, f.get('lip_dy', 1.5), f.get('lip_sg', 1.6), th['hi'], f.get('lip_a', .7) * th['hia'])
    u = np.clip(-d / f['E'], 0, 1)
    hgt = -f['depth'] * (u * u * (3 - 2 * u)) ** f.get('q', .85) + f.get('lip_h', 0) * np.exp(-(((-d) - f.get('lip_off', 1.8)) / f.get('lip_w', 2.6)) ** 2) * (d < .5)
    if groove:
        cy = m + h / 2
        hgt = hgt - 1.1 * np.exp(-((y - cy) / 1.4) ** 2) * ((x > m + r) & (x < m + w - r))
    floor = -f.get('floor_k', 0) * (u * u * (3 - 2 * u))
    rgb = lighting(hgt, th, V, ao_sigma=f.get('ao_s', 0), ao_k=f.get('ao_k', 0), spec=V.get('field_spec', 0), spec_p=V.get('spec_p', 20), kd=f.get('kd'), extra=floor)
    return finish(over_img(img, rgb, mask))

def key_img(tn, V, w, h=60, pressed=False, m=52, scale=1.0):
    th = THEME[tn]; sl._theme_name = tn
    d, x, y = capsule_sdf(w, h, m, h); mask = np.clip(.5 - d * S, 0, 1)
    img = np.zeros(mask.shape + (4,)); k = V['key']; h0 = k['h0'] * (.35 if pressed else 1.0) * scale
    for dx, dy, sg, kind, a in (V['key_shadow_pressed'] if pressed else V['key_shadow']):
        dx, dy, sg = dx * scale, dy * scale, sg * scale
        img = cast(img, mask, dx, dy, sg, th['hi'] if kind == 'hi' else th['lo'], a * (th['hia'] if kind == 'hi' else V['shadow_gain'][tn]))
    t = np.clip(-d / (h / 2), 0, 1); p = k.get('p', 2.3)
    hgt = h0 * (1 - (1 - t) ** p) ** (1 / p)
    rgb = lighting(hgt, th, V, spec=V.get('key_spec', 0), spec_p=V.get('spec_p', 20))
    return finish(over_img(img, rgb, mask))

def b64(im):
    b = io.BytesIO(); im.save(b, 'PNG', optimize=True); return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()
