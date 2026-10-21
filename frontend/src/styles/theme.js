// ─── Dark palette ────────────────────────────────────────────────────────────
const _dark = {
  success: '#5FBF8A',
  warning: '#E3C27A',
  error:   '#F28B6E',
  primary: '#E3C27A',
  onPrimary: '#141A1F',
  accent: '#E3C27A',
  selected: '#E3C27A',
  onSelected: '#141A1F',
  chip: '#243746',
  bar: '#0E161D',
  onBar: '#E8EDF2',
  barActive: '#E3C27A',

  background: {
    start:  '#131E27',
    middle: '#131E27',
    end:    '#131E27',
  },

  glass: {
    background:      'rgba(28, 43, 56, 0.92)',
    backgroundHover: 'rgba(36, 55, 70, 0.96)',
    border:          'rgba(44, 65, 83, 1)',
    borderHover:     'rgba(157, 170, 182, 0.55)',
    card:            'rgba(28, 43, 56, 0.92)',
    cardHover:       'rgba(36, 55, 70, 0.96)',
  },

  // The card AURA: a very thin rim and a soft halo in the website's steel blue, so a card reads as floating above the
  // ground instead of outlined on it. On navy the halo is a pale blue light with no offset (a dark shadow is invisible
  // there); on paper it is the same blue as a soft shadow that sits a little below the card. Read by src/styles/aura.js.
  aura: {
    rim:     'rgba(140, 186, 222, 0.24)',
    color:   '#78ACD6',
    opacity: 0.18,
    radius:  10,
    offset:  { width: 0, height: 0 },
  },

  shadow: {
    color:   'rgba(0, 0, 0, 0.25)',
    offset:  { width: 0, height: 2 },
    opacity: 0.25,
    radius:  8,
  },

  border: {
    subtle: 'rgba(44, 65, 83, 0.6)',
    medium: 'rgba(44, 65, 83, 1)',
    strong: 'rgba(157, 170, 182, 0.45)',
  },

  text: {
    primary:   'rgba(232, 237, 242, 1)',
    secondary: 'rgba(197, 207, 216, 1)',
    // 0.40 → 0.55: at 0.40 this was 3.59–3.79:1 on every dark surface, below
    // WCAG AA 4.5:1 for text. 0.55 clears it everywhere (5.44–6.28:1).
    muted:     'rgba(157, 170, 182, 1)',
    // `subtle` stays at 0.30 (2.6–2.7:1). It is placeholder/disabled/meta-dot
    // text, which WCAG exempts; raising it would collapse the muted/subtle
    // hierarchy and make disabled inputs read as active.
    subtle:    'rgba(157, 170, 182, 0.6)',
  },

  // ── Semantic STATE values, per theme ────────────────────────────────────
  // The saturated state tokens used to be pinned theme-blind in
  // semanticColors.js, so light mode inherited the dark hexes and failed
  // badly (amber 1.16:1, green 1.59:1, red 1.93:1). They now live in the
  // palette so each theme carries values that clear AA on ITS surfaces.
  // Dark keeps exactly what shipped — this half is a zero-pixel change.
  state: {
    attention:    '#E3C27A',
    critical:     '#F28B6E',
    criticalText: '#F28B6E',
    criticalFill: '#A83E12',
    verified:     '#5FBF8A',
  },

  iconPod: {
    background: 'rgba(227, 194, 122, 1)',
    border:     'rgba(227, 194, 122, 1)',
    iconColor:  'rgba(20, 26, 31, 1)',
  },

  status: {
    success:   '#5FBF8A',
    successBg: 'rgba(95, 191, 138, 0.2)',
    error:     '#F28B6E',
    errorBg:   'rgba(242, 139, 110, 0.12)',
    warning:   '#E3C27A',
    warningBg: 'rgba(227, 194, 122, 0.2)',
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
  success: '#1E5B3A',
  warning: '#7A5300',
  error:   '#A83E12',
  primary: '#243746',
  onPrimary: '#FFFFFF',
  accent: '#B47C1F',
  selected: '#D8A044',
  onSelected: '#151A1D',
  chip: '#F2F3F0',
  bar: '#243746',
  onBar: '#FFFFFF',
  barActive: '#E3C27A',

  background: {
    start:  '#ECEDE9',
    middle: '#ECEDE9',
    end:    '#ECEDE9',
  },

  glass: {
    background:      'rgba(255, 255, 255, 0.96)',
    backgroundHover: 'rgba(242, 243, 240, 0.98)',
    border:          'rgba(201, 204, 198, 1)',
    borderHover:     'rgba(166, 170, 163, 1)',
    card:            'rgba(255, 255, 255, 0.96)',
    cardHover:       'rgba(242, 243, 240, 0.98)',
    cardGradientEnd: 'rgba(255, 255, 255, 0.96)',
  },

  aura: {
    rim:     'rgba(69, 140, 181, 0.18)',
    color:   '#458CB5',
    opacity: 0.20,
    radius:  10,
    offset:  { width: 0, height: 4 },
  },

  shadow: {
    color:   'rgba(21, 26, 29, 0.08)',
    offset:  { width: 0, height: 2 },
    opacity: 0.12,
    radius:  8,
  },

  border: {
    subtle: 'rgba(201, 204, 198, 0.55)',
    medium: 'rgba(201, 204, 198, 0.9)',
    strong: 'rgba(166, 170, 163, 0.9)',
  },

  text: {
    primary:   '#151A1D',
    secondary: 'rgba(55, 67, 75, 1)',
    muted:     'rgba(79, 90, 97, 1)',
    // See the dark palette: `subtle` is placeholder/disabled text (WCAG-exempt).
    subtle:    'rgba(79, 90, 97, 0.7)',
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
    attention:    '#7A5300',
    critical:     '#A83E12',
    criticalText: '#A83E12',
    criticalFill: '#A83E12',
    verified:     '#1E5B3A',
  },

  iconPod: {
    background: 'rgba(36, 55, 70, 1)',
    border:     'rgba(36, 55, 70, 1)',
    iconColor:  '#FFFFFF',
  },

  status: {
    success:   '#1E5B3A',
    successBg: 'rgba(30, 91, 58, 0.10)',
    error:     '#A83E12',
    errorBg:   'rgba(168, 62, 18, 0.08)',
    warning:   '#7A5300',
    warningBg: 'rgba(122, 83, 0, 0.10)',
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

// ─── Palette application ─────────────────────────────────────────────────────
//
// `colors` is mutated IN PLACE, never reassigned: semanticColors.js exposes
// live getters over this exact object (and ThemeContext deep-copies it on each
// toggle), so its identity has to survive a theme switch.
//
// The previous helper only ever ASSIGNED — it walked Object.keys(source) and
// never deleted. A key present in one palette but absent from the other
// therefore survived the switch still carrying the old theme's value, and the
// incoming palette had no way to remove it. `glass.cardGradientEnd` is the
// live instance: it is defined only in _light (see the glass block above), so
// applyTheme('light') → applyTheme('dark') left a LIGHT rgba sitting on the
// dark palette for the rest of the session. Nothing reads that key today, so
// no pixel is currently wrong; the leak is structural, and the next
// per-theme-only key added would be a real one.
//
// _applyPalette prunes before it assigns: when it returns, `target` has
// EXACTLY the key set of `source`, at every depth.
function _applyPalette(target, source) {
  for (const key of Object.keys(target)) {
    if (!Object.prototype.hasOwnProperty.call(source, key)) delete target[key];
  }
  for (const key of Object.keys(source)) {
    if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
      if (!target[key] || typeof target[key] !== 'object' || Array.isArray(target[key])) {
        target[key] = {};
      }
      _applyPalette(target[key], source[key]);
    } else {
      target[key] = source[key];
    }
  }
}

// ─── Mutable colors object — starts dark, mutated by applyTheme() ────────────
export const colors = {};
_applyPalette(colors, _dark);

// Which palette `colors` holds right now. ThemeProvider reads it so it never assumes the palette it finds is dark.
let _activeMode = 'dark';
export const getActiveMode = () => _activeMode;

export function applyTheme(mode) {
  _activeMode = mode === 'light' ? 'light' : 'dark';
  _applyPalette(colors, mode === 'light' ? _light : _dark);
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
  md: 10,
  lg: 14,
  xl: 14,
  xxl: 14,
  full: 9999,
};

// ─── Outdoor palette — the app's LIGHT look, pinned ──────────────────────────
//
// WHAT THIS IS NOW. Every value below is lifted from `_light` above, or from
// the shared components that render it (GlassCard's gradient and shadow,
// GlassButton's icon pill). It is not a second design language: it is the app's
// own light theme, frozen, so a screen can wear the house look without
// inheriting the theme switch.
//
// WHY IT IS PINNED RATHER THAN READ FROM `colors`. The CP fills a logbook
// standing outside, often in direct sun, on his own phone with whatever theme
// he happens to have set. `colors` is a live view over the ACTIVE palette, so
// consuming it would make this screen go dark for anyone with dark mode on —
// and a dark card in direct sun is unreadable no matter how deliberately it was
// chosen. Legibility there is a function of sunlight, not of a preference.
//
// This group therefore holds the same values the app shows in light mode and
// never flips. In light mode the stepper is pixel-equivalent to a GlassCard
// screen; in dark mode it stays readable instead of matching.
//
// THE VALUES ARE COPIED, NOT REFERENCED, AND THAT IS THE COST. If `_light`
// changes, this must be updated with it — asserted by
// src/styles/outdoorMatchesLight.test.cjs, which fails when the two drift.
//
// Contrast against `cardTop` (#ffffff at 0.92 over the background gradient):
//   text      #0A1929              → 16.8:1  (WCAG AAA at every size)
//   textSoft  rgba(10,25,41,0.75)  →  6.4:1  (AA, AAA at large)
//   textDim   rgba(10,25,41,0.65)  →  4.8:1  (AA) — the floor; nothing dimmer
export const outdoor = {
  // Page background — the three stops AnimatedBackground paints.
  backgroundStart: '#ECEDE9',
  backgroundMiddle: '#ECEDE9',
  backgroundEnd: '#ECEDE9',

  // Card fill: the white→blue-100 vertical gradient GlassCard uses in light
  // mode. NOT a flat white — the flat fill is what read as foreign.
  cardTop: 'rgba(255, 255, 255, 0.84)',
  cardBottom: 'rgba(250, 251, 248, 0.80)',
  // A sunken well inside a card (read-only values, hints).
  surfaceSunk: 'rgba(36, 55, 70, 0.06)',
  // An opaque surface for the header strip and the footer.
  surface: 'rgba(255, 255, 255, 0.96)',
  surfaceSelected: '#243746',
  // The concept's selected state on paper is brass with ink text, and its top bar is navy with white type.
  selected: '#D8A044',
  onSelected: '#151A1D',
  bar: '#243746',
  onBar: '#FFFFFF',
  barLine: 'rgba(255, 255, 255, 0.35)',
  barSub: 'rgba(255, 255, 255, 0.78)',

  text: '#151A1D',
  textSoft: 'rgba(55, 67, 75, 1)',
  textDim: 'rgba(79, 90, 97, 1)',
  textOnSelected: '#ffffff',

  // The glass border — present but soft. GlassCard draws exactly this, so the
  // "no visible border" in the brief is not what the app actually does.
  line: 'rgba(201, 204, 198, 1)',
  lineStrong: 'rgba(166, 170, 163, 0.9)',

  // The accent the reference screen's count badge uses.
  accent: '#B47C1F',
  accentBg: 'rgba(216, 160, 68, 0.16)',
  accentBorder: 'rgba(180, 124, 31, 0.40)',

  warnBg: '#fef3c7',
  warnBorder: '#d97706',
  warn: '#92400e',
  danger: '#b91c1c',
  okBg: '#dcfce7',
  okBorder: '#15803d',
  ok: '#166534',

  scrim: 'rgba(21, 26, 29, 0.72)',
};

// The card aura of the light theme (_light.aura), so the pinned-light surfaces float the same way the rest of the
// app's cards do; the elevation is the one src/styles/aura.js gives Android. Spread as a style object so a consumer
// cannot get half of it.
export const outdoorShadow = {
  shadowColor: '#458CB5',
  shadowOffset: { width: 0, height: 4 },
  shadowOpacity: 0.20,
  shadowRadius: 10,
  elevation: 4,
};

// ─── Touch targets ───────────────────────────────────────────────────────────
//
// The CP surfaces are used OUTDOORS, GLOVED, ONE-HANDED, by people who are
// older and not technical. 44 is Apple's accessibility floor for a fingertip on
// a clean screen indoors; none of those conditions hold on a jobsite. 56 is the
// floor here and it is a FLOOR, not a size — `min` is applied via minHeight /
// minWidth so a control may be larger but can never be smaller.
//
// `primary` is the one action a step is about. It is deliberately much bigger
// than the floor: the rule is that a ten-year-old names the primary action
// within three seconds, and on a phone that is won by size before it is won by
// wording.
export const touchTarget = {
  min: 56,
  primary: 72,
};

// ─── Typefaces ────────────────────────────────────────────────────────────────
//
// The app keeps the platform's own font (Roboto on Android, San Francisco on iOS, the system font on the web), as it
// always has. The role names exist so a title, a count and a label can each be given a face later without touching
// the screens that use them; until faces are bundled with the app they are all undefined, which is what
// `typography.regular/medium/semibold` always were.
const _ui = undefined;
const _display = undefined;
const _num = undefined;
const _mono = undefined;

export const typography = {
  regular: _ui,
  medium: _ui,
  semibold: _ui,
  bold: _ui,
  display: _display,
  num: _num,
  mono: _mono,
  // 12 and 13 are the two most-used sizes across the CP screens (86
  // occurrences between them) and neither had a token, which is why those
  // screens carry literals. They are named here so the stepper does not have
  // to invent them again: `fine` is sub-label text, `dense` is body text in a
  // packed row. `xl` is unchanged and still the largest.
  sizes: { fine: 12, dense: 13, xs: 11, sm: 14, md: 16, lg: 18, xl: 24 },
  hero:  { fontFamily: _display, fontSize: 40, fontWeight: '800', letterSpacing: -1.2 },
  h1:    { fontFamily: _display, fontSize: 30, fontWeight: '800', letterSpacing: -0.9 },
  h2:    { fontFamily: _display, fontSize: 24, fontWeight: '700', letterSpacing: -0.4 },
  h3:    { fontFamily: _display, fontSize: 18, fontWeight: '700' },
  body:  { fontSize: 16, fontWeight: '400' },
  small: { fontSize: 14, fontWeight: '400' },
  label: { fontFamily: _mono, fontSize: 11, fontWeight: '600', letterSpacing: 1.8, textTransform: 'uppercase' },
  stat:  { fontFamily: _num, fontSize: 40, fontWeight: '600' },
};

export default { colors, spacing, borderRadius, typography, touchTarget, outdoor, outdoorShadow };
