// ─── Dark palette ────────────────────────────────────────────────────────────
const _dark = {
  success: '#4ade80',
  warning: '#fbbf24',
  error:   '#f87171',
  primary: '#3b82f6',

  background: {
    start:  '#050a12',
    middle: '#0A1929',
    end:    '#050a12',
  },

  glass: {
    background:      'rgba(255, 255, 255, 0.08)',
    backgroundHover: 'rgba(255, 255, 255, 0.12)',
    border:          'rgba(255, 255, 255, 0.15)',
    borderHover:     'rgba(255, 255, 255, 0.3)',
    card:            'rgba(255, 255, 255, 0.06)',
    cardHover:       'rgba(255, 255, 255, 0.10)',
  },

  shadow: {
    color:   'rgba(0, 0, 0, 0.3)',
    offset:  { width: 0, height: 4 },
    opacity: 0.3,
    radius:  12,
  },

  border: {
    subtle: 'rgba(255, 255, 255, 0.1)',
    medium: 'rgba(255, 255, 255, 0.2)',
    strong: 'rgba(255, 255, 255, 0.3)',
  },

  text: {
    primary:   'rgba(255, 255, 255, 0.9)',
    secondary: 'rgba(255, 255, 255, 0.6)',
    // 0.40 → 0.55: at 0.40 this was 3.59–3.79:1 on every dark surface, below
    // WCAG AA 4.5:1 for text. 0.55 clears it everywhere (5.44–6.28:1).
    muted:     'rgba(255, 255, 255, 0.55)',
    // `subtle` stays at 0.30 (2.6–2.7:1). It is placeholder/disabled/meta-dot
    // text, which WCAG exempts; raising it would collapse the muted/subtle
    // hierarchy and make disabled inputs read as active.
    subtle:    'rgba(255, 255, 255, 0.3)',
  },

  // ── Semantic STATE values, per theme ────────────────────────────────────
  // The saturated state tokens used to be pinned theme-blind in
  // semanticColors.js, so light mode inherited the dark hexes and failed
  // badly (amber 1.16:1, green 1.59:1, red 1.93:1). They now live in the
  // palette so each theme carries values that clear AA on ITS surfaces.
  // Dark keeps exactly what shipped — this half is a zero-pixel change.
  state: {
    attention:    '#fbbf24',  // amber-400  — 8.61:1 worst dark surface
    critical:     '#ef4444',  // red-500    — icons/dots (3.0 bar), 3.82:1
    criticalText: '#f87171',  // red-400    — text, 5.19:1
    criticalFill: '#dc2626',  // red-600    — fill behind WHITE text (4.83:1)
    verified:     '#22c55e',  // green-500  — 6.30:1
  },

  iconPod: {
    background: 'transparent',
    border:     'rgba(255, 255, 255, 0.15)',
    iconColor:  'rgba(255, 255, 255, 0.6)',           // same as text.secondary
  },

  status: {
    success:   '#4ade80',
    successBg: 'rgba(74, 222, 128, 0.2)',
    error:     '#f87171',
    errorBg:   'rgba(248, 113, 113, 0.1)',
    warning:   '#fbbf24',
    warningBg: 'rgba(251, 191, 36, 0.2)',
    // ── PR #15D D1 — 5-tier hazard-ratio palette (dark) ────────
    // L6 maps the backend hazard_ratio_to_color_tier output to:
    //   green   → status.success    (existing, ratio < 0.75)
    //   yellow  → status.caution    (NEW, 0.75 ≤ r < 1.5)
    //   amber   → status.warning    (existing, 1.5 ≤ r < 3.0)
    //   orange  → status.elevated   (NEW, 3.0 ≤ r < 4.0)
    //   red     → status.error      (existing, r ≥ 4.0)
    //   neutral → text.muted        (fallback when ratio invalid)
    caution:    '#facc15',                       // yellow-400
    cautionBg:  'rgba(250, 204, 21, 0.20)',
    elevated:   '#fb923c',                       // orange-400
    elevatedBg: 'rgba(251, 146, 60, 0.20)',
  },

  white:       '#ffffff',
  transparent: 'transparent',
};

// ─── Light palette (Blueview — exact CSS spec) ──────────────────────────────
//
//  Cards / boxes:
//    bg-gradient-to-br from-white/85 to-blue-100/70
//    border border-blue-200/60        → rgba(191,219,254,0.60)
//    shadow-xl shadow-blue-900/15
//    hover:border-blue-300            → #93C5FD
//
//  Icon pods:
//    bg-[#1565C0]/10  border-[#1565C0]/20  icon: #1565C0
//
// ─────────────────────────────────────────────────────────────────────────────
const _light = {
  success: '#2E7D32',
  warning: '#E65100',
  error:   '#C62828',
  primary: '#1565C0',

  background: {
    start:  '#d0dcf0',
    middle: '#D6E4F7',
    end:    '#ccd8ee',
  },

  glass: {
    background:      'rgba(255, 255, 255, 0.85)',   // from-white/85
    backgroundHover: 'rgba(255, 255, 255, 0.95)',
    border:          'rgba(191, 219, 254, 0.60)',   // border-blue-200/60
    borderHover:     'rgba(147, 197, 253, 1.0)',     // border-blue-300
    card:            'rgba(255, 255, 255, 0.80)',   // bg-white/80
    cardHover:       'rgba(255, 255, 255, 0.92)',
    cardGradientEnd: 'rgba(219, 234, 254, 0.70)',   // to-blue-100/70 (#DBEAFE at 70%)
  },

  shadow: {
    color:   'rgba(30, 58, 138, 0.15)',
    offset:  { width: 0, height: 8 },
    opacity: 0.15,
    radius:  24,
  },

  border: {
    subtle: 'rgba(191, 219, 254, 0.40)',   // blue-200/40
    medium: 'rgba(191, 219, 254, 0.60)',   // blue-200/60
    strong: 'rgba(147, 197, 253, 0.70)',   // blue-300/70
  },

  text: {
    primary:   '#0A1929',
    secondary: 'rgba(10, 25, 41, 0.75)',   // 6.40:1 at the darkest gradient stop
    muted:     'rgba(10, 25, 41, 0.65)',   // 4.75:1 at the darkest gradient stop
    // See the dark palette: `subtle` is placeholder/disabled text (WCAG-exempt).
    subtle:    'rgba(10, 25, 41, 0.50)',
  },

  // ── Semantic STATE values, light theme ──────────────────────────────────
  // Darker variants of the SAME hue families — the dark-theme hexes were
  // unreadable here (amber 1.16:1, green 1.59:1, red 1.93:1 at the darkest
  // gradient stop). Every value below clears AA against BOTH gradient ends
  // (#D6E4F7 lightest / #ccd8ee darkest) and both card fills.
  //
  // `attention` is #7A5300, NOT a browner amber like #92400E. Both pass
  // contrast, but #92400E sits at hue 23° — only 18° from critical red, so
  // "expiring" and "violation" stopped being distinguishable at a glance.
  // #7A5300 is hue 41°, within 2° of the dark amber #fbbf24 (43°): a pure
  // lightness/saturation change on amber's own hue, keeping 42.5° of hue
  // separation from red (dark theme has 57°).
  state: {
    attention:    '#7A5300',  // dark gold-amber — 4.77:1 worst surface
    critical:     '#C62828',  // red — icons/dots (3.0 bar), 3.92:1
    criticalText: '#B91C1C',  // red-700 — text, 4.51:1
    criticalFill: '#B91C1C',  // fill behind WHITE text — 6.02:1 on white
    verified:     '#166534',  // green-800 — 4.97:1
  },

  iconPod: {
    background: 'rgba(21, 101, 192, 0.10)',   // bg-[#1565C0]/10
    border:     'rgba(21, 101, 192, 0.20)',   // border-[#1565C0]/20
    iconColor:  '#1565C0',                     // primary blue
  },

  status: {
    success:   '#2E7D32',
    successBg: 'rgba(46, 125, 50, 0.10)',
    error:     '#C62828',
    errorBg:   'rgba(198, 40, 40, 0.08)',
    warning:   '#E65100',
    warningBg: 'rgba(230, 81, 0, 0.10)',
    // ── PR #15D D1 — 5-tier hazard-ratio palette (light) ────────
    // See _dark.status.caution comment for the L6 mapping. Light
    // values are Material amber-300 (#FFD54F) for caution and
    // Material deep-orange-800 (#EF6C00) for elevated — these are
    // pinned in the PR #15D Stage 5 spec.
    caution:    '#FFD54F',                       // amber-300
    cautionBg:  'rgba(255, 213, 79, 0.18)',
    elevated:   '#EF6C00',                       // deep-orange-800
    elevatedBg: 'rgba(239, 108, 0, 0.10)',
  },

  white:       '#ffffff',
  transparent: 'transparent',
};

// ─── Deep-assign helper ──────────────────────────────────────────────────────
function _deepAssign(target, source) {
  for (const key of Object.keys(source)) {
    if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
      if (!target[key] || typeof target[key] !== 'object') target[key] = {};
      _deepAssign(target[key], source[key]);
    } else {
      target[key] = source[key];
    }
  }
}

// ─── Mutable colors object — starts dark, mutated by applyTheme() ────────────
export const colors = {};
_deepAssign(colors, _dark);

export function applyTheme(mode) {
  _deepAssign(colors, mode === 'light' ? _light : _dark);
}

// ─── Static tokens ───────────────────────────────────────────────────────────
export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
};

export const borderRadius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  full: 9999,
};

export const typography = {
  sizes: { xs: 11, sm: 14, md: 16, lg: 18, xl: 24 },
  hero:  { fontSize: 48, fontWeight: '200', letterSpacing: -1 },
  h1:    { fontSize: 36, fontWeight: '300', letterSpacing: -0.5 },
  h2:    { fontSize: 24, fontWeight: '400' },
  h3:    { fontSize: 18, fontWeight: '500' },
  body:  { fontSize: 16, fontWeight: '400' },
  small: { fontSize: 14, fontWeight: '400' },
  label: { fontSize: 11, fontWeight: '500', letterSpacing: 2, textTransform: 'uppercase' },
  stat:  { fontSize: 36, fontWeight: '200' },
};

export default { colors, spacing, borderRadius, typography };
