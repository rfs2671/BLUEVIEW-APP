import React, { useState } from 'react';
import { TextInput, View, StyleSheet } from 'react-native';
import { colors, borderRadius, spacing } from '../styles/theme';

/**
 * GlassInput - Glassmorphism styled text input with hover/focus support
 */
const GlassInput = ({
  value,
  onChangeText,
  placeholder,
  secureTextEntry,
  keyboardType = 'default',
  autoCapitalize = 'none',
  leftIcon,
  rightIcon,
  style,
  inputStyle,
  multiline = false,
  numberOfLines = 1,
  ...props
}) => {
  const [isFocused, setIsFocused] = useState(false);
  const [isHovered, setIsHovered] = useState(false);

  return (
    <View
      style={[
        styles.container,
        isHovered && { backgroundColor: colors.glass.backgroundHover, borderColor: colors.glass.borderHover },
        isFocused && { backgroundColor: colors.glass.backgroundHover, borderColor: colors.border.strong },
        style,
      ]}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {leftIcon && <View style={styles.leftIcon}>{leftIcon}</View>}
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.text.subtle}
        secureTextEntry={secureTextEntry}
        keyboardType={keyboardType}
        autoCapitalize={autoCapitalize}
        multiline={multiline}
        numberOfLines={numberOfLines}
        onFocus={() => setIsFocused(true)}
        onBlur={() => setIsFocused(false)}
        style={[
          styles.input,
          leftIcon && styles.inputWithLeftIcon,
          rightIcon && styles.inputWithRightIcon,
          multiline && styles.multilineInput,
          inputStyle,
        ]}
        {...props}
      />
      {rightIcon && <View style={styles.rightIcon}>{rightIcon}</View>}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    flexDirection: 'row',
    alignItems: 'center',
    position: 'relative',
    transition: 'all 0.2s ease',
  },
  input: {
    flex: 1,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    color: colors.text.primary,
    fontSize: 16,
    outlineStyle: 'none',
  },
  inputWithLeftIcon: {
    paddingLeft: spacing.xxl + spacing.md,
  },
  inputWithRightIcon: {
    paddingRight: spacing.xxl + spacing.md,
  },
  multilineInput: {
    minHeight: 100,
    textAlignVertical: 'top',
    paddingTop: spacing.md,
  },
  leftIcon: {
    position: 'absolute',
    left: spacing.lg,
    zIndex: 1,
  },
  rightIcon: {
    position: 'absolute',
    right: spacing.lg,
    zIndex: 1,
  },
});

export default GlassInput;
