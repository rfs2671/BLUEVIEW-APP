import React, { useState, useEffect } from 'react';
import { TextInput, View, StyleSheet, Platform } from 'react-native';
import { borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';
import { Surface } from './SoftSilicone';
import { PanelSurface } from './SoftPanel';
import { SOFT_DIMS } from './softAssets';

/* Inject a global CSS rule once to kill Chrome's autofill background.
 *
 * -webkit-text-fill-color must be `currentColor`, never a literal. Chrome
 * overrides an autofilled input's `color`, so the declaration has to exist —
 * but it used to hardcode rgba(255,255,255,0.9), the DARK theme's text colour.
 * On the light theme that painted white text on a near-white input: invisible
 * while typing, i.e. a broken sign-in. It only manifested on AUTOFILL, which is
 * why every visual audit missed it. `currentColor` resolves to the element's
 * own computed colour, which RN-Web sets per theme, so the rule now follows the
 * theme even though it is injected once (guarded by autofillCSSInjected) and
 * never re-injected on theme switch.
 */
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
      -webkit-text-fill-color: currentColor !important;
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

  // The field is a soft dish pressed into the surface (the same one as the login): a pill for one line, a rounded
  // well for a multi-line box. Its fill and hairline border from the old glass look are gone; a caller's own
  // background, border and radius are dropped so they cannot draw a frame around the dish.
  const flat = StyleSheet.flatten(style) || {};
  const callerStyle = {};
  Object.keys(flat).forEach((k) => {
    if (['backgroundColor', 'borderColor', 'borderWidth', 'borderRadius', 'overflow'].includes(k)) return;
    callerStyle[k] = flat[k];
  });
  const fieldH = SOFT_DIMS.field.body;

  return (
    <View
      style={[multiline ? s.containerMulti : [s.container, { height: fieldH }], callerStyle]}
    >
      {multiline ? <PanelSurface kind="well" /> : <Surface kind="field" isDark={isDark} />}
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
    flexDirection: 'row',
    alignItems: 'center',
    position: 'relative',
  },
  containerMulti: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    position: 'relative',
    minHeight: 96,
    paddingVertical: spacing.xs,
  },
  input: {
    flex: 1,
    position: 'relative', // above the soft dish: an absolutely placed surface would paint over it on the web
    paddingHorizontal: spacing.xl,
    paddingVertical: 0,
    color: colors.text.primary,
    fontSize: 16,
    backgroundColor: 'transparent',
    outlineStyle: 'none',
  },
  inputWithLeftIcon: {
    paddingLeft: spacing.xxl + spacing.lg,
  },
  inputWithRightIcon: {
    paddingRight: spacing.xxl + spacing.lg,
  },
  multilineInput: {
    minHeight: 96,
    textAlignVertical: 'top',
    paddingTop: spacing.md,
    paddingVertical: spacing.md,
  },
  leftIcon: {
    position: 'absolute',
    left: spacing.xl,
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
    right: spacing.xl,
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
