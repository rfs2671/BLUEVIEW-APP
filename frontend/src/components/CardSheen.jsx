import React, { useEffect, useRef, useState } from 'react';
import { View, StyleSheet, Animated, Easing, Platform, AccessibilityInfo } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useTheme } from '../context/ThemeContext';
import { withAlpha } from '../styles/semanticColors';

/**
 * The card SHEEN: the one accent every card shares. A faint wash falling from the top edge and a hairline highlight
 * that fades out at both of its ends, so the card reads as a material catching light rather than a box with a stripe.
 * Each theme takes the other theme's tone (theme.js `sheen`): dark cards the light theme's beige, light cards the dark
 * theme's blue.
 *
 * It is purely decorative. It paints over the card's own fill, takes no touches (`pointerEvents: 'none'`) and is hidden
 * from assistive tech, so a card behaves exactly as it did without it.
 *
 * IT ANSWERS YOU. When `active` (hovered or pressed) the card lights up:
 *   - the hairline thickens to a 3px line and stretches from ~80% of the width to all of it;
 *   - a bright highlight sweeps along it, left to right, once;
 *   - the wash beneath it doubles.
 * A press is held for HOLD ms after the finger lifts, so a quick tap still shows the whole of it. With `intro`, the card
 * plays the same thing once, a beat after it appears (a phone has no hover, so this is how a screen announces itself).
 *
 * Everything animates transform and opacity only, eases out, and re-targets from wherever it is. Under reduced motion
 * nothing moves: the card just takes the lit state while `active` and drops it after.
 *
 * `radius` is the card's corner radius: the overlay rounds its own top corners so it never needs the card to clip, and
 * a card that casts an iOS shadow cannot clip.
 * `depth` is how far the wash falls. A tall card takes the default; a short one (a 40px button) passes a smaller depth
 * so the wash does not cover it.
 */

const REST_SCALE = 0.8;
const IN_MS = 260;
const OUT_MS = 380;
const SWEEP_MS = 640;
const HOLD_MS = 420;
const INTRO_MS = 360;
const THICK = 3;

function useReduceMotion() {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    let off = () => {};
    if (Platform.OS === 'web') {
      const mq = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
      if (mq) {
        setReduce(!!mq.matches);
        const on = (e) => setReduce(!!e.matches);
        if (mq.addEventListener) { mq.addEventListener('change', on); off = () => mq.removeEventListener('change', on); }
      }
    } else if (AccessibilityInfo && AccessibilityInfo.isReduceMotionEnabled) {
      AccessibilityInfo.isReduceMotionEnabled().then((v) => setReduce(!!v)).catch(() => {});
    }
    return off;
  }, []);
  return reduce;
}

export default function CardSheen({ radius = 14, depth = 46, active = false, intro = false }) {
  const { colors } = useTheme();
  const reduce = useReduceMotion();
  const native = Platform.OS !== 'web';
  const lit = useRef(new Animated.Value(0)).current;     // 0 at rest, 1 lit (hover / press)
  const pulse = useRef(new Animated.Value(0)).current;   // the intro's 0 -> 1 -> 0
  const sweep = useRef(new Animated.Value(0)).current;   // 0 -> 1 along the line, once per lighting
  const [width, setWidth] = useState(0);
  const [held, setHeld] = useState(false);
  const introDelay = useRef(Math.random() * 220).current;

  // A press is held a moment after it ends so a quick tap still shows the whole animation.
  useEffect(() => {
    if (active) { setHeld(true); return undefined; }
    const id = setTimeout(() => setHeld(false), HOLD_MS);
    return () => clearTimeout(id);
  }, [active]);
  const on = active || held;

  useEffect(() => {
    if (reduce) { lit.setValue(on ? 1 : 0); return undefined; }
    const run = Animated.timing(lit, {
      toValue: on ? 1 : 0,
      duration: on ? IN_MS : OUT_MS,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: native,
    });
    run.start();
    return () => run.stop();
  }, [on, reduce, lit, native]);

  // The highlight crosses the line each time the card lights up.
  useEffect(() => {
    if (!on || reduce) return undefined;
    sweep.setValue(0);
    const run = Animated.timing(sweep, { toValue: 1, duration: SWEEP_MS, easing: Easing.inOut(Easing.cubic), useNativeDriver: native });
    run.start();
    return () => run.stop();
  }, [on, reduce, sweep, native]);

  // The intro: once, a beat after the card appears.
  useEffect(() => {
    if (!intro || reduce) return undefined;
    const run = Animated.sequence([
      Animated.delay(120 + introDelay),
      Animated.parallel([
        Animated.timing(pulse, { toValue: 1, duration: INTRO_MS, easing: Easing.out(Easing.cubic), useNativeDriver: native }),
        Animated.timing(sweep, { toValue: 1, duration: SWEEP_MS, easing: Easing.inOut(Easing.cubic), useNativeDriver: native }),
      ]),
      Animated.timing(pulse, { toValue: 0, duration: OUT_MS, easing: Easing.out(Easing.cubic), useNativeDriver: native }),
    ]);
    sweep.setValue(0);
    run.start();
    return () => run.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sheen = colors.sheen;
  if (!sheen) return null;
  const level = Animated.add(lit, pulse).interpolate({ inputRange: [0, 1, 2], outputRange: [0, 1, 1], extrapolate: 'clamp' });
  const wash = [withAlpha(sheen.color, sheen.wash), withAlpha(sheen.color, 0)];
  const washMore = [withAlpha(sheen.color, sheen.wash * 1.2), withAlpha(sheen.color, 0)];
  const line = [withAlpha(sheen.color, 0), sheen.color, sheen.color, withAlpha(sheen.color, 0)];
  const scaleX = level.interpolate({ inputRange: [0, 1], outputRange: [REST_SCALE, 1] });
  const bar = Math.max(40, width * 0.26);
  const sweepX = sweep.interpolate({ inputRange: [0, 1], outputRange: [-bar, width] });
  const sweepOpacity = sweep.interpolate({ inputRange: [0, 0.12, 0.85, 1], outputRange: [0, 1, 1, 0] });

  return (
    <View
      pointerEvents="none"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      onLayout={(e) => setWidth(e.nativeEvent.layout.width)}
      style={[styles.layer, { height: Math.max(depth, THICK), borderTopLeftRadius: radius, borderTopRightRadius: radius }]}
    >
      <LinearGradient colors={wash} start={{ x: 0.5, y: 0 }} end={{ x: 0.5, y: 1 }} style={[styles.fill, { height: depth }]} />
      <Animated.View style={[styles.fill, { height: depth, opacity: level }]}>
        <LinearGradient colors={washMore} start={{ x: 0.5, y: 0 }} end={{ x: 0.5, y: 1 }} style={StyleSheet.absoluteFill} />
      </Animated.View>
      {/* the resting hairline */}
      <View style={styles.hairline}>
        <View style={[StyleSheet.absoluteFill, { transform: [{ scaleX: REST_SCALE }] }]}>
          <LinearGradient colors={line} locations={[0, 0.22, 0.78, 1]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={StyleSheet.absoluteFill} />
        </View>
      </View>
      {/* the lit line: thick, full width, fading in as the card lights up */}
      <Animated.View style={[styles.thick, { opacity: level, transform: [{ scaleX }] }]}>
        <LinearGradient colors={line} locations={[0, 0.18, 0.82, 1]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={StyleSheet.absoluteFill} />
      </Animated.View>
      {/* the highlight that crosses it */}
      <Animated.View style={[styles.bar, { width: bar, opacity: sweepOpacity, transform: [{ translateX: sweepX }] }]}>
        <LinearGradient
          colors={[withAlpha('#FFFFFF', 0), withAlpha('#FFFFFF', 0.9), withAlpha('#FFFFFF', 0)]}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 0 }}
          style={StyleSheet.absoluteFill}
        />
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  layer: { position: 'absolute', top: 0, left: 0, right: 0, overflow: 'hidden' },
  fill: { position: 'absolute', top: 0, left: 0, right: 0 },
  hairline: { position: 'absolute', top: 0, left: 0, right: 0, height: 1 },
  thick: { position: 'absolute', top: 0, left: 0, right: 0, height: THICK },
  bar: { position: 'absolute', top: 0, left: 0, height: THICK },
});
