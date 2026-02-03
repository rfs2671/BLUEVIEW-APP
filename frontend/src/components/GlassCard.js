import React, { useState } from 'react';
import { View, StyleSheet, Pressable } from 'react-native';
import { BlurView } from 'expo-blur';
import { colors, borderRadius, spacing } from '../styles/theme';

/**
 * GlassCard - Glassmorphism card component with hover support
 */
export const GlassCard = ({ children, style, onPress, intensity = 20, hoverEffect = true, variant = 'default' }) => {
  const [isHovered, setIsHovered] = useState(false);
  const CardWrapper = onPress ? Pressable : View;
  
  const cardProps = onPress ? {
    onPress,
    onHoverIn: () => setIsHovered(true),
    onHoverOut: () => setIsHovered(false),
  } : {
    onMouseEnter: () => hoverEffect && setIsHovered(true),
    onMouseLeave: () => hoverEffect && setIsHovered(false),
  };
  
  // Use higher opacity for modals
  const contentStyle = variant === 'modal' ? styles.contentModal : styles.content;
  const blurIntensity = variant === 'modal' ? 80 : intensity;
  
  return (
    <CardWrapper
      {...cardProps}
      style={[
        styles.container,
        style,
        isHovered && hoverEffect && styles.cardHovered,
      ]}
    >
      <BlurView intensity={blurIntensity} tint="dark" style={styles.blur}>
        <View style={contentStyle}>{children}</View>
      </BlurView>
      <View style={[styles.border, isHovered && hoverEffect && styles.borderHovered]} />
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
        style,
        isHovered && styles.statHovered,
      ]}
    >
      <View style={styles.statContent}>{children}</View>
    </CardWrapper>
  );
};

/**
 * GlassListItem - Interactive list item with hover support
 */
export const GlassListItem = ({ children, style, onPress, disabled }) => {
  const [isHovered, setIsHovered] = useState(false);
  
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={({ pressed }) => [
        styles.listItem,
        isHovered && styles.listItemHovered,
        pressed && styles.listItemPressed,
        disabled && styles.listItemDisabled,
        style,
      ]}
    >
      {children}
    </Pressable>
  );
};

/**
 * IconPod - Circular icon container
 */
export const IconPod = ({ children, size = 52, style }) => (
  <View style={[styles.iconPod, { width: size, height: size }, style]}>
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
  contentModal: {
    backgroundColor: 'rgba(255, 255, 255, 0.0)',
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
  borderHovered: {
    borderColor: 'rgba(255, 255, 255, 0.3)',
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
  statHovered: {
    backgroundColor: 'rgba(255, 255, 255, 0.18)',
    borderColor: 'rgba(255, 255, 255, 0.35)',
    transform: [{ scale: 1.03 }, { translateY: -4 }],
  },
  statContent: {
    padding: spacing.lg,
  },
  iconPod: {
    borderRadius: borderRadius.full,
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: colors.glass.border,
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
  listItemHovered: {
    backgroundColor: 'rgba(255, 255, 255, 0.15)',
    borderColor: 'rgba(255, 255, 255, 0.3)',
    transform: [{ scale: 1.01 }, { translateY: -2 }],
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
