import React, { useState } from 'react';
import { Pressable, Text, StyleSheet, ActivityIndicator, View } from 'react-native';
import { useTheme } from '../context/ThemeContext';
import { borderRadius, spacing } from '../styles/theme';

const GlassButton = ({
  title,
  onPress,
  loading = false,
  disabled = false,
  icon,
  iconRight,
  variant = 'default', // 'default' | 'icon'
  style,
  textStyle,
}) => {
  const [isHovered, setIsHovered] = useState(false);
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
  // The concept's filled action: the primary action of a screen. 'primary' is that; 'filled' is the same look under a name
  // that no other call site already uses. 'secondary' and the default stay the translucent glass button they always were.
  const filled = variant === 'primary' || variant === 'filled';

  if (variant === 'icon') {
    return (
      <Pressable
        onPress={onPress}
        disabled={disabled || loading}
        onHoverIn={() => setIsHovered(true)}
        onHoverOut={() => setIsHovered(false)}
        style={({ pressed }) => [
          styles.iconButton,
          isHovered && {
            backgroundColor: colors.glass.backgroundHover,
            borderColor: colors.glass.borderHover,
          },
          pressed && styles.pressed,
          disabled && styles.disabled,
          style,
        ]}
      >
        {loading ? (
          <ActivityIndicator size="small" color={colors.text.primary} />
        ) : (
          icon
        )}
      </Pressable>
    );
  }

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={({ pressed }) => [
        styles.button,
        filled && styles.buttonFilled,
        isHovered && {
          backgroundColor: filled ? colors.primary : colors.glass.backgroundHover,
          borderColor: filled ? colors.primary : colors.glass.borderHover,
          transform: [{ scale: 1.03 }],
        },
        pressed && styles.pressed,
        disabled && styles.disabled,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator size="small" color={filled ? colors.onPrimary : colors.text.primary} />
      ) : (
        <View style={styles.content}>
          {icon && <View style={styles.iconLeft}>{icon}</View>}
          <Text style={[styles.text, filled && styles.textFilled, textStyle]}>{title}</Text>
          {iconRight && <View style={styles.iconRight}>{iconRight}</View>}
        </View>
      )}
    </Pressable>
  );
};

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    button: {
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      paddingHorizontal: spacing.xl,
      paddingVertical: spacing.md,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      transition: 'all 0.2s ease',
    },
    buttonFilled: {
      // The app's tap floor is 44pt even for a compact action; padding alone would leave this ~33pt.
      minHeight: 44,
      backgroundColor: colors.primary,
      borderColor: colors.primary,
      borderRadius: borderRadius.md - 1,
      paddingHorizontal: spacing.md - 4,
      paddingVertical: spacing.sm - 1,
    },
    textFilled: {
      color: colors.onPrimary,
      fontSize: 13,
      fontWeight: '700',
    },
    iconButton: {
      width: 44,
      height: 44,
      borderRadius: borderRadius.full,
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
      alignItems: 'center',
      justifyContent: 'center',
      transition: 'all 0.2s ease',
    },
    content: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: spacing.sm,
    },
    text: {
      color: colors.text.primary,
      fontSize: 16,
      fontWeight: '500',
    },
    iconLeft: {
      marginRight: spacing.sm,
    },
    iconRight: {
      marginLeft: spacing.sm,
    },
    pressed: {
      opacity: 0.8,
      transform: [{ scale: 0.98 }],
    },
    disabled: {
      opacity: 0.5,
    },
  });
}

export default GlassButton;
