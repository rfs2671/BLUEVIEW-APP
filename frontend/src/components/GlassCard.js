import React, { useState } from 'react';
import { View, StyleSheet, Pressable, Text, Platform } from 'react-native';
import { BlurView } from 'expo-blur';
import { colors, borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';

/**
 * Helper: returns platform shadow styles from the colors.shadow token.
 * On web uses boxShadow, on native uses the shadow* props.
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
 * GlassCard - Glassmorphism card component with hover support
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
        <View style={[
          styles.content,
          variant === 'modal' && { backgroundColor: 'transparent' },
        ]}>
          {children}
        </View>
      </BlurView>
      <View style={[
        styles.border,
        isHovered && hoverEffect && { borderColor: colors.glass.borderHover },
      ]} />
    </CardWrapper>
  );
};

/**
 * StatCard - Statistics card with glass effect and hover support
 */
export const StatCard = ({ children, style, onPress }) => {
  const [isHovered, setIsHovered] = useState(false);
  const CardWrapper = onPress ? Pressable : View;

  const cardProps = onPress ? {
    onPress,
    onHoverIn: () => setIsHovered(true),
    onHoverOut: () => setIsHovered(false),
  } : {
    onMouseEnter: () => setIsHovered(true),
    onMouseLeave: () => setIsHovered(false),
  };

  return (
    <CardWrapper
      {...cardProps}
      style={[
        styles.statContainer,
        glassShadow(),
        style,
        isHovered && {
          backgroundColor: colors.glass.backgroundHover,
          borderColor: colors.glass.borderHover,
          transform: [{ scale: 1.03 }, { translateY: -4 }],
        },
      ]}
    >
      <View style={styles.statContent}>{children}</View>
    </CardWrapper>
  );
};

/**
 * GlassListItem - Interactive list item with hover support
 */
export const GlassListItem = ({ children, title, subtitle, leftIcon, rightIcon, showBorder, style, onPress, disabled }) => {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={({ pressed }) => [
        styles.listItem,
        glassShadow(),
        isHovered && {
          backgroundColor: colors.glass.backgroundHover,
          borderColor: colors.glass.borderHover,
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
 * Light mode: bg-[#1565C0]/10, border-[#1565C0]/20   (from colors.iconPod)
 * Dark  mode: transparent bg,  border from glass.border (from colors.iconPod)
 */
export const IconPod = ({ children, size = 52, style }) => (
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
    {children}
  </View>
);

const styles = StyleSheet.create({
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
    backgroundColor: colors.glass.background,
    padding: spacing.xl,
  },
  border: {
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
  statContainer: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    overflow: 'hidden',
    transition: 'all 0.2s ease',
  },
  statContent: {
    padding: spacing.lg,
  },
  iconPod: {
    borderRadius: borderRadius.full,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    // backgroundColor and borderColor set inline from colors.iconPod tokens
  },
  listItem: {
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
  listItemPressed: {
    opacity: 0.85,
    transform: [{ scale: 0.99 }],
  },
  listItemDisabled: {
    opacity: 0.5,
  },
});

export default GlassCard;
