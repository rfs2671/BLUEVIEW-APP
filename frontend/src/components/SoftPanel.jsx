import React, { useEffect, useRef, useState } from 'react';
import { View, Image, StyleSheet, Animated, Easing, Platform, Pressable, useWindowDimensions } from 'react-native';
import { useTheme } from '../context/ThemeContext';
import { SOFT_PANEL, SOFT_PANEL_DIMS, SOFT_PILL, SOFT_PILL_DIMS, SOFT_FULL, SOFT_PEBBLE, SOFT_PEBBLE_DIMS } from './softAssets';
import { SOFT_PLATEAU } from './softPlateau';

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
// The straight run between two corners is a tile TILE dp long, drawn at its natural size and REPEATED, then clipped
// to the run. It is never stretched: a thin strip stretched a long way drew wrongly on Android (blank, then bands
// and hairlines), while corners, which are never stretched, always drew right.
export const TILE = 256;
export function TileRow({ src, height, count = 3 }) {
  const tiles = [];
  for (let i = 0; i < count; i += 1) tiles.push(<Image key={i} source={src} style={{ width: TILE, height }} fadeDuration={0} />);
  return <View style={{ flex: 1, height, overflow: 'hidden', flexDirection: 'row' }}>{tiles}</View>;
}
function TileCol({ src, width, count = 3 }) {
  const tiles = [];
  for (let i = 0; i < count; i += 1) tiles.push(<Image key={i} source={src} style={{ width, height: TILE }} fadeDuration={0} />);
  return <View style={{ width, overflow: 'hidden' }}>{tiles}</View>;
}
export function useTileCount() {
  const { width } = useWindowDimensions();
  return Math.ceil((width + 80) / TILE) + 0;
}

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
const PRESSED_KIND = { card: 'cardp', slim: 'slimp' };

export function PanelSurface({ kind = 'card', anim }) {
  const d = SOFT_PANEL_DIMS[kind];
  const box = { position: 'absolute', left: -d.margin, right: -d.margin, top: -d.margin, bottom: -d.margin };
  const pressedKind = PRESSED_KIND[kind];
  if (anim && pressedKind) {
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
  // iPhone: ONE image with fixed corners (cap insets), so there are no joins. Separate stretched pieces faded at
  // their edges there (a one-pixel piece vanished; wider ones left faint seams).
  if (Platform.OS === 'ios') {
    return (
      <Image
        source={SOFT_FULL[isDark ? 'dark' : 'light'][kind]}
        style={StyleSheet.absoluteFill}
        capInsets={{ top: c, left: c, bottom: c, right: c }}
        resizeMode="stretch"
      />
    );
  }
  // Android and web: corners at natural size, the runs between them repeated tiles, the middle a flat colour.
  return <NineTiles set={set} c={c} plateau={SOFT_PLATEAU[isDark ? 'dark' : 'light'][kind]} />;
}

function NineTiles({ set, c, plateau }) {
  const [h, setH] = useState(640);
  const nH = useTileCount();
  const nV = Math.max(1, Math.ceil(h / TILE));
  const fixed = { width: c, height: c };
  const mid = `rgba(${plateau[0]},${plateau[1]},${plateau[2]},${plateau[3] / 255})`;
  return (
    <View style={StyleSheet.absoluteFill} onLayout={(e) => setH(e.nativeEvent.layout.height)}>
      <View style={{ height: c, flexDirection: 'row' }}>
        <Image source={set.tl} style={fixed} fadeDuration={0} />
        <TileRow src={set.tc} height={c} count={nH} />
        <Image source={set.tr} style={fixed} fadeDuration={0} />
      </View>
      <View style={{ flex: 1, flexDirection: 'row' }}>
        <TileCol src={set.ml} width={c} count={nV} />
        <View style={{ flex: 1, backgroundColor: mid }} />
        <TileCol src={set.mr} width={c} count={nV} />
      </View>
      <View style={{ height: c, flexDirection: 'row' }}>
        <Image source={set.bl} style={fixed} fadeDuration={0} />
        <TileRow src={set.bc} height={c} count={nH} />
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
  if (Platform.OS === 'ios') {
    return (
      <Image
        source={SOFT_FULL[isDark ? 'dark' : 'light'][pressed ? 'pillp' : 'pill']}
        style={StyleSheet.absoluteFill}
        capInsets={{ top: 0, left: d.capW, bottom: 0, right: d.capW }}
        resizeMode="stretch"
      />
    );
  }
  return <PillTiles set={set} d={d} />;
}

function PillTiles({ set, d }) {
  const n = useTileCount();
  return (
    <View style={[StyleSheet.absoluteFill, { flexDirection: 'row' }]}>
      <Image source={set.L} style={{ width: d.capW, height: d.imgH }} fadeDuration={0} />
      <TileRow src={set.M} height={d.imgH} count={n} />
      <Image source={set.R} style={{ width: d.capW, height: d.imgH }} fadeDuration={0} />
    </View>
  );
}

const styles = StyleSheet.create({ abs: { position: 'absolute' } });

/**
 * A soft box with content: a raised slim panel (`kind="slim"`, pressable with `onPress`) or a pressed-in track
 * (`kind="slimw"` or "well"). `style` places it (margins, flex, width); `contentStyle` lays out what is inside
 * (padding, rows). It is as big as its content, never smaller than the panel's minimum.
 */
export function SoftBox({ kind = 'slim', onPress, style, contentStyle, children, ...rest }) {
  const d = SOFT_PANEL_DIMS[kind];
  const [down, setDown] = useState(false);
  const anim = usePressAnim(down);
  const pressable = typeof onPress === 'function' && !!PRESSED_KIND[kind];
  const Wrapper = onPress ? Pressable : View;
  const press = onPress ? { onPress, onPressIn: () => setDown(true), onPressOut: () => setDown(false) } : {};
  return (
    <Wrapper {...rest} {...press} style={[{ position: 'relative', minHeight: d.min }, style]}>
      <PanelSurface kind={kind} anim={pressable ? anim : undefined} />
      <Animated.View style={[{ position: 'relative' }, contentStyle, pressable && pressShift(anim)]}>{children}</Animated.View>
    </Wrapper>
  );
}

/** The round 44dp button: a raised pebble that sinks when pressed. Children (an icon) sit in its centre. */
export function SoftPebble({ onPress, disabled, style, children, ...rest }) {
  const { isDark } = useTheme();
  const [down, setDown] = useState(false);
  const anim = usePressAnim(down);
  const d = SOFT_PEBBLE_DIMS;
  const set = SOFT_PEBBLE[isDark ? 'dark' : 'light'];
  const up = anim.interpolate({ inputRange: [0, 1], outputRange: [1, 0] });
  const box = { position: 'absolute', left: -d.margin, top: -d.margin, width: d.img, height: d.img };
  return (
    <Pressable
      {...rest}
      onPress={onPress}
      disabled={disabled}
      onPressIn={() => setDown(true)}
      onPressOut={() => setDown(false)}
      style={[{ width: d.body, height: d.body, position: 'relative' }, style, disabled && { opacity: 0.5 }]}
    >
      <View pointerEvents="none" style={box}>
        <Animated.Image source={set.up} style={[StyleSheet.absoluteFill, { opacity: up }]} fadeDuration={0} />
        <Animated.Image source={set.down} style={[StyleSheet.absoluteFill, { opacity: anim }]} fadeDuration={0} />
      </View>
      <Animated.View style={[{ width: d.body, height: d.body, alignItems: 'center', justifyContent: 'center', position: 'relative' }, pressShift(anim)]}>
        {children}
      </Animated.View>
    </Pressable>
  );
}

export default SoftPanel;
