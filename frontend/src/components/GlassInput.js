import React, { useState } from 'react';
import { TextInput, View, StyleSheet } from 'react-native';
import { colors, borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';

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
        s.container,
        isHovered && { backgroundColor: colors.glass.backgroundHover, borderColor: colors.glass.borderHover },
        isFocused && { backgroundColor: colors.glass.backgroundHover, borderColor: colors.border.strong },
        style,
      ]}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {leftIcon && <View style={s.leftIcon}>{leftIcon}</View>}
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
          s.input,
          leftIcon && s.inputWithLeftIcon,
          rightIcon && s.inputWithRightIcon,
          multiline && s.multilineInput,
          inputStyle,
        ]}
        {...props}
      />
      {rightIcon && <View style={s.rightIcon}>{rightIcon}</View>}
    </View>
  );
};

function buildStyles(colors, isDark) {
  return StyleSheet.create({
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
}
export default GlassInput;
