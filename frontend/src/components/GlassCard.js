import React, { useState } from 'react';
import { View, StyleSheet, Pressable, Text, Platform } from 'react-native';
import { BlurView } from 'expo-blur';
import { LinearGradient } from 'expo-linear-gradient';
import { colors, borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';
import { withAlpha } from '../styles/semanticColors';

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
   Light: white → paper tint
   ────────────────────────────────────────────────────────────────────────── */
const DARK_GRADIENT = [
  withAlpha('#243746', 0.86),   // chip tone at top
  withAlpha('#1C2B38', 0.80),   // card tone at bottom
];

// The modal variant keeps the frost but draws a near-solid fill over it, so a dialog reads as the palette's card tone
// instead of the saturated tint the frost alone gives it.
const MODAL_DARK_GRADIENT = [withAlpha('#1C2B38', 0.94), withAlpha('#1C2B38', 0.94)];
const MODAL_LIGHT_GRADIENT = [withAlpha('#ffffff', 0.95), withAlpha('#ffffff', 0.95)];

const LIGHT_GRADIENT = [
  withAlpha('#ffffff', 0.84),   // white at top
  'rgba(250, 251, 248, 0.80)',   // paper at bottom
];

/* ═══════════════════════════════════════════════════════════════════════════════
   GlassCard
   ═══════════════════════════════════════════════════════════════════════════════ */
export const GlassCard = ({
  children,
  style,
  contentStyle,
  onPress,
  intensity = 20,
  hoverEffect = true,
  variant = 'default',
}) => {
  const [isHovered, setIsHovered] = useState(false);
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
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
  const gradientColors = variant === 'modal'
    ? (isDark ? MODAL_DARK_GRADIENT : MODAL_LIGHT_GRADIENT)
    : (isDark ? DARK_GRADIENT : LIGHT_GRADIENT);

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
      {/* The fill sits ABOVE the frost (it used to sit under it). expo-blur's web view applies saturate(180%) to everything
          behind it, which pushed the card's fill toward a saturated blue; drawn on top, the fill keeps the exact tone the
          palette names while the frost still shows through it. */}
      {/* Layer 1: frosted blur on web; on native we fall back to a
          plain semi-opaque View. expo-blur's native BlurView was
          throwing a render exception on device (the web JS shim is
          unaffected), and a plain View cannot crash. The fill is
          opaque enough to keep dark cards readable since the Layer-1
          dark gradient is near-transparent. Reversible. */}
      {Platform.OS === 'web' ? (
        <BlurView
          intensity={blurIntensity}
          tint={isDark ? 'dark' : 'light'}
          style={StyleSheet.absoluteFillObject}
        />
      ) : (
        <View
          style={[
            StyleSheet.absoluteFillObject,
            { backgroundColor: isDark ? withAlpha('#1C2B38', 0.6) : withAlpha('#ffffff', 0.5) },
          ]}
        />
      )}
      {/* Layer 2: gradient fills the entire card */}
      <LinearGradient
        colors={gradientColors}
        start={{ x: 0.5, y: 0 }}
        end={{ x: 0.5, y: 1 }}
        style={StyleSheet.absoluteFillObject}
      />
      {/* Layer 3: content. `contentStyle` (optional) overrides the default
          padding — e.g. narrow summary bubbles that can't afford 32px insets. */}
      <View style={[styles.cardContent, contentStyle]}>{children}</View>
      {/* Layer 4: border overlay — hairline in both themes (the concept draws one on paper too) */}
      <View
        style={[
          styles.borderOverlay,
          isHovered && hoverEffect && { borderColor: colors.glass.borderHover },
        ]}
      />
    </CardWrapper>
  );
};

/* ═══════════════════════════════════════════════════════════════════════════════
   StatCard
   ═══════════════════════════════════════════════════════════════════════════════ */
export const StatCard = ({ children, style, onPress }) => {
  const [isHovered, setIsHovered] = useState(false);
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
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
  contentStyle,
  onPress,
  disabled,
}) => {
  const [isHovered, setIsHovered] = useState(false);
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);

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
      {/* `contentStyle` (optional) overrides the default spacing.lg inset — for
          dense rows where a 24px inset per side eats the content width. */}
      <View style={[styles.listItemContent, contentStyle]}>
        {children || defaultContent}
      </View>
    </Pressable>
  );
};

/* ═══════════════════════════════════════════════════════════════════════════════
   IconPod
   ═══════════════════════════════════════════════════════════════════════════════ */
export const IconPod = ({ children, size = 52, style }) => {
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
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
          borderRadius: Math.round(size * 0.28),
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
function buildStyles(colors, isDark) {
  return StyleSheet.create({
  /* ── GlassCard ──────────────────────────────────────────────────────────── */
  cardContainer: {
    borderRadius: borderRadius.xxl,
    overflow: 'hidden',
    position: 'relative',
    transition: 'all 0.2s ease',
  },
  cardContent: {
    padding: spacing.md,
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
}
export default GlassCard;
