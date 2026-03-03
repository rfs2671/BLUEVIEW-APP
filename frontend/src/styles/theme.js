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
    muted:     'rgba(255, 255, 255, 0.4)',
    subtle:    'rgba(255, 255, 255, 0.3)',
  },

  status: {
    success:   '#4ade80',
    successBg: 'rgba(74, 222, 128, 0.2)',
    error:     '#f87171',
    errorBg:   'rgba(248, 113, 113, 0.1)',
    warning:   '#fbbf24',
    warningBg: 'rgba(251, 191, 36, 0.2)',
  },

  white:       '#ffffff',
  transparent: 'transparent',
};

// ─── Light palette (Blueview — exact CSS spec) ──────────────────────────────
//
//  globals.css background:
//    base #D6E4F7  +  linear-gradient(180deg, #d0dcf0 0%, #D6E4F7 50%, #ccd8ee 100%)
//    + radial-gradient(ellipse at top,  rgba(21,101,192,0.08) …)
//    + radial-gradient(ellipse at bottom, rgba(2,119,189,0.06) …)
//
//  Cards / boxes:
//    bg-white/85  backdrop-blur-2xl
//    border border-blue-200/60        → #BFDBFE at 60% → rgba(191,219,254,0.60)
//    shadow-xl shadow-blue-900/15     → #1e3a5f-ish at 15%
//    hover:border-blue-300            → #93C5FD
//
//  Text:
//    primary  #0A1929
//    muted    #0A1929/50, #0A1929/40
//
//  Primary / accent:  #1565C0
//    icon bg:  bg-[#1565C0]/10
//
//  Nav bar:
//    bg-white/90  backdrop-blur-2xl  border-blue-200/60
//    active: bg-blue-50 (#EFF6FF)
//
// ─────────────────────────────────────────────────────────────────────────────
const _light = {
  success: '#2E7D32',
  warning: '#E65100',
  error:   '#C62828',
  primary: '#1565C0',

  // linear-gradient(180deg, #d0dcf0 0%, #D6E4F7 50%, #ccd8ee 100%)
  background: {
    start:  '#d0dcf0',
    middle: '#D6E4F7',
    end:    '#ccd8ee',
  },

  // ── Glass surfaces ─────────────────────────────────────────────────────────
  //  bg-white/85                         → rgba(255,255,255,0.85)
  //  border border-blue-200/60           → rgba(191,219,254,0.60)
  //  hover:border-blue-300               → #93C5FD
  //  shadow-xl shadow-blue-900/15        → mapped in shadow token below
  glass: {
    background:      'rgba(255, 255, 255, 0.85)',
    backgroundHover: 'rgba(255, 255, 255, 0.95)',
    border:          'rgba(191, 219, 254, 0.60)',   // border-blue-200/60
    borderHover:     'rgba(147, 197, 253, 1.0)',     // border-blue-300
    card:            'rgba(255, 255, 255, 0.80)',
    cardHover:       'rgba(255, 255, 255, 0.92)',
  },

  // shadow-xl shadow-blue-900/15  → blue-900 is #1e3a8a
  shadow: {
    color:   'rgba(30, 58, 138, 0.15)',
    offset:  { width: 0, height: 8 },
    opacity: 0.15,
    radius:  24,
  },

  // Structural borders (blue-200 variants)
  border: {
    subtle: 'rgba(191, 219, 254, 0.40)',   // blue-200/40
    medium: 'rgba(191, 219, 254, 0.60)',   // blue-200/60
    strong: 'rgba(147, 197, 253, 0.70)',   // blue-300/70
  },

  // Text: #0A1929 at varying opacities
  text: {
    primary:   '#0A1929',                            // full
    secondary: 'rgba(10, 25, 41, 0.50)',             // /50
    muted:     'rgba(10, 25, 41, 0.40)',             // /40
    subtle:    'rgba(10, 25, 41, 0.22)',
  },

  status: {
    success:   '#2E7D32',
    successBg: 'rgba(46, 125, 50, 0.10)',
    error:     '#C62828',
    errorBg:   'rgba(198, 40, 40, 0.08)',
    warning:   '#E65100',
    warningBg: 'rgba(230, 81, 0, 0.10)',
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

/**
 * Called by ThemeContext.toggleTheme() before screens remount.
 * Mutates colors in-place so every StyleSheet.create() that runs
 * during remount reads the correct new palette.
 */
export function applyTheme(mode) {
  _deepAssign(colors, mode === 'light' ? _light : _dark);
}

// ─── Static tokens (unchanged from original) ─────────────────────────────────
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
