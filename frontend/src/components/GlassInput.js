import React, { useState, useEffect } from 'react';
import { TextInput, View, StyleSheet, Platform } from 'react-native';
import { borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';

/* Inject a global CSS rule once to kill Chrome's autofill background */
let autofillCSSInjected = false;
function injectAutofillCSS() {
  if (autofillCSSInjected || Platform.OS !== 'web') return;
  autofillCSSInjected = true;
  const style = document.createElement('style');
  style.textContent = `
    input:-webkit-autofill,
    input:-webkit-autofill:hover,
    input:-webkit-autofill:focus,
    input:-webkit-autofill:active {
      -webkit-box-shadow: 0 0 0 1000px transparent inset !important;
      -webkit-text-fill-color: rgba(255,255,255,0.9) !important;
      background-color: transparent !important;
      transition: background-color 5000s ease-in-out 0s !important;
    }
  `;
  document.head.appendChild(style);
}

const IconWrap = ({ children, style }) => (
  <View style={style}>
    <View style={{ backgroundColor: 'transparent' }}>
      {children}
    </View>
  </View>
);

const GlassInput = React.forwardRef(({
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
}, ref) => {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const [isFocused, setIsFocused] = useState(false);
  const [isHovered, setIsHovered] = useState(false);

  useEffect(() => { injectAutofillCSS(); }, []);

  return (
    <View
      style={[
        s.container,
        isHovered && { backgroundColor: colors.glass.backgroundHover, borderColor: colors.glass.borderHover },
        isFocused && { backgroundColor: colors.glass.backgroundHover, borderColor: colors.border.strong },
        style,
      ]}
      {...(Platform.OS === 'web' ? {
        onMouseEnter: () => setIsHovered(true),
        onMouseLeave: () => setIsHovered(false),
      } : {})}
    >
      {leftIcon && <IconWrap style={s.leftIcon}>{leftIcon}</IconWrap>}
      <TextInput
        ref={ref}
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
      {rightIcon && <IconWrap style={s.rightIcon}>{rightIcon}</IconWrap>}
    </View>
  );
});

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
    backgroundColor: 'transparent',
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
    top: 0,
    bottom: 0,
    justifyContent: 'center',
    alignItems: 'center',
    width: 20,
    zIndex: 1,
    backgroundColor: 'transparent',
  },
  rightIcon: {
    position: 'absolute',
    right: spacing.lg,
    top: 0,
    bottom: 0,
    justifyContent: 'center',
    alignItems: 'center',
    width: 20,
    zIndex: 1,
    backgroundColor: 'transparent',
  },
});
}
export default GlassInput;
