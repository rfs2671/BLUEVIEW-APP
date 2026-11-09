import React from 'react';
import { View, Image, StyleSheet } from 'react-native';
import { useTheme } from '../context/ThemeContext';
import { SOFT_PANEL, SOFT_PANEL_DIMS, SOFT_PILL, SOFT_PILL_DIMS } from './softAssets';

/**
 * Stretchable soft-silicone surfaces: a `card` that rises off the page and a `well` that is pressed into it.
 *
 * The surface is an image cut in nine pieces (four corners, four one-pixel edges, a one-pixel centre) drawn BEHIND
 * the content, so it is always exactly as big as what is on it. A card whose list opens, or whose address wraps,
 * simply grows: text can never run off the edge of the surface the way it did on a fixed-size picture.
 *
 * Pieces share exact edges, so they snap to the same pixel together. Only the opaque centre tucks 1dp under its
 * neighbours: the shadow pieces are translucent, and overlapping them would draw a darker line where they meet.
 */
export function PanelSurface({ kind = 'card', radius }) {
  const { isDark } = useTheme();
  const set = SOFT_PANEL[isDark ? 'dark' : 'light'][kind];
  const d = SOFT_PANEL_DIMS[kind];
  const c = d.corner;
  const o = c - 1; // only the opaque centre tucks 1dp under its neighbours
  const img = (src, style) => <Image source={src} style={[styles.abs, style]} resizeMode="stretch" fadeDuration={0} />;
  return (
    <View pointerEvents="none" style={{ position: 'absolute', left: -d.margin, right: -d.margin, top: -d.margin, bottom: -d.margin }}>
      {img(set.mc, { left: o, right: o, top: o, bottom: o })}
      {img(set.tc, { left: c, right: c, top: 0, height: c })}
      {img(set.bc, { left: c, right: c, bottom: 0, height: c })}
      {img(set.ml, { left: 0, width: c, top: c, bottom: c })}
      {img(set.mr, { right: 0, width: c, top: c, bottom: c })}
      {img(set.tl, { left: 0, top: 0, width: c, height: c })}
      {img(set.tr, { right: 0, top: 0, width: c, height: c })}
      {img(set.bl, { left: 0, bottom: 0, width: c, height: c })}
      {img(set.br, { right: 0, bottom: 0, width: c, height: c })}
    </View>
  );
}

/**
 * A soft panel with content. `style` places and sizes it (margins, flex, width) and may set padding;
 * the surface follows whatever size the content makes it.
 */
export function SoftPanel({ kind = 'card', style, children, ...rest }) {
  const d = SOFT_PANEL_DIMS[kind];
  return (
    <View {...rest} style={[{ minHeight: d.min, minWidth: d.min }, style]}>
      <PanelSurface kind={kind} />
      {children}
    </View>
  );
}

/** The surface of a small raised pill (fixed height 44, any width), for tool buttons. */
export function PillSurface({ pressed = false }) {
  const { isDark } = useTheme();
  const set = SOFT_PILL[(isDark ? 'dark' : 'light') + (pressed ? 'p' : '')];
  const d = SOFT_PILL_DIMS;
  return (
    <View pointerEvents="none" style={{ position: 'absolute', left: -d.margin, right: -d.margin, top: -d.margin, height: d.imgH, flexDirection: 'row' }}>
      <Image source={set.L} style={{ width: d.capW, height: d.imgH }} fadeDuration={0} />
      <Image source={set.M} style={{ flex: 1, height: d.imgH }} resizeMode="stretch" fadeDuration={0} />
      <Image source={set.R} style={{ width: d.capW, height: d.imgH }} fadeDuration={0} />
    </View>
  );
}

const styles = StyleSheet.create({ abs: { position: 'absolute' } });

export default SoftPanel;
