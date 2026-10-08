import React from 'react';
import { View, Text, StyleSheet, Pressable, ScrollView } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { ArrowLeft } from 'lucide-react-native';
import { OWNER_NAV, ownerNavActive } from '../utils/ownerPortal';
import { spacing, borderRadius } from '../styles/theme';
import { chrome } from '../styles/semanticColors';
import { useTheme } from '../context/ThemeContext';

/**
 * THE OWNER PORTAL'S OWN NAV, in place of the app's sidebar and tab bar.
 *
 * Every /owner screen renders this at the top and no FloatingNav;
 * DesktopShell lists /owner in BARE_ROUTES so the desktop rail is gone too.
 * "Back to app" leaves the portal for the normal app's dashboard.
 */
export default function OwnerNav({ title }) {
  const { colors } = useTheme();
  const s = buildStyles(colors);
  const router = useRouter();
  const active = ownerNavActive(usePathname());

  return (
    <View style={s.wrap}>
      <View style={s.topRow}>
        <Pressable
          onPress={() => router.replace('/')}
          accessibilityRole="button"
          accessibilityLabel="Back to app"
          style={({ pressed }) => [s.back, pressed && s.pressed]}
        >
          <ArrowLeft size={18} strokeWidth={1.75} color={colors.text.primary} />
          <Text style={s.backText}>Back to app</Text>
        </Pressable>
        <Text style={s.brand}>OWNER PORTAL</Text>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}
        contentContainerStyle={s.tabs}>
        {OWNER_NAV.map((item) => {
          const on = item.key === active;
          return (
            <Pressable
              key={item.key}
              onPress={() => { if (!on) router.replace(item.path); }}
              accessibilityRole="tab"
              accessibilityState={{ selected: on }}
              style={({ pressed }) => [s.tab, on && s.tabOn, pressed && s.pressed]}
            >
              <Text style={[s.tabText, on && s.tabTextOn]}>{item.label}</Text>
            </Pressable>
          );
        })}
      </ScrollView>
      {title ? <Text style={s.title}>{title}</Text> : null}
    </View>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    wrap: {
      paddingHorizontal: spacing.lg,
      paddingTop: spacing.sm,
      paddingBottom: spacing.xs,
      gap: spacing.sm,
    },
    topRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: spacing.sm,
    },
    back: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      minHeight: 44,
      paddingHorizontal: spacing.sm,
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    backText: { fontSize: 14, fontWeight: '500', color: colors.text.primary },
    brand: {
      fontSize: 13, fontWeight: '700', letterSpacing: 1.5,
      color: colors.text.muted,
    },
    tabs: { gap: spacing.sm },
    tab: {
      minHeight: 40,
      justifyContent: 'center',
      paddingHorizontal: spacing.md,
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    tabOn: { borderColor: chrome.brand, backgroundColor: colors.glass.background },
    tabText: { fontSize: 14, fontWeight: '500', color: colors.text.secondary },
    tabTextOn: { color: chrome.brand, fontWeight: '600' },
    title: { fontSize: 20, fontWeight: '600', color: colors.text.primary },
    pressed: { opacity: 0.8 },
  });
}
