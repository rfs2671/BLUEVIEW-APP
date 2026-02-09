export const colors = {
   success: '#4ade80',
  warning: '#fbbf24',
  error: '#f87171',
  primary: '#3b82f6',

  // Background gradient colors
  background: {
    start: '#050a12',
    middle: '#0A1929',
    end: '#050a12',
  },
  
  // Glass card colors
  glass: {
    background: 'rgba(255, 255, 255, 0.08)',
    backgroundHover: 'rgba(255, 255, 255, 0.12)',
    border: 'rgba(255, 255, 255, 0.15)',
    borderHover: 'rgba(255, 255, 255, 0.3)',
  },
  
  // Text colors
  text: {
    primary: 'rgba(255, 255, 255, 0.9)',
    secondary: 'rgba(255, 255, 255, 0.6)',
    muted: 'rgba(255, 255, 255, 0.4)',
    subtle: 'rgba(255, 255, 255, 0.3)',
  },
  
  // Status colors
  status: {
    success: '#4ade80',
    successBg: 'rgba(74, 222, 128, 0.2)',
    error: '#f87171',
    errorBg: 'rgba(248, 113, 113, 0.1)',
    warning: '#fbbf24',
    warningBg: 'rgba(251, 191, 36, 0.2)',
  },
  
  // Accent
  white: '#ffffff',
  transparent: 'transparent',
};

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
