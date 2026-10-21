import { Platform, StyleSheet } from 'react-native';
import { withAlpha } from './semanticColors';

// The card aura (theme.js `aura`): one soft, steel-blue halo plus a very thin rim. Every platform draws it with the
// single shadow it has natively, so it ships over the air with no native rebuild:
//   web      box-shadow
//   iOS      shadowColor/Offset/Opacity/Radius (needs an UNCLIPPED view; GlassCard keeps its clip on an inner view)
//   Android  elevation, tinted by shadowColor (Android 9+); weaker than the other two by nature
export const AURA_RIM_WIDTH = Platform.OS === 'web' ? 0.5 : StyleSheet.hairlineWidth;

export function auraRim(colors) {
  const a = colors && colors.aura;
  return a ? { borderWidth: AURA_RIM_WIDTH, borderColor: a.rim } : {};
}

// `elevation` only casts a shadow from a view that paints a background, so callers whose view has none (GlassCard's
// unclipped outer frame) ask for the iOS half only and put the Android half on the view that does paint.
// A view with a TRANSLUCENT fill gets no Android elevation: Android draws an elevation shadow under the whole view and a
// see-through fill lets it show inside the card as a grey smudge. Such views pass { translucent: true }.
export function auraShadow(colors, platform = Platform.OS, { translucent = false } = {}) {
  const a = colors && colors.aura;
  if (!a) return {};
  if (platform === 'web') {
    return { boxShadow: `${a.offset.width}px ${a.offset.height}px ${a.radius * 2}px ${withAlpha(a.color, a.opacity)}` };
  }
  if (platform === 'android') {
    return translucent ? {} : { elevation: 4, shadowColor: a.color };
  }
  return {
    shadowColor: a.color,
    shadowOffset: a.offset,
    shadowOpacity: a.opacity,
    shadowRadius: a.radius,
  };
}
