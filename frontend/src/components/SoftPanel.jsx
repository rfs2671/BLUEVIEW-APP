import React, { useEffect, useRef } from 'react';
import { View, Image, StyleSheet, Animated, Easing } from 'react-native';
import { useTheme } from '../context/ThemeContext';
import { SOFT_PANEL, SOFT_PANEL_DIMS, SOFT_PILL, SOFT_PILL_DIMS } from './softAssets';

/**
 * Stretchable soft-silicone surfaces: a `card` that rises off the page and a `well` that is pressed into it.
 *
 * The surface is an image cut in nine pieces (four corners, four one-pixel edges, a one-pixel centre) drawn BEHIND
 * the content, so it is always exactly as big as what is on it. A card whose list opens, or whose address wraps,
 * simply grows: text can never run off the edge of the surface the way it did on a fixed-size picture.
 *
 * The pieces are laid out in rows and share exact edges. None of them is a one-pixel-wide image: those drew as
 * nothing on iPhone, leaving only the four corners.
 */
/**
 * 0 -> 1 while something is pressed, with the soft-silicone timing: it eases in over about a tenth of a second and
 * eases back out more slowly, like silicone returning to shape. Opacity and transform only, so it runs on the
 * native driver.
 */
export function usePressAnim(pressed) {
  const v = useRef(new Animated.Value(pressed ? 1 : 0)).current;
  useEffect(() => {
    Animated.timing(v, {
      toValue: pressed ? 1 : 0,
      duration: pressed ? 110 : 260,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [pressed, v]);
  return v;
}

/** The label drops 1dp as the surface sinks. Pass the value from usePressAnim. */
export function pressShift(anim) {
  return { transform: [{ translateY: anim.interpolate({ inputRange: [0, 1], outputRange: [0, 1] }) }] };
}

/**
 * A card surface. With `anim` (from usePressAnim) it crossfades between the raised surface and the pressed one.
 *
 * THE FADING LAYERS MUST BE THE SAME SIZE AS THE PICTURE, shadow margin included. A view with an animated opacity is
 * composited on its own, and Android cuts a composited view off at its edges: fading a layer that is only as big as
 * the card chopped the shadows (and all of each edge) away, leaving four corners floating on the page. So the outer
 * box is the whole picture, and the layers inside it fill that box exactly.
 */
export function PanelSurface({ kind = 'card', anim }) {
  const d = SOFT_PANEL_DIMS[kind];
  const box = { position: 'absolute', left: -d.margin, right: -d.margin, top: -d.margin, bottom: -d.margin };
  if (anim && kind === 'card') {
    const up = anim.interpolate({ inputRange: [0, 1], outputRange: [1, 0] });
    return (
      <View pointerEvents="none" style={box}>
        <Animated.View style={[StyleSheet.absoluteFill, { opacity: up }]}><NineSlice kind="card" /></Animated.View>
        <Animated.View style={[StyleSheet.absoluteFill, { opacity: anim }]}><NineSlice kind="cardp" /></Animated.View>
      </View>
    );
  }
  return <View pointerEvents="none" style={box}><NineSlice kind={kind} /></View>;
}

function NineSlice({ kind = 'card' }) {
  const { isDark } = useTheme();
  const set = SOFT_PANEL[isDark ? 'dark' : 'light'][kind];
  const c = SOFT_PANEL_DIMS[kind].corner;
  // Laid out in three flex rows, the same way the login fields are (which draw correctly on a phone):
  // fixed-size corners, and the pieces between them take whatever room is left.
  const fixed = { width: c, height: c };
  return (
    <View style={StyleSheet.absoluteFill}>
      <View style={{ height: c, flexDirection: 'row' }}>
        <Image source={set.tl} style={fixed} fadeDuration={0} />
        <Image source={set.tc} style={{ flex: 1, height: c }} resizeMode="stretch" fadeDuration={0} />
        <Image source={set.tr} style={fixed} fadeDuration={0} />
      </View>
      <View style={{ flex: 1, flexDirection: 'row' }}>
        <Image source={set.ml} style={{ width: c }} resizeMode="stretch" fadeDuration={0} />
        <Image source={set.mc} style={{ flex: 1 }} resizeMode="stretch" fadeDuration={0} />
        <Image source={set.mr} style={{ width: c }} resizeMode="stretch" fadeDuration={0} />
      </View>
      <View style={{ height: c, flexDirection: 'row' }}>
        <Image source={set.bl} style={fixed} fadeDuration={0} />
        <Image source={set.bc} style={{ flex: 1, height: c }} resizeMode="stretch" fadeDuration={0} />
        <Image source={set.br} style={fixed} fadeDuration={0} />
      </View>
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

/** The surface of a small raised pill (fixed height 44, any width), for tool buttons. Same rule as PanelSurface. */
export function PillSurface({ anim }) {
  const d = SOFT_PILL_DIMS;
  const box = { position: 'absolute', left: -d.margin, right: -d.margin, top: -d.margin, height: d.imgH };
  if (anim) {
    const up = anim.interpolate({ inputRange: [0, 1], outputRange: [1, 0] });
    return (
      <View pointerEvents="none" style={box}>
        <Animated.View style={[StyleSheet.absoluteFill, { opacity: up }]}><PillLayer /></Animated.View>
        <Animated.View style={[StyleSheet.absoluteFill, { opacity: anim }]}><PillLayer pressed /></Animated.View>
      </View>
    );
  }
  return <View pointerEvents="none" style={box}><PillLayer /></View>;
}

function PillLayer({ pressed = false }) {
  const { isDark } = useTheme();
  const set = SOFT_PILL[(isDark ? 'dark' : 'light') + (pressed ? 'p' : '')];
  const d = SOFT_PILL_DIMS;
  return (
    <View style={[StyleSheet.absoluteFill, { flexDirection: 'row' }]}>
      <Image source={set.L} style={{ width: d.capW, height: d.imgH }} fadeDuration={0} />
      <Image source={set.M} style={{ flex: 1, height: d.imgH }} resizeMode="stretch" fadeDuration={0} />
      <Image source={set.R} style={{ width: d.capW, height: d.imgH }} fadeDuration={0} />
    </View>
  );
}

const styles = StyleSheet.create({ abs: { position: 'absolute' } });

export default SoftPanel;
