/**
 * Phase B4 — shared chrome for /help/* customer documentation pages.
 *
 * Wraps content in AnimatedBackground + SafeAreaView + glass header
 * bar (back button + title) + ScrollView. Re-uses the LeveLog
 * design system identically to the Activity feed shell from B0.1
 * — same header pattern, same theme-aware colors, same spacing.
 *
 * Usage:
 *
 *   <HelpPageShell title="FAQ">
 *     <HelpSection title="What's the difference between …">
 *       <HelpParagraph>...</HelpParagraph>
 *     </HelpSection>
 *   </HelpPageShell>
 *
 * Mobile-first: max content width 720, glass header bar with a
 * round back button. Theme-aware via useTheme.
 */

import React, { useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft } from 'lucide-react-native';
import AnimatedBackground from './AnimatedBackground';
import { GlassCard } from './GlassCard';
import HeaderBrand from './HeaderBrand';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius, typography } from '../styles/theme';

export default function HelpPageShell({ title, children }) {
  const router = useRouter();
  const { colors, isDark } = useTheme();
  const styles = useMemo(() => buildStyles(colors, isDark), [colors, isDark]);

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
        <View style={styles.headerBar}>
          <Pressable
            onPress={() => {
              // back() is no-op when there's no history (deep-linked
              // to /help/foo). Fall through to /help in that case so
              // the user always lands somewhere sane.
              if (router.canGoBack && router.canGoBack()) {
                router.back();
              } else {
                router.replace('/help');
              }
            }}
            style={({ pressed }) => [
              styles.backBtn,
              pressed && { opacity: 0.65 },
            ]}
            accessibilityLabel="Go back"
            accessibilityRole="button"
          >
            <ArrowLeft size={20} color={colors.text.primary} />
          </Pressable>
          <HeaderBrand />
        </View>

        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {title ? (
            <View style={styles.titleBlock}>
              <Text style={styles.eyebrow}>HELP CENTER</Text>
              <Text style={styles.title}>{title}</Text>
            </View>
          ) : null}
          {children}
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

/** A standalone help section card. Stacks below other sections with
 *  consistent vertical rhythm. */
export function HelpSection({ title, children, style }) {
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
  return (
    <GlassCard style={[styles.section, style]} hoverEffect={false}>
      {title ? <Text style={styles.sectionTitle}>{title}</Text> : null}
      {children}
    </GlassCard>
  );
}

/** Body paragraph with theme-aware color and comfortable line height. */
export function HelpParagraph({ children, style }) {
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
  return <Text style={[styles.paragraph, style]}>{children}</Text>;
}

/** Bullet list — array of strings or arbitrary nodes. */
export function HelpBullets({ items }) {
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
  return (
    <View style={styles.bullets}>
      {(items || []).map((item, idx) => (
        <View key={idx} style={styles.bulletRow}>
          <Text style={styles.bulletDot}>•</Text>
          <Text style={styles.bulletText}>{item}</Text>
        </View>
      ))}
    </View>
  );
}

/** Inline keyword / code-style emphasis for surface-level terms
 *  (e.g. "Critical only", "track_dob_status"). */
export function HelpKbd({ children }) {
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
  return <Text style={styles.kbd}>{children}</Text>;
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    safe: {
      flex: 1,
      backgroundColor: 'transparent',
    },
    headerBar: {
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.sm,
      backgroundColor: colors.glass.background,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
    },
    backBtn: {
      width: 36,
      height: 36,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 18,
      marginRight: spacing.sm,
    },
    scroll: {
      flex: 1,
    },
    scrollContent: {
      paddingHorizontal: spacing.lg,
      paddingTop: spacing.lg,
      paddingBottom: 80,
      maxWidth: 720,
      width: '100%',
      alignSelf: 'center',
    },
    titleBlock: {
      marginBottom: spacing.lg,
    },
    eyebrow: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.xs,
    },
    title: {
      fontSize: 28,
      fontWeight: '600',
      color: colors.text.primary,
      letterSpacing: -0.5,
    },
    section: {
      marginBottom: spacing.md,
    },
    sectionTitle: {
      fontSize: 18,
      fontWeight: '600',
      color: colors.text.primary,
      marginBottom: spacing.sm,
    },
    paragraph: {
      fontSize: 14,
      lineHeight: 22,
      color: colors.text.secondary,
      marginBottom: spacing.sm,
    },
    bullets: {
      gap: spacing.xs,
      marginBottom: spacing.sm,
    },
    bulletRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: spacing.sm,
    },
    bulletDot: {
      fontSize: 14,
      color: colors.text.muted,
      lineHeight: 22,
      width: 12,
      textAlign: 'center',
    },
    bulletText: {
      flex: 1,
      fontSize: 14,
      lineHeight: 22,
      color: colors.text.secondary,
    },
    kbd: {
      fontFamily: 'monospace',
      fontSize: 13,
      color: colors.text.primary,
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.sm,
      paddingHorizontal: 4,
    },
  });
}
