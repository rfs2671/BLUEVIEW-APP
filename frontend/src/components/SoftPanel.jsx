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
// Every picture is cut BLEED larger than the box it fills (real neighbouring pixels in the extra band) and clipped to
// the box. A picture fades slightly at its own edge when drawn on a fractional pixel, which is every phone whose density
// is not a whole number; with the bleed the fade falls outside the clip and neighbouring pieces meet without a hairline.
export const BLEED = 2;
export function BleedImage({ src, width, height, style }) {
  return (
    <View style={[{ width, height, overflow: 'hidden' }, style]}>
      <Image
        source={src}
        style={{ position: 'absolute', left: -BLEED, top: -BLEED, width: width + 2 * BLEED, height: height + 2 * BLEED }}
        fadeDuration={0}
      />
    </View>
  );
}
export function TileRow({ src, height, count = 3 }) {
  const tiles = [];
  for (let i = 0; i < count; i += 1) tiles.push(<BleedImage key={i} src={src} width={TILE} height={height} />);
  return <View style={{ flex: 1, height, overflow: 'hidden', flexDirection: 'row' }}>{tiles}</View>;
}
function TileCol({ src, width, count = 3 }) {
  const tiles = [];
  for (let i = 0; i < count; i += 1) tiles.push(<BleedImage key={i} src={src} width={width} height={TILE} />);
  return <View style={{ width, overflow: 'hidden' }}>{tiles}</View>;
}
export function useTileCount() {
  const { width } = useWindowDimensions();
  return Math.ceil((width + 80) / TILE) + 0;
}

/**
 * The press state of a soft surface, as ONE number (0 = raised, 1 = pressed in) plus an optional second number for
 * "selected" (0 = not, 1 = stays dented, like the text fields).
 *
 *  - pressing eases in gently (about 150ms);
 *  - letting go SPRINGS back softly: a slow, small overshoot that settles, like silicone, not a rubber ball;
 *  - choosing something (selected = true) dents it and holds it there; choosing something ELSE releases it with the
 *    same spring, so the old choice bounces back up as the new one sinks.
 *
 * Opacity and transform only, so everything runs on the native driver. Pass `selected` (true/false) to make the
 * surface selectable; leave it undefined for a plain button.
 */
export function usePressAnim(pressed, selected, lazy = false) {
  const v = useRef(new Animated.Value(pressed ? 1 : 0)).current;
  const sel = useRef(new Animated.Value(selected ? 1 : 0)).current;
  // `live`: the pressed and dented pictures only EXIST while they can be seen (pressed, selected, or settling after a
  // release). A list of a hundred records used to carry three full copies of the surface per card, all the time.
  const [live, setLive] = useState(!!(pressed || selected));
  useEffect(() => {
    if (pressed || selected) { setLive(true); return undefined; }
    const t = setTimeout(() => setLive(false), 900);
    return () => clearTimeout(t);
  }, [pressed, selected]);
  useEffect(() => {
    if (pressed) {
      Animated.timing(v, { toValue: 1, duration: 150, easing: Easing.out(Easing.cubic), useNativeDriver: true }).start();
    } else {
      Animated.spring(v, { toValue: 0, speed: 10, bounciness: 8, useNativeDriver: true }).start();
    }
  }, [pressed, v]);
  useEffect(() => {
    if (selected === undefined) return;
    if (selected) {
      Animated.timing(sel, { toValue: 1, duration: 220, easing: Easing.out(Easing.cubic), useNativeDriver: true }).start();
    } else {
      Animated.spring(sel, { toValue: 0, speed: 8, bounciness: 4, useNativeDriver: true }).start();
    }
  }, [selected, sel]);
  v.sel = sel;
  // Buttons keep their pressed picture mounted (a button that has to build it at the moment of the tap shows no animation
  // at all). Only list cards pass `lazy` and build it on demand.
  v.live = lazy ? live : true;
  v.selectable = selected !== undefined;
  return v;
}

const clamp01 = (x) => x.interpolate({ inputRange: [0, 1], outputRange: [0, 1], extrapolate: 'clamp' });

/** The label sinks 1dp when pressed, and bobs up a little as the surface springs back. */
export function pressShift(anim) {
  const total = anim.sel ? Animated.add(anim, anim.sel) : anim;
  return { transform: [{ translateY: total.interpolate({ inputRange: [-0.5, 0, 1, 2], outputRange: [-2, 0, 1, 1.5], extrapolate: 'clamp' }) }] };
}

/** The surface itself pops up a touch as it springs back past its resting height. */
function popStyle(anim) {
  return { transform: [{ translateY: anim.interpolate({ inputRange: [-0.5, 0, 1], outputRange: [-4, 0, 0], extrapolate: 'clamp' }) }] };
}

/** Opacities of the three layers (raised, pressed, dented) for one anim, times an optional base opacity (idle = 0). */
function layerOpacities(anim, base) {
  const vc = clamp01(anim);
  const sc = anim.selectable ? clamp01(anim.sel) : null;
  let raised = sc ? clamp01(Animated.subtract(1, Animated.add(vc, sc))) : Animated.subtract(1, vc);
  let pressed = sc ? Animated.multiply(vc, Animated.subtract(1, sc)) : vc;
  if (base) { raised = Animated.multiply(raised, base); pressed = Animated.multiply(pressed, base); }
  return { raised, pressed, dent: sc };
}

/**
 * A card surface. With `anim` (from usePressAnim) it crossfades between the raised surface, the pressed one and
 * (when selectable) the dented one. `tone` forces the dark/light artwork (the sidebar rail is always navy);
 * `baseOpacity` (an Animated value) hides the surface at rest, for items that only show one on hover.
 *
 * THE FADING LAYERS MUST BE THE SAME SIZE AS THE PICTURE, shadow margin included. A view with an animated opacity is
 * composited on its own, and Android cuts a composited view off at its edges: fading a layer that is only as big as
 * the card chopped the shadows (and all of each edge) away, leaving four corners floating on the page. So the outer
 * box is the whole picture, and the layers inside it fill that box exactly.
 */
const PRESSED_KIND = { card: 'cardp', slim: 'slimp' };
const DENT_KIND = { card: 'cardd', slim: 'slimd' };

export function PanelSurface({ kind = 'card', anim, tone, baseOpacity }) {
  const d = SOFT_PANEL_DIMS[kind];
  const box = { position: 'absolute', left: -d.margin, right: -d.margin, top: -d.margin, bottom: -d.margin };
  const pressedKind = PRESSED_KIND[kind];
  if (anim && pressedKind) {
    const o = layerOpacities(anim, baseOpacity);
    const fill = StyleSheet.absoluteFill;
    return (
      <Animated.View pointerEvents="none" style={[box, popStyle(anim)]}>
        <Animated.View style={[fill, { opacity: o.raised }]}><NineSlice kind={kind} tone={tone} /></Animated.View>
        {anim.live ? <Animated.View style={[fill, { opacity: o.pressed }]}><NineSlice kind={pressedKind} tone={tone} /></Animated.View> : null}
        {o.dent && anim.live ? <Animated.View style={[fill, { opacity: o.dent }]}><NineSlice kind={DENT_KIND[kind]} tone={tone} /></Animated.View> : null}
      </Animated.View>
    );
  }
  return <View pointerEvents="none" style={box}><NineSlice kind={kind} tone={tone} /></View>;
}

function NineSlice({ kind = 'card', tone }) {
  const { isDark } = useTheme();
  const t = tone || (isDark ? 'dark' : 'light');
  const set = SOFT_PANEL[t][kind];
  const c = SOFT_PANEL_DIMS[kind].corner;
  // iPhone: ONE image with fixed corners (cap insets), so there are no joins. Separate stretched pieces faded at
  // their edges there (a one-pixel piece vanished; wider ones left faint seams).
  if (Platform.OS === 'ios') {
    return (
      <Image
        source={SOFT_FULL[t][kind]}
        style={StyleSheet.absoluteFill}
        capInsets={{ top: c, left: c, bottom: c, right: c }}
        resizeMode="stretch"
      />
    );
  }
  // Android and web: corners at natural size, the runs between them repeated tiles, the middle a flat colour.
  return <NineTiles set={set} c={c} plateau={SOFT_PLATEAU[t][kind]} />;
}

function NineTiles({ set, c, plateau }) {
  // Only as many tiles as the run between the corners needs, measured: a typical card is one tile along each edge.
  const [box, setBox] = useState({ w: 0, h: 0 });
  const nH = box.w ? Math.max(1, Math.ceil((box.w - 2 * c) / TILE)) : 1;
  const nV = box.h ? Math.max(1, Math.ceil((box.h - 2 * c) / TILE)) : 1;
  const fixed = { width: c, height: c };
  const mid = `rgba(${plateau[0]},${plateau[1]},${plateau[2]},${plateau[3] / 255})`;
  return (
    <View
      style={StyleSheet.absoluteFill}
      onLayout={(e) => {
        const { width, height } = e.nativeEvent.layout;
        // tile counts change in whole steps; ignore sub-tile changes so an expanding card does not re-render per frame
        setBox((cur) => {
          const nw = Math.ceil(width / 64); const nh = Math.ceil(height / 64);
          return (Math.ceil(cur.w / 64) === nw && Math.ceil(cur.h / 64) === nh) ? cur : { w: width, h: height };
        });
      }}
    >
      <View style={{ height: c, flexDirection: 'row' }}>
        <BleedImage src={set.tl} width={c} height={c} />
        <TileRow src={set.tc} height={c} count={nH} />
        <BleedImage src={set.tr} width={c} height={c} />
      </View>
      <View style={{ flex: 1, flexDirection: 'row' }}>
        <TileCol src={set.ml} width={c} count={nV} />
        <View style={{ flex: 1, backgroundColor: mid }} />
        <TileCol src={set.mr} width={c} count={nV} />
      </View>
      <View style={{ height: c, flexDirection: 'row' }}>
        <BleedImage src={set.bl} width={c} height={c} />
        <TileRow src={set.bc} height={c} count={nH} />
        <BleedImage src={set.br} width={c} height={c} />
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

/**
 * The surface of a small raised pill (fixed height 44, any width), for tool buttons and sidebar items. Same rules as
 * PanelSurface: the fading layers fill the whole picture; `tone` ('light' | 'dark' | 'raild' | 'raill') picks the
 * artwork; `baseOpacity` hides the raised look at rest.
 */
export function PillSurface({ anim, tone, baseOpacity }) {
  const d = SOFT_PILL_DIMS;
  const box = { position: 'absolute', left: -d.margin, right: -d.margin, top: -d.margin, height: d.imgH };
  if (anim) {
    const o = layerOpacities(anim, baseOpacity);
    const fill = StyleSheet.absoluteFill;
    return (
      <Animated.View pointerEvents="none" style={[box, popStyle(anim)]}>
        <Animated.View style={[fill, { opacity: o.raised }]}><PillLayer tone={tone} /></Animated.View>
        {anim.live ? <Animated.View style={[fill, { opacity: o.pressed }]}><PillLayer tone={tone} state="p" /></Animated.View> : null}
        {o.dent && anim.live ? <Animated.View style={[fill, { opacity: o.dent }]}><PillLayer tone={tone} state="d" /></Animated.View> : null}
      </Animated.View>
    );
  }
  return <View pointerEvents="none" style={box}><PillLayer tone={tone} /></View>;
}

function PillLayer({ tone, state = '' }) {
  const { isDark } = useTheme();
  const t = tone || (isDark ? 'dark' : 'light');
  const set = SOFT_PILL[t + state];
  const d = SOFT_PILL_DIMS;
  if (Platform.OS === 'ios') {
    return (
      <Image
        source={SOFT_FULL[t][state === 'p' ? 'pillp' : state === 'd' ? 'pilld' : 'pill']}
        style={StyleSheet.absoluteFill}
        capInsets={{ top: 0, left: d.capW, bottom: 0, right: d.capW }}
        resizeMode="stretch"
      />
    );
  }
  return <PillTiles set={set} d={d} />;
}

function PillTiles({ set, d }) {
  const [w, setW] = useState(0);
  const n = w ? Math.max(1, Math.ceil((w - 2 * d.capW) / TILE)) : 1;
  return (
    <View style={[StyleSheet.absoluteFill, { flexDirection: 'row' }]} onLayout={(e) => setW((cur) => (Math.ceil(cur / 64) === Math.ceil(e.nativeEvent.layout.width / 64) ? cur : e.nativeEvent.layout.width))}>
      <BleedImage src={set.L} width={d.capW} height={d.imgH} />
      <TileRow src={set.M} height={d.imgH} count={n} />
      <BleedImage src={set.R} width={d.capW} height={d.imgH} />
    </View>
  );
}

const styles = StyleSheet.create({ abs: { position: 'absolute' } });

/**
 * A soft box with content: a raised slim panel (`kind="slim"`, pressable with `onPress`) or a pressed-in track
 * (`kind="slimw"` or "well"). `style` places it (margins, flex, width); `contentStyle` lays out what is inside
 * (padding, rows). It is as big as its content, never smaller than the panel's minimum.
 */
export function SoftBox({ kind = 'slim', onPress, selected, style, contentStyle, children, ...rest }) {
  const d = SOFT_PANEL_DIMS[kind];
  const [down, setDown] = useState(false);
  const anim = usePressAnim(down, selected);
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

/** The surface of the round 44dp button, to place inside a 44 x 44 box. Same rules as PanelSurface. */
export function PebbleSurface({ anim, tone, baseOpacity }) {
  const { isDark } = useTheme();
  const d = SOFT_PEBBLE_DIMS;
  const set = SOFT_PEBBLE[tone || (isDark ? 'dark' : 'light')];
  const o = layerOpacities(anim, baseOpacity);
  const box = { position: 'absolute', left: -d.margin, top: -d.margin, width: d.img, height: d.img };
  return (
    <Animated.View pointerEvents="none" style={[box, popStyle(anim)]}>
      <Animated.Image source={set.up} style={[StyleSheet.absoluteFill, { opacity: o.raised }]} fadeDuration={0} />
      {anim.live ? <Animated.Image source={set.down} style={[StyleSheet.absoluteFill, { opacity: o.pressed }]} fadeDuration={0} /> : null}
      {o.dent && anim.live ? <Animated.Image source={set.dent} style={[StyleSheet.absoluteFill, { opacity: o.dent }]} fadeDuration={0} /> : null}
    </Animated.View>
  );
}

/**
 * The round 44dp button: a raised pebble that sinks when pressed and springs back. `selected` keeps it dented (the
 * active sidebar item); `tone` picks the artwork.
 */
export function SoftPebble({ onPress, disabled, selected, tone, baseOpacity, style, children, ...rest }) {
  const [down, setDown] = useState(false);
  const anim = usePressAnim(down, selected);
  const d = SOFT_PEBBLE_DIMS;
  return (
    <Pressable
      {...rest}
      onPress={onPress}
      disabled={disabled}
      onPressIn={() => setDown(true)}
      onPressOut={() => setDown(false)}
      style={[{ width: d.body, height: d.body, position: 'relative' }, style, disabled && { opacity: 0.5 }]}
    >
      <PebbleSurface anim={anim} tone={tone} baseOpacity={baseOpacity} />
      <Animated.View style={[{ width: d.body, height: d.body, alignItems: 'center', justifyContent: 'center', position: 'relative' }, pressShift(anim)]}>
        {children}
      </Animated.View>
    </Pressable>
  );
}

export default SoftPanel;
