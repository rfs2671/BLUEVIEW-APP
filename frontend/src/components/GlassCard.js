/**
 * GlassCard.js
 * Place at: frontend/src/components/GlassCard.js
 *
 * FIX #1: Light mode gradient not filling the box.
 *   - containerLight now has backgroundColor fallback so there's never a gap
 *   - Removed BlurView from light mode (it was creating a translucent layer
 *     that showed the page background through the edges)
 *   - Gradient + content are direct children of the container
 */

import React, { useState } from 'react';
import { View, StyleSheet, Pressable, Text, Platform } from 'react-native';
import { BlurView } from 'expo-blur';
import { LinearGradient } from 'expo-linear-gradient';
import { colors, borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';

function glassShadow() {
  if (!colors.shadow) return {};
  const s = colors.shadow;
  if (Platform.OS === 'web') {
    return {
      boxShadow: `${s.offset.width}px ${s.offset.height}px ${s.radius}px ${s.color}`,
    };
  }
  return {
    shadowColor:   s.color,
    shadowOffset:  s.offset,
    shadowOpacity: s.opacity,
    shadowRadius:  s.radius,
    elevation:     6,
  };
}

const LIGHT_GRADIENT = [
  'rgba(255, 255, 255, 0.92)',
  'rgba(219, 234, 254, 0.65)',
];

/* ═══════════════════════════════════════════════════════════════════════════════
   GlassCard
   ═══════════════════════════════════════════════════════════════════════════════ */
export const GlassCard = ({
  children,
  style,
  onPress,
  intensity = 20,
  hoverEffect = true,
  variant = 'default',
}) => {
  const [isHovered, setIsHovered] = useState(false);
  const { isDark } = useTheme();
  const CardWrapper = onPress ? Pressable : View;

  const cardProps = onPress
    ? {
        onPress,
        onHoverIn: () => setIsHovered(true),
        onHoverOut: () => setIsHovered(false),
      }
    : {
        onMouseEnter: () => hoverEffect && setIsHovered(true),
        onMouseLeave: () => hoverEffect && setIsHovered(false),
      };

  const blurIntensity = variant === 'modal' ? 80 : intensity;

  if (isDark) {
    /* ── DARK MODE — unchanged ─────────────────────────────────────────── */
    return (
      <CardWrapper
        {...cardProps}
        style={[
          styles.containerDark,
          glassShadow(),
          style,
          isHovered && hoverEffect && styles.cardHovered,
        ]}
      >
        <BlurView
          intensity={blurIntensity}
          tint="dark"
          style={styles.blurDark}
        >
          <View
            style={[
              styles.contentPadded,
              {
                backgroundColor:
                  variant === 'modal'
                    ? 'transparent'
                    : colors.glass.background,
              },
            ]}
          >
            {children}
          </View>
        </BlurView>
        <View
          style={[
            styles.borderOverlay,
            isHovered && hoverEffect && { borderColor: colors.glass.borderHover },
          ]}
        />
      </CardWrapper>
    );
  }

  /* ── LIGHT MODE — gradient fills entire card edge-to-edge ─────────────── */
  return (
    <CardWrapper
      {...cardProps}
      style={[
        styles.containerLight,
        glassShadow(),
        style,
        isHovered && hoverEffect && styles.cardHovered,
      ]}
    >
      <LinearGradient
        colors={LIGHT_GRADIENT}
        start={{ x: 0, y: 0 }}
        end={{ x: 0.3, y: 1 }}
        style={styles.gradientFill}
      />
      {/* Content sits directly on top of gradient — no BlurView gap */}
      <View style={styles.contentPadded}>{children}</View>
    </CardWrapper>
  );
};

/* ═══════════════════════════════════════════════════════════════════════════════
   StatCard
   ═══════════════════════════════════════════════════════════════════════════════ */
export const StatCard = ({ children, style, onPress }) => {
  const [isHovered, setIsHovered] = useState(false);
  const { isDark } = useTheme();
  const CardWrapper = onPress ? Pressable : View;

  const cardProps = onPress
    ? {
        onPress,
        onHoverIn: () => setIsHovered(true),
        onHoverOut: () => setIsHovered(false),
      }
    : {
        onMouseEnter: () => setIsHovered(true),
        onMouseLeave: () => setIsHovered(false),
      };

  if (isDark) {
    return (
      <CardWrapper
        {...cardProps}
        style={[
          styles.statDark,
          glassShadow(),
          style,
          isHovered && {
            backgroundColor: colors.glass.backgroundHover,
            borderColor: colors.glass.borderHover,
            transform: [{ scale: 1.03 }, { translateY: -4 }],
          },
        ]}
      >
        <View
          style={[
            styles.statPadded,
            { backgroundColor: colors.glass.background },
          ]}
        >
          {children}
        </View>
      </CardWrapper>
    );
  }

  return (
    <CardWrapper
      {...cardProps}
      style={[
        styles.statLight,
        glassShadow(),
        style,
        isHovered && {
          transform: [{ scale: 1.03 }, { translateY: -4 }],
        },
      ]}
    >
      <LinearGradient
        colors={LIGHT_GRADIENT}
        start={{ x: 0, y: 0 }}
        end={{ x: 0.3, y: 1 }}
        style={styles.gradientFill}
      />
      <View style={styles.statPadded}>{children}</View>
    </CardWrapper>
  );
};

/* ═══════════════════════════════════════════════════════════════════════════════
   IconPod
   ═══════════════════════════════════════════════════════════════════════════════ */
export const IconPod = ({ children, size = 52, style }) => {
  const themedChildren = React.Children.map(children, (child) => {
    if (!React.isValidElement(child)) return child;
    if (child.props.preserveColor) return child;
    return React.cloneElement(child, {
      color: colors.iconPod.iconColor,
    });
  });

  return (
    <View
      style={[
        styles.iconPod,
        {
          width: size,
          height: size,
          backgroundColor: colors.iconPod.background,
          borderColor: colors.iconPod.border,
        },
        style,
      ]}
    >
      {themedChildren}
    </View>
  );
};

/* ═══════════════════════════════════════════════════════════════════════════════
   GlassListItem
   ═══════════════════════════════════════════════════════════════════════════════ */
export const GlassListItem = ({
  children,
  title,
  subtitle,
  leftIcon,
  rightIcon,
  showBorder,
  style,
  onPress,
  disabled,
}) => {
  const [isHovered, setIsHovered] = useState(false);
  const { isDark } = useTheme();

  const baseStyle = isDark ? styles.listItemDark : styles.listItemLight;

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={({ pressed }) => [
        baseStyle,
        style,
        isHovered && { backgroundColor: isDark ? colors.glass.backgroundHover : 'rgba(255,255,255,0.95)' },
        pressed && styles.listItemPressed,
        disabled && styles.listItemDisabled,
      ]}
    >
      {leftIcon && <View style={{ marginRight: spacing.md }}>{leftIcon}</View>}
      <View style={{ flex: 1 }}>
        {title && <Text style={{ fontSize: 16, fontWeight: '500', color: colors.text.primary }}>{title}</Text>}
        {subtitle && <Text style={{ fontSize: 13, color: colors.text.muted, marginTop: 2 }}>{subtitle}</Text>}
        {children}
      </View>
      {rightIcon && <View style={{ marginLeft: spacing.md }}>{rightIcon}</View>}
    </Pressable>
  );
};

/* ═══════════════════════════════════════════════════════════════════════════════
   STYLES
   ═══════════════════════════════════════════════════════════════════════════════ */
const styles = StyleSheet.create({
  /* ── GlassCard — dark ───────────────────────────────────────────────────── */
  containerDark: {
    borderRadius: borderRadius.xxl,
    overflow: 'hidden',
    position: 'relative',
    transition: 'all 0.2s ease',
  },
  blurDark: {
    overflow: 'hidden',
    borderRadius: borderRadius.xxl,
  },
  borderOverlay: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: borderRadius.xxl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    pointerEvents: 'none',
    transition: 'all 0.2s ease',
  },

  /* ── GlassCard — light ──────────────────────────────────────────────────── */
  containerLight: {
    borderRadius: borderRadius.xxl,
    overflow: 'hidden',
    position: 'relative',
    backgroundColor: 'rgba(255, 255, 255, 0.88)',  // ← fallback so no gap shows
    transition: 'all 0.2s ease',
  },

  /* ── Gradient fill — used in light mode cards ───────────────────────────── */
  gradientFill: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: borderRadius.xxl,
  },

  /* ── GlassCard — shared ─────────────────────────────────────────────────── */
  contentPadded: {
    padding: spacing.xl,
  },
  cardHovered: {
    transform: [{ scale: 1.01 }],
  },

  /* ── StatCard — dark ────────────────────────────────────────────────────── */
  statDark: {
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    overflow: 'hidden',
    transition: 'all 0.2s ease',
  },

  /* ── StatCard — light ───────────────────────────────────────────────────── */
  statLight: {
    borderRadius: borderRadius.xl,
    overflow: 'hidden',
    backgroundColor: 'rgba(255, 255, 255, 0.88)',
    transition: 'all 0.2s ease',
  },

  /* ── StatCard — shared padding ──────────────────────────────────────────── */
  statPadded: {
    padding: spacing.lg,
  },

  /* ── IconPod ────────────────────────────────────────────────────────────── */
  iconPod: {
    borderRadius: borderRadius.full,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },

  /* ── GlassListItem — dark ───────────────────────────────────────────────── */
  listItemDark: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    transition: 'all 0.2s ease',
  },

  /* ── GlassListItem — light ──────────────────────────────────────────────── */
  listItemLight: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 0,
    padding: spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    transition: 'all 0.2s ease',
  },

  listItemPressed: {
    opacity: 0.85,
    transform: [{ scale: 0.99 }],
  },
  listItemDisabled: {
    opacity: 0.5,
  },
});

export default GlassCard;
