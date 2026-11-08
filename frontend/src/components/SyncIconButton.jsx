import React, { useEffect } from 'react';
import { Pressable, View, Text, StyleSheet } from 'react-native';
import Svg, { Circle } from 'react-native-svg';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  useAnimatedProps,
  withTiming,
  withRepeat,
  withSequence,
  withSpring,
  withDelay,
  cancelAnimation,
  Easing,
} from 'react-native-reanimated';
import { RefreshCw, Check } from 'lucide-react-native';
import { useTheme } from '../context/ThemeContext';
import { semantic, withAlpha } from '../styles/semanticColors';

const AnimatedCircle = Animated.createAnimatedComponent(Circle);

/**
 * A sync button that shows its own progress, start to finish.
 *
 *   idle      the refresh icon
 *   syncing   a ring begins to travel around the button while the arrows turn:
 *             something is visibly in progress
 *   success   the ring closes into a full green circle, the arrows swap for a
 *             check that pops in, and a ripple goes out: unmistakably done
 *   error     the ring closes red and the button shakes
 *
 * The caller owns `status` and sets it back to 'idle' after a moment.
 */
export default function SyncIconButton({
  status = 'idle',
  onPress,
  disabled = false,
  size = 40,
  badge = 0,
  accessibilityLabel = 'Sync',
  style,
}) {
  const { colors } = useTheme();

  const R = size / 2 - 2;
  const C = 2 * Math.PI * R;
  const ringColor =
    status === 'success' ? semantic.verified
      : status === 'error' ? semantic.critical
        : (colors.aura && colors.aura.color) || '#78ACD6';

  const sweep = useSharedValue(0);      // fraction of the ring drawn, 0..1
  const ringSpin = useSharedValue(0);   // degrees the ring has travelled
  const ringOpacity = useSharedValue(0);
  const arrows = useSharedValue(0);     // degrees the arrows have turned
  const done = useSharedValue(0);       // 0 arrows, 1 check
  const ripple = useSharedValue(0);     // 0 -> 1 once, on success
  const shake = useSharedValue(0);

  useEffect(() => {
    if (status === 'syncing') {
      cancelAnimation(ringSpin); cancelAnimation(arrows);
      done.value = withTiming(0, { duration: 120 });
      ripple.value = 0;
      ringSpin.value = 0;
      arrows.value = 0;
      sweep.value = withTiming(0.3, { duration: 200 });
      ringOpacity.value = withTiming(1, { duration: 150 });
      ringSpin.value = withRepeat(withTiming(360, { duration: 900, easing: Easing.linear }), -1, false);
      arrows.value = withRepeat(withTiming(360, { duration: 800, easing: Easing.inOut(Easing.cubic) }), -1, false);
    } else if (status === 'success') {
      cancelAnimation(ringSpin); cancelAnimation(arrows);
      // finish the turn in progress, close the ring, then swap in the check
      arrows.value = withTiming(360, { duration: 320, easing: Easing.out(Easing.cubic) });
      sweep.value = withTiming(1, { duration: 320, easing: Easing.out(Easing.cubic) });
      ringOpacity.value = withSequence(withTiming(1, { duration: 120 }), withDelay(900, withTiming(0, { duration: 350 })));
      done.value = withDelay(260, withSpring(1, { damping: 9, stiffness: 180 }));
      ripple.value = withDelay(300, withTiming(1, { duration: 650, easing: Easing.out(Easing.cubic) }));
    } else if (status === 'error') {
      cancelAnimation(ringSpin); cancelAnimation(arrows);
      arrows.value = withTiming(360, { duration: 260, easing: Easing.out(Easing.cubic) });
      sweep.value = withTiming(1, { duration: 260 });
      ringOpacity.value = withSequence(withTiming(1, { duration: 100 }), withDelay(1000, withTiming(0, { duration: 300 })));
      shake.value = withSequence(
        withTiming(-4, { duration: 60 }), withTiming(4, { duration: 80 }),
        withTiming(-3, { duration: 70 }), withTiming(3, { duration: 70 }), withTiming(0, { duration: 60 }),
      );
    } else {
      cancelAnimation(ringSpin); cancelAnimation(arrows);
      ringOpacity.value = withTiming(0, { duration: 160 });
      done.value = withTiming(0, { duration: 220 });
      sweep.value = withTiming(0, { duration: 160 });
      arrows.value = 0;
      ripple.value = 0;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  const ringBox = useAnimatedStyle(() => ({
    opacity: ringOpacity.value,
    transform: [{ rotate: `${ringSpin.value - 90}deg` }],
  }), [ringOpacity, ringSpin]);
  const ringProps = useAnimatedProps(() => ({
    strokeDashoffset: C * (1 - sweep.value),
  }), [sweep]);
  const arrowStyle = useAnimatedStyle(() => ({
    opacity: 1 - done.value,
    transform: [{ rotate: `${arrows.value}deg` }, { scale: 1 - 0.3 * done.value }],
  }), [arrows, done]);
  const checkStyle = useAnimatedStyle(() => ({
    opacity: done.value > 1 ? 1 : done.value,
    transform: [{ scale: 0.4 + 0.6 * done.value }],
  }), [done]);
  const rippleStyle = useAnimatedStyle(() => ({
    opacity: ripple.value <= 0 ? 0 : 0.55 * (1 - ripple.value),
    transform: [{ scale: 1 + 0.9 * ripple.value }],
  }), [ripple]);
  const shakeStyle = useAnimatedStyle(() => ({ transform: [{ translateX: shake.value }] }), [shake]);

  const iconColor =
    status === 'success' ? semantic.verified
      : status === 'error' ? semantic.critical
        : status === 'syncing' ? colors.text.primary
          : colors.text.secondary;

  const label = status === 'success' ? 'Synced' : status === 'syncing' ? 'Syncing' : status === 'error' ? 'Sync failed' : accessibilityLabel;

  return (
    <Animated.View style={shakeStyle}>
      <Pressable
        onPress={onPress}
        disabled={disabled || status === 'syncing'}
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityLiveRegion="polite"
        accessibilityState={{ busy: status === 'syncing', disabled }}
        style={({ pressed }) => [
          styles.btn,
          {
            width: size,
            height: size,
            borderRadius: size / 2,
            backgroundColor: colors.glass.background,
            borderColor: colors.glass.border,
          },
          pressed && { opacity: 0.7 },
          disabled && status !== 'syncing' && { opacity: 0.45 },
          style,
        ]}
      >
        <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, { borderRadius: size / 2, borderWidth: 1.5, borderColor: semantic.verified }, rippleStyle]} />
        <Animated.View pointerEvents="none" style={[styles.ring, { width: size, height: size }, ringBox]}>
          <Svg width={size} height={size}>
            <AnimatedCircle
              cx={size / 2}
              cy={size / 2}
              r={R}
              stroke={ringColor}
              strokeWidth={2.2}
              strokeLinecap="round"
              fill="none"
              strokeDasharray={`${C} ${C}`}
              animatedProps={ringProps}
            />
          </Svg>
        </Animated.View>
        <Animated.View style={[styles.icon, arrowStyle]}>
          <RefreshCw size={size * 0.45} strokeWidth={1.7} color={iconColor} />
        </Animated.View>
        <Animated.View style={[styles.icon, checkStyle]}>
          <Check size={size * 0.5} strokeWidth={2.4} color={semantic.verified} />
        </Animated.View>
        {badge > 0 && (
          <View style={[styles.badge, { backgroundColor: colors.warning }]}>
            <Text style={styles.badgeText}>{badge > 9 ? '9+' : badge}</Text>
          </View>
        )}
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  btn: { alignItems: 'center', justifyContent: 'center', borderWidth: 1 },
  ring: { position: 'absolute', left: -1, top: -1 },
  icon: { position: 'absolute', alignItems: 'center', justifyContent: 'center' },
  badge: {
    position: 'absolute',
    top: -4,
    right: -4,
    minWidth: 16,
    height: 16,
    borderRadius: 8,
    paddingHorizontal: 3,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: { fontSize: 10, fontWeight: '700', color: '#111' },
});
