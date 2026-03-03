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

// ─── Light palette (Blueview) ────────────────────────────────────────────────
// Background:  #EEF4FB with subtle blue radial hints
// Surfaces:    White (#FFF) glass cards with light blue borders
// Text:        Dark navy #0A1929
// Primary:     Vibrant deep blue #1565C0
// ─────────────────────────────────────────────────────────────────────────────
const _light = {
  success: '#2E7D32',
  warning: '#E65100',
  error:   '#C62828',
  primary: '#1565C0',

  background: {
    start:  '#EEF4FB',
    middle: '#F4F8FD',
    end:    '#EEF4FB',
  },

  glass: {
    background:      'rgba(255, 255, 255, 0.70)',
    backgroundHover: 'rgba(255, 255, 255, 0.85)',
    border:          'rgba(255, 255, 255, 0.80)',
    borderHover:     'rgba(21, 101, 192, 0.30)',
    card:            'rgba(255, 255, 255, 0.60)',
    cardHover:       'rgba(255, 255, 255, 0.80)',
  },

  border: {
    subtle: 'rgba(10, 25, 41, 0.08)',
    medium: 'rgba(10, 25, 41, 0.15)',
    strong: 'rgba(10, 25, 41, 0.25)',
  },

  text: {
    primary:   'rgba(10, 25, 41, 0.90)',
    secondary: 'rgba(10, 25, 41, 0.55)',
    muted:     'rgba(10, 25, 41, 0.40)',
    subtle:    'rgba(10, 25, 41, 0.25)',
  },

  status: {
    success:   '#2E7D32',
    successBg: 'rgba(46, 125, 50, 0.12)',
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
