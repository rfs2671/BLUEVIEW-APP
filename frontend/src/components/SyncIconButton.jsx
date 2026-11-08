import React, { useEffect } from 'react';
import { Pressable, View, Text, StyleSheet } from 'react-native';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withTiming,
  withRepeat,
  withSequence,
  withSpring,
  cancelAnimation,
  Easing,
} from 'react-native-reanimated';
import { RefreshCw } from 'lucide-react-native';
import { useTheme } from '../context/ThemeContext';
import { semantic, withAlpha } from '../styles/semanticColors';

/**
 * A sync button that shows its own progress instead of a pop-up.
 *
 *   idle      plain icon
 *   syncing   the icon spins (one turn per ~0.75s until the work is done)
 *   success   the turn in progress finishes, the icon pops and turns green
 *   error     the same finish, in red (the caller still explains what failed)
 *
 * The caller owns `status` and puts it back to 'idle' after a moment.
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
  const rotate = useSharedValue(0);
  const pop = useSharedValue(1);

  useEffect(() => {
    if (status === 'syncing') {
      cancelAnimation(rotate);
      rotate.value = 0;
      rotate.value = withRepeat(
        withTiming(360, { duration: 750, easing: Easing.inOut(Easing.cubic) }),
        -1,
        false,
      );
    } else if (status === 'success' || status === 'error') {
      // Finish the turn in progress rather than snapping, then settle.
      cancelAnimation(rotate);
      rotate.value = withTiming(360, { duration: 380, easing: Easing.out(Easing.cubic) });
      if (status === 'success') {
        pop.value = withSequence(withTiming(1.2, { duration: 140 }), withSpring(1, { damping: 8, stiffness: 160 }));
      }
    } else {
      cancelAnimation(rotate);
      rotate.value = 0; // 360 and 0 look the same, so this does not jump
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  const spin = useAnimatedStyle(() => ({
    transform: [{ rotate: `${rotate.value}deg` }, { scale: pop.value }],
  }));

  const tint =
    status === 'success' ? semantic.verified
      : status === 'error' ? semantic.critical
        : status === 'syncing' ? colors.text.primary
          : colors.text.secondary;

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || status === 'syncing'}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ busy: status === 'syncing', disabled }}
      style={({ pressed }) => [
        styles.btn,
        {
          width: size,
          height: size,
          borderRadius: size * 0.3,
          backgroundColor:
            status === 'success' ? withAlpha(semantic.verified, 0.14)
              : status === 'error' ? withAlpha(semantic.critical, 0.14)
                : colors.glass.background,
          borderColor:
            status === 'success' ? withAlpha(semantic.verified, 0.5)
              : status === 'error' ? withAlpha(semantic.critical, 0.5)
                : colors.glass.border,
        },
        pressed && { opacity: 0.7 },
        disabled && status !== 'syncing' && { opacity: 0.45 },
        style,
      ]}
    >
      <Animated.View style={spin}>
        <RefreshCw size={size * 0.45} strokeWidth={1.7} color={tint} />
      </Animated.View>
      {badge > 0 && (
        <View style={[styles.badge, { backgroundColor: colors.warning }]}>
          <Text style={styles.badgeText}>{badge > 9 ? '9+' : badge}</Text>
        </View>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btn: {
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
  },
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
