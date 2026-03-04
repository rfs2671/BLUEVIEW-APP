import React, { useState } from 'react';
import { View, StyleSheet, Pressable, Text, Platform } from 'react-native';
import { BlurView } from 'expo-blur';
import { LinearGradient } from 'expo-linear-gradient';
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
 *
 * Light mode: bg-gradient-to-br from-white/85 to-blue-100/70
 * Dark  mode: flat rgba(255,255,255,0.08)
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

  // Light mode gradient: from-white/85 → to-blue-100/70
  const lightGradientColors = [
    colors.glass.background,                             // rgba(255,255,255,0.85)
    colors.glass.cardGradientEnd || colors.glass.background,  // rgba(219,234,254,0.70)
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
          /* Dark mode / modal: flat bg */
          <View style={[
            styles.content,
            { backgroundColor: variant === 'modal' ? 'transparent' : colors.glass.background },
          ]}>
            {children}
          </View>
        ) : (
          /* Light mode: gradient bg from white/85 → blue-100/70 */
          <LinearGradient
            colors={lightGradientColors}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
            style={styles.content}
          >
            {children}
          </LinearGradient>
        )}
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
 *
 * Light mode: gradient bg from white/85 → blue-100/70
 * Dark  mode: flat glass background
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
    colors.glass.background,
    colors.glass.cardGradientEnd || colors.glass.background,
  ];

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
      {isDark ? (
        <View style={[styles.statContent, { backgroundColor: colors.glass.background }]}>{children}</View>
      ) : (
        <LinearGradient
          colors={lightGradientColors}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={styles.statContent}
        >
          {children}
        </LinearGradient>
      )}
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
 * Light mode: bg-[#1565C0]/10, border-[#1565C0]/20, icon color #1565C0
 * Dark  mode: transparent bg, glass border, icon color text.secondary
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
