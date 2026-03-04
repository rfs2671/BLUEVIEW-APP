import React, { useState } from 'react';
import { View, StyleSheet, Pressable, Text, Platform } from 'react-native';
import { BlurView } from 'expo-blur';
import { LinearGradient } from 'expo-linear-gradient';
import { colors, borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';

/**
 * Helper: returns platform shadow styles from the colors.shadow token.
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

/**
 * GlassCard - Glassmorphism card component
 *
 * Light mode: vertical gradient (white/90 → blue-100/70), NO border, soft shadow
 * Dark  mode: flat bg, 1px border, unchanged
 */
export const GlassCard = ({ children, style, onPress, intensity = 20, hoverEffect = true, variant = 'default' }) => {
  const [isHovered, setIsHovered] = useState(false);
  const { isDark } = useTheme();
  const CardWrapper = onPress ? Pressable : View;

  const cardProps = onPress ? {
    onPress,
    onHoverIn: () => setIsHovered(true),
    onHoverOut: () => setIsHovered(false),
  } : {
    onMouseEnter: () => hoverEffect && setIsHovered(true),
    onMouseLeave: () => hoverEffect && setIsHovered(false),
  };

  const blurIntensity = variant === 'modal' ? 80 : intensity;

  const lightGradientColors = [
    'rgba(255, 255, 255, 0.90)',
    colors.glass.cardGradientEnd || 'rgba(219, 234, 254, 0.70)',
  ];

  return (
    <CardWrapper
      {...cardProps}
      style={[
        styles.container,
        glassShadow(),
        style,
        isHovered && hoverEffect && styles.cardHovered,
      ]}
    >
      <BlurView intensity={blurIntensity} tint={isDark ? 'dark' : 'light'} style={styles.blur}>
        {isDark || variant === 'modal' ? (
          <View style={[
            styles.content,
            { backgroundColor: variant === 'modal' ? 'transparent' : colors.glass.background },
          ]}>
            {children}
          </View>
        ) : (
          <LinearGradient
            colors={lightGradientColors}
            start={{ x: 0.5, y: 0 }}
            end={{ x: 0.5, y: 1 }}
            style={styles.content}
          >
            {children}
          </LinearGradient>
        )}
      </BlurView>
      {/* Border overlay — dark mode only */}
      {isDark && (
        <View style={[
          styles.borderOverlay,
          isHovered && hoverEffect && { borderColor: colors.glass.borderHover },
        ]} />
      )}
    </CardWrapper>
  );
};

/**
 * StatCard - Statistics card
 *
 * Light mode: vertical gradient, NO border
 * Dark  mode: flat bg, 1px border
 */
export const StatCard = ({ children, style, onPress }) => {
  const [isHovered, setIsHovered] = useState(false);
  const { isDark } = useTheme();
  const CardWrapper = onPress ? Pressable : View;

  const cardProps = onPress ? {
    onPress,
    onHoverIn: () => setIsHovered(true),
    onHoverOut: () => setIsHovered(false),
  } : {
    onMouseEnter: () => setIsHovered(true),
    onMouseLeave: () => setIsHovered(false),
  };

  const lightGradientColors = [
    'rgba(255, 255, 255, 0.90)',
    colors.glass.cardGradientEnd || 'rgba(219, 234, 254, 0.70)',
  ];

  return (
    <CardWrapper
      {...cardProps}
      style={[
        isDark ? styles.statContainerDark : styles.statContainerLight,
        glassShadow(),
        style,
        isHovered && {
          backgroundColor: colors.glass.backgroundHover,
          ...(isDark && { borderColor: colors.glass.borderHover }),
          transform: [{ scale: 1.03 }, { translateY: -4 }],
        },
      ]}
    >
      {isDark ? (
        <View style={[styles.statContent, { backgroundColor: colors.glass.background }]}>
          {children}
        </View>
      ) : (
        <LinearGradient
          colors={lightGradientColors}
          start={{ x: 0.5, y: 0 }}
          end={{ x: 0.5, y: 1 }}
          style={styles.statContent}
        >
          {children}
        </LinearGradient>
      )}
    </CardWrapper>
  );
};

/**
 * GlassListItem - Interactive list item
 */
export const GlassListItem = ({ children, title, subtitle, leftIcon, rightIcon, showBorder, style, onPress, disabled }) => {
  const [isHovered, setIsHovered] = useState(false);
  const { isDark } = useTheme();

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
          backgroundColor: colors.glass.backgroundHover,
          ...(isDark && { borderColor: colors.glass.borderHover }),
          transform: [{ scale: 1.01 }, { translateY: -2 }],
        },
        pressed && styles.listItemPressed,
        disabled && styles.listItemDisabled,
        showBorder && styles.listItemBorder,
        style,
      ]}
    >
      {children || (
        <View style={{ flexDirection: 'row', alignItems: 'center', flex: 1 }}>
          {leftIcon && <View style={{ marginRight: 12 }}>{leftIcon}</View>}
          <View style={{ flex: 1 }}>
            {title && <Text style={{ color: colors.text.primary, fontSize: 16, fontWeight: '500' }}>{title}</Text>}
            {subtitle && <Text style={{ color: colors.text.muted, fontSize: 13, marginTop: 2 }}>{subtitle}</Text>}
          </View>
          {rightIcon && <View style={{ marginLeft: 12 }}>{rightIcon}</View>}
        </View>
      )}
    </Pressable>
  );
};

/**
 * IconPod - Circular icon container
 *
 * Automatically re-colors child icons to colors.iconPod.iconColor.
 */
export const IconPod = ({ children, size = 52, style }) => {
  const themedChildren = React.Children.map(children, (child) => {
    if (!React.isValidElement(child)) return child;
    if (child.props.preserveColor) return child;
    return React.cloneElement(child, {
      color: colors.iconPod.iconColor,
    });
  });

  return (
    <View style={[
      styles.iconPod,
      {
        width: size,
        height: size,
        backgroundColor: colors.iconPod.background,
        borderColor: colors.iconPod.border,
      },
      style,
    ]}>
      {themedChildren}
    </View>
  );
};

const styles = StyleSheet.create({
  /* ── GlassCard ──────────────────────────────────────────────────────────── */
  container: {
    borderRadius: borderRadius.xxl,
    overflow: 'hidden',
    position: 'relative',
    transition: 'all 0.2s ease',
  },
  blur: {
    overflow: 'hidden',
    borderRadius: borderRadius.xxl,
  },
  content: {
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
  statContainerDark: {
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    overflow: 'hidden',
    transition: 'all 0.2s ease',
  },
  statContainerLight: {
    borderRadius: borderRadius.xl,
    borderWidth: 0,
    overflow: 'hidden',
    transition: 'all 0.2s ease',
  },
  statContent: {
    padding: spacing.lg,
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
