import React, { useState, useEffect } from 'react';
import { View, Text, TextInput, Pressable, StyleSheet, Platform, ActivityIndicator } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Eye, EyeOff } from 'lucide-react-native';
import { useTheme } from '../context/ThemeContext';
import { withAlpha } from '../styles/semanticColors';

/**
 * Soft-silicone controls for the login screen: a field that reads as a shallow
 * dish pressed into the surface, and a key that rises off it. Matte, with long
 * soft shadows and a thin light edge; light comes from the top left.
 *
 * Built only from the app's own theme colours: the surface IS the screen
 * background (paper #ECEDE9 in light, navy #1C2B38 in dark) and the shadows are
 * darker and lighter versions of it, so nothing here introduces a new hue.
 *
 * React Native has one shadow per view and no inner shadow, so on a phone:
 *   - the key stacks two shadow layers (a light one up-left, a dark one down-right)
 *   - the field fakes its inner shadow with edge gradients
 * On the web the same look is drawn with real CSS shadows (inset included).
 */
const CSS_SHADOWS = Platform.OS === 'web' && !(typeof globalThis !== 'undefined' && globalThis.__SOFT_NATIVE_PATH__);

function palette(isDark, colors) {
  const surface = (colors.background && colors.background.start) || (isDark ? '#1C2B38' : '#ECEDE9');
  return isDark
    ? {
        surface,
        keyTop: '#2C4050', keyBottom: '#1F2F3C',
        hi: '#FFFFFF', hiA: 0.06, lo: '#03090E', loA: 0.72,
        wellA: 'rgba(0,0,0,0.32)', wellB: 'rgba(255,255,255,0.02)',
        edge: 'rgba(255,255,255,0.14)',
        focus: 'rgba(120,172,214,0.55)',
      }
    : {
        surface,
        keyTop: '#F8F9F6', keyBottom: '#DCDED8',
        hi: '#FFFFFF', hiA: 0.95, lo: '#7C8072', loA: 0.46,
        wellA: 'rgba(124,128,114,0.18)', wellB: 'rgba(255,255,255,0.34)',
        edge: 'rgba(255,255,255,0.95)',
        focus: 'rgba(69,140,181,0.5)',
      };
}

// Chrome paints autofilled inputs with its own pale-blue background, which shows
// as a blue bar across the soft dish. Make it transparent; currentColor keeps the
// text colour following the theme (see GlassInput for the history).
let autofillCSSInjected = false;
function injectAutofillCSS() {
  if (autofillCSSInjected || Platform.OS !== 'web' || typeof document === 'undefined') return;
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

export const SoftField = React.forwardRef(({
  value, onChangeText, placeholder, secureTextEntry, keyboardType = 'default', autoCapitalize = 'none',
  leftIcon, rightIcon, style, ...props
}, ref) => {
  const { colors, isDark } = useTheme();
  const p = palette(isDark, colors);
  const [focused, setFocused] = useState(false);
  useEffect(() => { injectAutofillCSS(); }, []);
  const R = 28; // half the 56 field height: a true pill, so rings and edges follow it

  const webShadow = CSS_SHADOWS
    ? {
        boxShadow: isDark
          ? `inset 7px 8px 14px rgba(2,8,12,0.72), inset -6px -7px 13px rgba(255,255,255,0.05), 0 1px 0 rgba(255,255,255,0.04)`
          : `inset 7px 8px 14px rgba(124,128,114,0.40), inset -7px -8px 14px rgba(255,255,255,0.95), 0 1px 0 rgba(255,255,255,0.7)`,
      }
    : null;

  return (
    <View
      style={[
        styles.fieldWrap,
        { borderRadius: R },
        style,
      ]}
    >
      <LinearGradient
        colors={[p.wellA, p.wellB]}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={[styles.fieldBody, { borderRadius: R }, webShadow]}
      >
        {!CSS_SHADOWS && (
          <>
            {/* inner shadow, dark on the top and left edges... */}
            <LinearGradient pointerEvents="none" colors={[withAlpha(p.lo, isDark ? 0.55 : 0.30), withAlpha(p.lo, 0)]} style={styles.edgeTop} />
            <LinearGradient pointerEvents="none" colors={[withAlpha(p.lo, isDark ? 0.45 : 0.24), withAlpha(p.lo, 0)]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={styles.edgeLeft} />
            {/* ...light on the bottom and right edges */}
            <LinearGradient pointerEvents="none" colors={[withAlpha(p.hi, 0), withAlpha(p.hi, isDark ? 0.07 : 0.9)]} style={styles.edgeBottom} />
            <LinearGradient pointerEvents="none" colors={[withAlpha(p.hi, 0), withAlpha(p.hi, isDark ? 0.05 : 0.7)]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={styles.edgeRight} />
          </>
        )}
        {leftIcon ? <View style={styles.iconL}>{leftIcon}</View> : null}
        <TextInput
          ref={ref}
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder}
          placeholderTextColor={colors.text.subtle}
          secureTextEntry={secureTextEntry}
          keyboardType={keyboardType}
          autoCapitalize={autoCapitalize}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          style={[styles.input, { color: colors.text.primary }, leftIcon ? { paddingLeft: 6 } : null, rightIcon ? { paddingRight: 6 } : null]}
          {...props}
        />
        {rightIcon ? <View style={styles.iconR}>{rightIcon}</View> : null}
      </LinearGradient>
    </View>
  );
});

/**
 * The show/hide control for a password field. Its own fixed-size touch target
 * with a stronger icon colour than the field's other icons: the dimmest text
 * colour disappears into the dish, and a flexible icon can be squeezed out of
 * the field entirely on some devices.
 */
export function PasswordToggle({ shown, onToggle }) {
  const { colors } = useTheme();
  const Icon = shown ? EyeOff : Eye;
  return (
    <Pressable
      onPress={onToggle}
      hitSlop={8}
      accessibilityRole="button"
      accessibilityLabel={shown ? 'Hide password' : 'Show password'}
      style={styles.eye}
    >
      <Icon size={22} strokeWidth={1.7} color={colors.text.secondary} />
    </Pressable>
  );
}

export function SoftKey({ title, icon, onPress, loading = false, disabled = false, style }) {
  const { colors, isDark } = useTheme();
  const p = palette(isDark, colors);
  const R = 30;
  const off = disabled || loading;

  return (
    <Pressable
      onPress={onPress}
      disabled={off}
      accessibilityRole="button"
      accessibilityLabel={title}
      accessibilityState={{ disabled: off, busy: loading }}
      style={[{ opacity: disabled && !loading ? 0.55 : 1 }, style]}
    >
      {({ pressed }) => {
        const body = (
          <LinearGradient
            colors={pressed ? [p.keyBottom, p.keyTop] : [p.keyTop, p.keyBottom]}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
            style={[
              styles.keyBody,
              { borderRadius: R, borderColor: p.edge },
              CSS_SHADOWS && {
                boxShadow: pressed
                  ? (isDark
                      ? 'inset 6px 7px 13px rgba(2,8,12,0.72), inset -5px -6px 11px rgba(255,255,255,0.05)'
                      : 'inset 6px 7px 13px rgba(124,128,114,0.40), inset -5px -6px 11px rgba(255,255,255,0.9)')
                  : (isDark
                      ? '-9px -9px 20px rgba(255,255,255,0.05), 14px 18px 30px rgba(2,8,12,0.8), inset 1px 1px 1px rgba(255,255,255,0.13), inset -3px -4px 7px rgba(0,0,0,0.34)'
                      : '-12px -12px 26px rgba(255,255,255,0.95), 14px 18px 32px rgba(124,128,114,0.46), inset 1px 1px 2px rgba(255,255,255,0.95), inset -3px -4px 7px rgba(124,128,114,0.22)'),
              },
            ]}
          >
            {loading ? (
              <ActivityIndicator size="small" color={colors.text.primary} />
            ) : (
              <View style={styles.keyRow}>
                {icon ? <View style={styles.keyIcon}>{icon}</View> : null}
                <Text style={[styles.keyText, { color: colors.text.primary }]}>{title}</Text>
              </View>
            )}
          </LinearGradient>
        );
        if (CSS_SHADOWS) return <View style={{ transform: [{ scale: pressed ? 0.985 : 1 }] }}>{body}</View>;
        // phone: two stacked shadow layers; pressing pulls both in close
        return (
          <View
            style={{
              borderRadius: R,
              shadowColor: p.hi, shadowOpacity: pressed ? 0.3 * p.hiA : p.hiA, shadowRadius: pressed ? 6 : 18,
              shadowOffset: { width: pressed ? -2 : -9, height: pressed ? -2 : -9 },
              transform: [{ scale: pressed ? 0.985 : 1 }],
            }}
          >
            <View
              style={{
                borderRadius: R,
                shadowColor: p.lo, shadowOpacity: pressed ? 0.5 * p.loA : p.loA, shadowRadius: pressed ? 8 : 26,
                shadowOffset: { width: pressed ? 3 : 11, height: pressed ? 4 : 15 },
                elevation: pressed ? 2 : 8,
                backgroundColor: p.surface,
              }}
            >
              {body}
            </View>
          </View>
        );
      }}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  fieldWrap: { height: 56 },
  fieldBody: { flex: 1, flexDirection: 'row', alignItems: 'center', overflow: 'hidden', paddingHorizontal: 18 },
  input: { flex: 1, minWidth: 0, fontSize: 16, paddingVertical: 0, backgroundColor: 'transparent', outlineStyle: 'none' },
  iconL: { marginRight: 8, flexShrink: 0 },
  iconR: { marginLeft: 4, marginRight: -8, flexShrink: 0 },
  eye: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center', flexShrink: 0 },
  edgeTop: { position: 'absolute', top: 0, left: 0, right: 0, height: 16 },
  edgeLeft: { position: 'absolute', top: 0, bottom: 0, left: 0, width: 16 },
  edgeBottom: { position: 'absolute', bottom: 0, left: 0, right: 0, height: 12 },
  edgeRight: { position: 'absolute', top: 0, bottom: 0, right: 0, width: 12 },
  keyBody: { height: 60, alignItems: 'center', justifyContent: 'center', overflow: 'hidden', borderWidth: StyleSheet.hairlineWidth },
  keyRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center' },
  keyIcon: { marginRight: 10 },
  keyText: { fontSize: 16, fontWeight: '700', letterSpacing: 0.2 },
});

export default { SoftField, SoftKey, PasswordToggle };
