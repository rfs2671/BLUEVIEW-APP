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
        isHovered && {
          backgroundColor: colors.glass.backgroundHover,
          borderColor: colors.glass.borderHover,
          transform: [{ scale: 1.03 }],
        },
        pressed && styles.pressed,
        disabled && styles.disabled,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator size="small" color={colors.text.primary} />
      ) : (
        <View style={styles.content}>
          {icon && <View style={styles.iconLeft}>{icon}</View>}
          <Text style={[styles.text, textStyle]}>{title}</Text>
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
