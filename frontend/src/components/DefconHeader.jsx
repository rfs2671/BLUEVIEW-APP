/**
 * Phase 1 Week 11-12 PR-B — Defcon tier header card.
 *
 * Compact tier badge + GC-voice primary_reason + "Why?" link. Rendered
 * at the top of CompliancePanel when the backend's defcon-status
 * endpoint returns a tier. The "Why?" link navigates to the full
 * Defcon detail screen at /project/{id}/defcon.
 *
 * Props:
 *   tier            — 'NORMAL' | 'ELEVATED' | 'IMMEDIATE' (defaults to NORMAL)
 *   primaryReason   — pre-rendered GC-voice reason string from backend
 *   lastEvaluatedAt — ISO UTC string; rendered as "X minutes ago"
 *   onPressWhy      — handler for the Why? link (parent passes navigation)
 *
 * Icon mapping (3-bucket Lucide):
 *   NORMAL    → ShieldCheck    (green)
 *   ELEVATED  → ShieldAlert    (amber)
 *   IMMEDIATE → AlertTriangle  (red)
 */

import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
} from 'lucide-react-native';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius, typography } from '../styles/theme';
import {
  tierToTheme,
  tierToLabel,
  formatTimeAgo,
} from '../utils/defconHelpers';

function _tierIcon(tier) {
  if (tier === 'IMMEDIATE') return AlertTriangle;
  if (tier === 'ELEVATED')  return ShieldAlert;
  return ShieldCheck;
}

export default function DefconHeader({
  tier,
  primaryReason,
  lastEvaluatedAt,
  onPressWhy,
}) {
  const { colors } = useTheme();
  const safeTier = tier || 'NORMAL';
  const { fg, bg } = tierToTheme(safeTier);
  const Icon = _tierIcon(safeTier);
  const timeAgo = formatTimeAgo(lastEvaluatedAt);

  return (
    <View
      style={[styles.card, { backgroundColor: bg, borderColor: fg }]}
      accessibilityRole="summary"
      accessibilityLabel={`Defcon tier: ${tierToLabel(safeTier)}`}
    >
      <View style={styles.row}>
        <Icon size={18} strokeWidth={1.5} color={fg} />
        <Text style={[styles.tierLabel, { color: fg }]}>
          {tierToLabel(safeTier).toUpperCase()}
        </Text>
        {timeAgo && (
          <Text style={[styles.timeAgo, { color: colors.text.muted }]}>
            {timeAgo}
          </Text>
        )}
      </View>
      {primaryReason ? (
        <Text style={[styles.reason, { color: colors.text.primary }]}>
          {primaryReason}
        </Text>
      ) : null}
      {onPressWhy && (
        <Pressable
          onPress={onPressWhy}
          accessibilityRole="link"
          accessibilityLabel="Open Defcon detail screen"
          hitSlop={8}
        >
          <Text style={[styles.whyLink, { color: fg }]}>Why? →</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: borderRadius.md,
    borderWidth: 1,
    padding: spacing.sm,
    marginBottom: spacing.sm,
    gap: spacing.xs,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  tierLabel: {
    ...typography.label,
    fontSize: 11,
    letterSpacing: 1.5,
    flex: 1,
  },
  timeAgo: {
    ...typography.small,
    fontSize: 11,
  },
  reason: {
    ...typography.body,
    fontSize: 14,
    lineHeight: 18,
  },
  whyLink: {
    ...typography.label,
    fontSize: 11,
    letterSpacing: 1,
    paddingTop: 2,
  },
});
