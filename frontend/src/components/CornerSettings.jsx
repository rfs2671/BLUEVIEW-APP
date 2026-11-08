import React from 'react';
import { Pressable, StyleSheet } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Settings } from 'lucide-react-native';
import { useTheme } from '../context/ThemeContext';
import { useIsDesktop } from '../hooks/useIsDesktop';
import { useNavChromeVisible } from '../utils/navChromeStore';
import { withAlpha } from '../styles/semanticColors';

// Small, always-there settings button in the top-right corner. It replaces the
// Settings tab in the bottom bar. Shown wherever the bottom nav is (the nav
// registers itself in navChromeStore), and hidden on the settings page itself.
export default function CornerSettings() {
  const router = useRouter();
  const pathname = usePathname();
  const insets = useSafeAreaInsets();
  const { colors } = useTheme();
  const isDesktop = useIsDesktop();
  const navVisible = useNavChromeVisible();

  if (isDesktop || !navVisible || pathname === '/settings') return null;

  return (
    <Pressable
      onPress={() => router.push('/settings')}
      accessibilityRole="button"
      accessibilityLabel="Settings"
      hitSlop={8}
      style={({ pressed }) => [
        styles.btn,
        {
          top: insets.top + 19,
          backgroundColor: withAlpha(colors.text.primary, 0.06),
          borderColor: colors.glass.border,
        },
        pressed && { opacity: 0.6 },
      ]}
    >
      <Settings size={17} strokeWidth={1.7} color={colors.text.secondary} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btn: {
    position: 'absolute',
    right: 16,
    width: 34,
    height: 34,
    borderRadius: 17,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 50,
  },
});
