import React, { useState } from 'react';
import { View, StyleSheet, Pressable, Text, Platform } from 'react-native';
import { BlurView } from 'expo-blur';
import { LinearGradient } from 'expo-linear-gradient';
import { colors, borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';

/**
 * Platform shadow helper.
 */
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

/* ── Gradient presets ─────────────────────────────────────────────────────────
   Both modes use a vertical gradient so the fill covers every pixel.
   Dark:  subtle white-frosted glass
   Light: white → blue-100 tint
   ────────────────────────────────────────────────────────────────────────── */
const DARK_GRADIENT = [
  'rgba(255, 255, 255, 0.10)',   // brighter at top
  'rgba(255, 255, 255, 0.04)',   // fades toward bottom
];

const LIGHT_GRADIENT = [
  'rgba(255, 255, 255, 0.92)',   // white at top
  'rgba(219, 234, 254, 0.65)',   // blue-100 at bottom
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
  const gradientColors = isDark ? DARK_GRADIENT : LIGHT_GRADIENT;

  return (
    <CardWrapper
      {...cardProps}
      style={[
        styles.cardContainer,
        glassShadow(),
        style,
        isHovered && hoverEffect && styles.cardHovered,
      ]}
    >
      {/* Layer 1: gradient fills the entire card */}
      {variant !== 'modal' && (
        <LinearGradient
          colors={gradientColors}
          start={{ x: 0.5, y: 0 }}
          end={{ x: 0.5, y: 1 }}
          style={StyleSheet.absoluteFillObject}
        />
      )}
      {/* Layer 2: blur on top of gradient */}
      <BlurView
        intensity={blurIntensity}
        tint={isDark ? 'dark' : 'light'}
        style={StyleSheet.absoluteFillObject}
      />
      {/* Layer 3: content */}
      <View style={styles.cardContent}>{children}</View>
      {/* Layer 4: border overlay — dark only */}
      {isDark && (
        <View
          style={[
            styles.borderOverlay,
            isHovered && hoverEffect && { borderColor: colors.glass.borderHover },
          ]}
        />
      )}
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

  const gradientColors = isDark ? DARK_GRADIENT : LIGHT_GRADIENT;

  return (
    <CardWrapper
      {...cardProps}
      style={[
        isDark ? styles.statDark : styles.statLight,
        glassShadow(),
        style,
        isHovered && {
          ...(isDark && { borderColor: colors.glass.borderHover }),
          transform: [{ scale: 1.03 }, { translateY: -4 }],
        },
      ]}
    >
      <LinearGradient
        colors={gradientColors}
        start={{ x: 0.5, y: 0 }}
        end={{ x: 0.5, y: 1 }}
        style={StyleSheet.absoluteFillObject}
      />
      <View style={styles.statPadded}>{children}</View>
    </CardWrapper>
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

  const gradientColors = isDark ? DARK_GRADIENT : LIGHT_GRADIENT;

  const defaultContent = (
    <View style={{ flexDirection: 'row', alignItems: 'center', flex: 1 }}>
      {leftIcon && <View style={{ marginRight: 12 }}>{leftIcon}</View>}
      <View style={{ flex: 1 }}>
        {title && (
          <Text style={{ color: colors.text.primary, fontSize: 16, fontWeight: '500' }}>
            {title}
          </Text>
        )}
        {subtitle && (
          <Text style={{ color: colors.text.muted, fontSize: 13, marginTop: 2 }}>
            {subtitle}
          </Text>
        )}
      </View>
      {rightIcon && <View style={{ marginLeft: 12 }}>{rightIcon}</View>}
    </View>
  );

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={({ pressed }) => [
        isDark ? styles.listItemDark : styles.listItemLight,
        glassShadow(),
        isHovered && {
          ...(isDark && { borderColor: colors.glass.borderHover }),
          transform: [{ scale: 1.01 }, { translateY: -2 }],
        },
        pressed && styles.listItemPressed,
        disabled && styles.listItemDisabled,
        showBorder && styles.listItemBorder,
        style,
      ]}
    >
      <LinearGradient
        colors={gradientColors}
        start={{ x: 0.5, y: 0 }}
        end={{ x: 0.5, y: 1 }}
        style={StyleSheet.absoluteFillObject}
      />
      <View style={styles.listItemContent}>
        {children || defaultContent}
      </View>
    </Pressable>
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
   STYLES
   ═══════════════════════════════════════════════════════════════════════════════ */
const styles = StyleSheet.create({
  /* ── GlassCard ──────────────────────────────────────────────────────────── */
  cardContainer: {
    borderRadius: borderRadius.xxl,
    overflow: 'hidden',
    position: 'relative',
    transition: 'all 0.2s ease',
  },
  cardContent: {
    padding: spacing.xl,
  },
  borderOverlay: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: borderRadius.xxl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    pointerEvents: 'none',
    transition: 'all 0.2s ease',
  },
  cardHovered: {
    transform: [{ scale: 1.01 }],
  },

  /* ── StatCard ───────────────────────────────────────────────────────────── */
  statDark: {
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    overflow: 'hidden',
    transition: 'all 0.2s ease',
  },
  statLight: {
    borderRadius: borderRadius.xl,
    overflow: 'hidden',
    transition: 'all 0.2s ease',
  },
  statPadded: {
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm,
  },

  /* ── IconPod ────────────────────────────────────────────────────────────── */
  iconPod: {
    borderRadius: borderRadius.full,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },

  /* ── GlassListItem ─────────────────────────────────────────────────────── */
  listItemDark: {
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    overflow: 'hidden',
    transition: 'all 0.2s ease',
  },
  listItemLight: {
    borderRadius: borderRadius.xl,
    overflow: 'hidden',
    transition: 'all 0.2s ease',
  },
  listItemContent: {
    padding: spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
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
