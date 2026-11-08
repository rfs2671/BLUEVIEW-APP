import React, { useRef } from 'react';
import { View, Pressable, StyleSheet } from 'react-native';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  withTiming,
  withSequence,
} from 'react-native-reanimated';
import { Moon, Sun } from 'lucide-react-native';
import { useTheme } from '../context/ThemeContext';
import { withAlpha } from '../styles/semanticColors';

/**
 * The light/dark switch for the desktop sidebar: a pill with a knob. Pressing it
 * stretches the knob as it slides across, and the new theme spreads out from the
 * knob (see ThemeContext.toggleThemeAnimated). The knob moves first and the
 * spread follows a beat later, so the switch is seen to do the work.
 *
 * The app remounts when the theme changes, so the knob is set to its final spot
 * here and the new copy simply starts there.
 */
const W = 56;
const H = 30;
const K = 22;
const PAD = 4;
const TRAVEL = W - PAD * 2 - K;

export default function ThemeSwitch() {
  const { colors, isDark, toggleThemeAnimated, themeForced } = useTheme();
  const ref = useRef(null);
  const pos = useSharedValue(isDark ? 0 : 1);   // 0 = knob left (dark), 1 = right (light)
  const stretch = useSharedValue(0);
  const press = useSharedValue(0);

  const knob = useAnimatedStyle(() => ({
    transform: [
      { translateX: TRAVEL * pos.value },
      { scaleX: 1 + 0.55 * stretch.value + 0.12 * press.value },
      { scaleY: 1 - 0.14 * stretch.value - 0.1 * press.value },
    ],
  }), [pos, stretch, press]);
  const sunStyle = useAnimatedStyle(() => ({ opacity: 0.85 * (1 - pos.value) }), [pos]);
  const moonStyle = useAnimatedStyle(() => ({ opacity: 0.85 * pos.value }), [pos]);

  if (themeForced) return null;

  const onPress = () => {
    const toLight = isDark;
    pos.value = withSpring(toLight ? 1 : 0, { damping: 15, stiffness: 300, mass: 0.7 });
    stretch.value = withSequence(withTiming(1, { duration: 110 }), withTiming(0, { duration: 240 }));
    const go = (x, y) => setTimeout(() => toggleThemeAnimated({ x, y }), 130);
    if (ref.current && ref.current.measureInWindow) {
      ref.current.measureInWindow((x, y, w, h) => go(x + w / 2, y + h / 2));
    } else {
      go(W / 2, H / 2);
    }
  };

  return (
    <View ref={ref} collapsable={false} style={{ width: W, height: H }}>
      <Pressable
        onPress={onPress}
        onPressIn={() => { press.value = withTiming(1, { duration: 90 }); }}
        onPressOut={() => { press.value = withTiming(0, { duration: 160 }); }}
        accessibilityRole="switch"
        accessibilityState={{ checked: !isDark }}
        accessibilityLabel="Light mode"
        style={[
          styles.track,
          { backgroundColor: withAlpha(colors.onBar, 0.12), borderColor: withAlpha(colors.onBar, 0.2) },
        ]}
      >
        <Animated.View style={[styles.slot, { left: PAD }, moonStyle]} pointerEvents="none">
          <Moon size={13} strokeWidth={1.8} color={colors.onBar} />
        </Animated.View>
        <Animated.View style={[styles.slot, { right: PAD }, sunStyle]} pointerEvents="none">
          <Sun size={13} strokeWidth={1.8} color={colors.onBar} />
        </Animated.View>
        <Animated.View style={[styles.knob, { left: PAD, backgroundColor: colors.barActive }, knob]} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  track: { width: W, height: H, borderRadius: H / 2, borderWidth: 1 },
  slot: { position: 'absolute', top: 0, bottom: 0, width: K, alignItems: 'center', justifyContent: 'center' },
  knob: {
    position: 'absolute',
    top: (H - K) / 2 - 1,
    width: K,
    height: K,
    borderRadius: K / 2,
    shadowColor: '#000',
    shadowOpacity: 0.3,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 1 },
    elevation: 3,
  },
});
