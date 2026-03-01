// ─── Dark palette (original app colors — unchanged) ────────────────────────
const _dark = {
  success: '#4ade80',
  warning: '#fbbf24',
  error:   '#f87171',
  primary: '#3b82f6',

  // Background gradient colors
  background: {
    start:  '#050a12',
    middle: '#0A1929',
    end:    '#050a12',
  },

  // Glass card colors
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

  // Text colors
  text: {
    primary:   'rgba(255, 255, 255, 0.9)',
    secondary: 'rgba(255, 255, 255, 0.6)',
    muted:     'rgba(255, 255, 255, 0.4)',
    subtle:    'rgba(255, 255, 255, 0.3)',
  },

  // Status colors
  status: {
    success:   '#4ade80',
    successBg: 'rgba(74, 222, 128, 0.2)',
    error:     '#f87171',
    errorBg:   'rgba(248, 113, 113, 0.1)',
    warning:   '#fbbf24',
    warningBg: 'rgba(251, 191, 36, 0.2)',
  },

  // UI surface / nav tints
  surface:   '#050a12',
  statusBar: 'light',
  blurTint:  'dark',

  // Accent
  white:       '#ffffff',
  transparent: 'transparent',
};

// ─── Light palette ──────────────────────────────────────────────────────────
const _light = {
  success: '#16a34a',
  warning: '#d97706',
  error:   '#dc2626',
  primary: '#2563eb',

  background: {
    start:  '#e8f0fb',
    middle: '#f0f5ff',
    end:    '#e8f0fb',
  },

  glass: {
    background:      'rgba(0, 0, 0, 0.04)',
    backgroundHover: 'rgba(0, 0, 0, 0.07)',
    border:          'rgba(0, 0, 0, 0.12)',
    borderHover:     'rgba(0, 0, 0, 0.25)',
    card:            'rgba(0, 0, 0, 0.03)',
    cardHover:       'rgba(0, 0, 0, 0.06)',
  },

  border: {
    subtle: 'rgba(0, 0, 0, 0.08)',
    medium: 'rgba(0, 0, 0, 0.15)',
    strong: 'rgba(0, 0, 0, 0.25)',
  },

  text: {
    primary:   'rgba(0, 0, 0, 0.90)',
    secondary: 'rgba(0, 0, 0, 0.60)',
    muted:     'rgba(0, 0, 0, 0.40)',
    subtle:    'rgba(0, 0, 0, 0.25)',
  },

  status: {
    success:   '#16a34a',
    successBg: 'rgba(22, 163, 74, 0.12)',
    error:     '#dc2626',
    errorBg:   'rgba(220, 38, 38, 0.08)',
    warning:   '#d97706',
    warningBg: 'rgba(217, 119, 6, 0.12)',
  },

  surface:   '#e8f0fb',
  statusBar: 'dark',
  blurTint:  'light',

  white:       '#ffffff',
  transparent: 'transparent',
};

// ─── Deep-assign helper ─────────────────────────────────────────────────────
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

// ─── THE mutable live colors object ────────────────────────────────────────
// Starts as dark (original default). ThemeContext calls applyTheme() to swap.
export const colors = {};
_deepAssign(colors, _dark);

/**
 * Called by ThemeContext when the user toggles the theme.
 * Mutates colors in-place → every existing import gets the new values
 * on next render without any changes to screen files.
 */
export function applyTheme(mode) {
  _deepAssign(colors, mode === 'light' ? _light : _dark);
}

// ─── Static design tokens (completely unchanged) ───────────────────────────
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
  sizes: {
    xs: 11,
    sm: 14,
    md: 16,
    lg: 18,
    xl: 24,
  },

  // Hero/Display text
  hero: {
    fontSize: 48,
    fontWeight: '200',
    letterSpacing: -1,
  },
  // Large headings
  h1: {
    fontSize: 36,
    fontWeight: '300',
    letterSpacing: -0.5,
  },
  // Section headings
  h2: {
    fontSize: 24,
    fontWeight: '400',
  },
  // Card titles
  h3: {
    fontSize: 18,
    fontWeight: '500',
  },
  // Body text
  body: {
    fontSize: 16,
    fontWeight: '400',
  },
  // Small text
  small: {
    fontSize: 14,
    fontWeight: '400',
  },
  // Labels (uppercase tracking)
  label: {
    fontSize: 11,
    fontWeight: '500',
    letterSpacing: 2,
    textTransform: 'uppercase',
  },
  // Stats numbers
  stat: {
    fontSize: 36,
    fontWeight: '200',
  },
};

export default {
  colors,
  spacing,
  borderRadius,
  typography,
};
