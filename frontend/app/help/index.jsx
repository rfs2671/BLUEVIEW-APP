/**
 * Phase B4 — /help index.
 *
 * Lands the customer on a 5-card directory of self-serve help
 * topics. Each card routes to a topic page under /help/*.
 *
 * Design system: AnimatedBackground + GlassCard + useTheme,
 * matches /onboarding's visual language. Mobile-first.
 */

import React, { useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
} from 'react-native';
import { useRouter } from 'expo-router';
import {
  Sparkles,
  HelpCircle,
  Wrench,
  Bell,
  Shield,
  ChevronRight,
} from 'lucide-react-native';
import HelpPageShell from '../../src/components/HelpPageShell';
import { GlassCard } from '../../src/components/GlassCard';
import { useTheme } from '../../src/context/ThemeContext';
import { spacing, borderRadius, typography } from '../../src/styles/theme';

const HELP_CARDS = [
  {
    path: '/help/getting-started',
    icon: Sparkles,
    title: 'Getting started',
    subtitle:
      'What LeveLog monitors, how data is refreshed, and what to expect in your first 15 minutes.',
  },
  {
    path: '/help/faq',
    icon: HelpCircle,
    title: 'FAQ',
    subtitle:
      'Severity levels, 311 vs DOB, email volume, filing reps, multi-user setup, and the most common questions.',
  },
  {
    path: '/help/troubleshooting',
    icon: Wrench,
    title: 'Troubleshooting',
    subtitle:
      "Empty feeds, missing emails, signals showing as (none), and the wrong project address.",
  },
  {
    path: '/help/notifications',
    icon: Bell,
    title: 'Notification preferences',
    subtitle:
      "Picking the right preset, per-project overrides, the preview tool, and the SMS roadmap.",
  },
  {
    path: '/help/permit-renewal',
    icon: Shield,
    title: 'Permit renewal',
    subtitle:
      "How LeveLog assists manual filing on DOB NOW, status indicators, and PW2 copy values.",
  },
];

export default function HelpIndex() {
  const router = useRouter();
  const { colors, isDark } = useTheme();
  const styles = useMemo(() => buildStyles(colors, isDark), [colors, isDark]);

  return (
    <HelpPageShell title="Help center">
      <Text style={styles.lead}>
        Self-serve answers to the most common LeveLog questions. Can't find
        what you're looking for? Reach out via the chat widget on
        levelog.com or email support.
      </Text>
      <View style={styles.grid}>
        {HELP_CARDS.map((card) => {
          const Icon = card.icon;
          return (
            <Pressable
              key={card.path}
              onPress={() => router.push(card.path)}
              style={({ pressed }) => [
                styles.cardWrap,
                pressed && { opacity: 0.85 },
              ]}
              accessibilityRole="link"
              accessibilityLabel={card.title}
            >
              <GlassCard style={styles.card} hoverEffect={false}>
                <View style={styles.cardHeader}>
                  <View style={styles.iconCircle}>
                    <Icon size={20} strokeWidth={1.5} color={colors.text.primary} />
                  </View>
                  <ChevronRight size={18} color={colors.text.muted} />
                </View>
                <Text style={styles.cardTitle}>{card.title}</Text>
                <Text style={styles.cardSubtitle}>{card.subtitle}</Text>
              </GlassCard>
            </Pressable>
          );
        })}
      </View>
    </HelpPageShell>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    lead: {
      fontSize: 15,
      lineHeight: 22,
      color: colors.text.secondary,
      marginBottom: spacing.lg,
    },
    grid: {
      gap: spacing.md,
    },
    cardWrap: {
      width: '100%',
    },
    card: {
      paddingVertical: spacing.lg,
      paddingHorizontal: spacing.lg,
    },
    cardHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: spacing.sm,
    },
    iconCircle: {
      width: 40,
      height: 40,
      borderRadius: 20,
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
      alignItems: 'center',
      justifyContent: 'center',
    },
    cardTitle: {
      fontSize: 17,
      fontWeight: '600',
      color: colors.text.primary,
      marginBottom: 4,
    },
    cardSubtitle: {
      fontSize: 13,
      lineHeight: 19,
      color: colors.text.secondary,
    },
  });
}
