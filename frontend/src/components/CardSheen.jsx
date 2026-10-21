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
 * `active` (hovered or pressed) plays a short answer: the hairline stretches from about 80% of the card's width to the
 * whole of it, brightening as it goes, and a second wash fades in beneath it. It runs on transform and opacity only,
 * eases out in 240ms, and re-targets from wherever it is if the pointer leaves mid-way. It is skipped (the card simply
 * changes state) when the device asks for reduced motion.
 *
 * `radius` is the card's corner radius: the overlay rounds its own top corners so it never needs the card to clip, and
 * a card that casts an iOS shadow cannot clip.
 * `depth` is how far the wash falls. A tall card takes the default; a short one (a 40px button) passes a smaller depth
 * so the wash does not cover it.
 */

const REST_SCALE = 0.8;
const DURATION = 240;

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

export default function CardSheen({ radius = 14, depth = 46, active = false }) {
  const { colors } = useTheme();
  const reduce = useReduceMotion();
  const t = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (reduce) { t.setValue(active ? 1 : 0); return undefined; }
    const run = Animated.timing(t, {
      toValue: active ? 1 : 0,
      duration: DURATION,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: Platform.OS !== 'web',
    });
    run.start();
    return () => run.stop();
  }, [active, reduce, t]);

  const sheen = colors.sheen;
  if (!sheen) return null;
  const wash = [withAlpha(sheen.color, sheen.wash), withAlpha(sheen.color, 0)];
  const washMore = [withAlpha(sheen.color, sheen.wash * 0.7), withAlpha(sheen.color, 0)];
  const line = [withAlpha(sheen.color, 0), sheen.color, sheen.color, withAlpha(sheen.color, 0)];
  const scaleX = t.interpolate({ inputRange: [0, 1], outputRange: [REST_SCALE, 1] });
  const lineOpacity = t.interpolate({ inputRange: [0, 1], outputRange: [0.85, 1] });

  return (
    <View
      pointerEvents="none"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[styles.layer, { height: depth, borderTopLeftRadius: radius, borderTopRightRadius: radius }]}
    >
      <LinearGradient colors={wash} start={{ x: 0.5, y: 0 }} end={{ x: 0.5, y: 1 }} style={StyleSheet.absoluteFill} />
      <Animated.View style={[StyleSheet.absoluteFill, { opacity: t }]}>
        <LinearGradient colors={washMore} start={{ x: 0.5, y: 0 }} end={{ x: 0.5, y: 1 }} style={StyleSheet.absoluteFill} />
      </Animated.View>
      <Animated.View style={[styles.hairline, { opacity: lineOpacity, transform: [{ scaleX }] }]}>
        <LinearGradient
          colors={line}
          locations={[0, 0.22, 0.78, 1]}
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
  // Full width, drawn at REST_SCALE so the hover only has to grow it.
  hairline: { position: 'absolute', top: 0, left: 0, right: 0, height: 1 },
});
