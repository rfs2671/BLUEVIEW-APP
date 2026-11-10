import React from 'react';
import { useRouter, usePathname } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Settings } from 'lucide-react-native';
import { useTheme } from '../context/ThemeContext';
import { useIsDesktop } from '../hooks/useIsDesktop';
import { useNavChromeVisible } from '../utils/navChromeStore';
import { SoftPebble } from './SoftPanel';

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

  // The same soft round button as the back button on the left, so the two header corners match.
  return (
    <SoftPebble
      onPress={() => router.push('/settings')}
      accessibilityRole="button"
      accessibilityLabel="Settings"
      hitSlop={8}
      style={{ position: 'absolute', right: 24, top: insets.top + 16, zIndex: 50 }}
    >
      <Settings size={19} strokeWidth={1.6} color={colors.text.secondary} />
    </SoftPebble>
  );
}
