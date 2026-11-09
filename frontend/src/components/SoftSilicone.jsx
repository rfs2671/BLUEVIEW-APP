import React, { useState } from 'react';
import { View, Text, TextInput, Pressable, Image, StyleSheet, ActivityIndicator } from 'react-native';
import { Eye, EyeOff } from 'lucide-react-native';
import { useTheme } from '../context/ThemeContext';
import { SOFT, SOFT_DIMS } from './softAssets';

/**
 * Soft-silicone controls for the login and register screens: a field that is a
 * shallow dish pressed into the surface, and a key that rises off it. Matte,
 * with long soft shadows and a thin light edge; light comes from the top left.
 *
 * THE SURFACES ARE IMAGES. React Native cannot draw inner shadows or stacked
 * shadows, and iPhone and Android draw single shadows differently, so computing
 * this on the phone gave a flat, faint version of the design. The surfaces are
 * rendered once, in the app's own colours (paper #ECEDE9 in light, navy #1C2B38
 * in dark), by scripts/build-soft-assets.py, and drawn here as three pieces
 * (left cap, stretchy middle, right cap) so they fit any width and look the same
 * everywhere. Text, icons and the focus ring stay live.
 */
function Surface({ kind, isDark }) {
  const d = SOFT_DIMS[kind];
  const set = SOFT[isDark ? 'dark' : 'light'][kind];
  return (
    <View
      pointerEvents="none"
      style={{ position: 'absolute', left: -d.margin, right: -d.margin, top: -d.margin, height: d.imgH, flexDirection: 'row' }}
    >
      <Image source={set.L} style={{ width: d.capW, height: d.imgH }} />
      <Image source={set.M} style={{ flex: 1, height: d.imgH }} resizeMode="stretch" />
      <Image source={set.R} style={{ width: d.capW, height: d.imgH }} />
    </View>
  );
}

export const SoftField = React.forwardRef(({
  value, onChangeText, placeholder, secureTextEntry, keyboardType = 'default', autoCapitalize = 'none',
  leftIcon, rightIcon, style, ...props
}, ref) => {
  const { colors, isDark } = useTheme();
  const [focused, setFocused] = useState(false);
  const h = SOFT_DIMS.field.body;
  const focus = isDark ? 'rgba(120,172,214,0.6)' : 'rgba(69,140,181,0.55)';

  return (
    <View style={[{ height: h }, style]}>
      <Surface kind="field" isDark={isDark} />
      {focused ? <View pointerEvents="none" style={[styles.ring, { borderColor: focus, borderRadius: h / 2 + 3 }]} /> : null}
      <View style={styles.fieldRow}>
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
      </View>
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
      {({ pressed }) => (
        // No scale on press: shrinking the key would re-sample the image pieces and show a hairline at each
        // join. The pressed image (the key sinking in) carries the feel.
        <View style={{ height: SOFT_DIMS.key.body }}>
          <Surface kind={pressed ? 'keyp' : 'key'} isDark={isDark} />
          <View style={styles.keyContent}>
            {loading ? (
              <ActivityIndicator size="small" color={colors.text.primary} />
            ) : (
              <View style={styles.keyRow}>
                {icon ? <View style={styles.keyIcon}>{icon}</View> : null}
                <Text style={[styles.keyText, { color: colors.text.primary }]}>{title}</Text>
              </View>
            )}
          </View>
        </View>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  fieldRow: { ...StyleSheet.absoluteFillObject, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 28 },
  input: { flex: 1, minWidth: 0, fontSize: 16, paddingVertical: 0, backgroundColor: 'transparent', outlineStyle: 'none' },
  iconL: { marginRight: 8, flexShrink: 0 },
  iconR: { marginLeft: 4, marginRight: -10, flexShrink: 0 },
  eye: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center', flexShrink: 0 },
  ring: { position: 'absolute', left: -3, right: -3, top: -3, bottom: -3, borderWidth: 2.5 },
  keyContent: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center' },
  keyRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center' },
  keyIcon: { marginRight: 10 },
  keyText: { fontSize: 16, fontWeight: '700', letterSpacing: 0.2 },
});

export default { SoftField, SoftKey, PasswordToggle };
