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
 *   exposureSummary — OPTIONAL. When set, the card LEADS with this open-exposure
 *                     line instead of the tier label + primary_reason, and the
 *                     backend NORMAL prose is withheld. Set by CompliancePanel
 *                     only when tier===NORMAL AND the project has open
 *                     violations/complaints, so a reassuring verdict can never
 *                     sit above contradicting exposure.
 *   exposureTone    — OPTIONAL. 'critical' | 'attention' — tone for the lede.
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
import { semantic } from '../styles/semanticColors';
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
  exposureSummary,
  exposureTone,
}) {
  const { colors } = useTheme();
  const safeTier = tier || 'NORMAL';
  // Exposure lede — set by CompliancePanel when a reassuring NORMAL verdict
  // would otherwise sit above standing open exposure. The tier itself is
  // unchanged; only what this card LEADS with changes.
  const leading = !!exposureSummary;
  const tierTheme = tierToTheme(safeTier);
  const fg = leading
    ? (exposureTone === 'critical' ? semantic.criticalText : semantic.attention)
    : tierTheme.fg;
  const bg = leading
    ? (exposureTone === 'critical' ? semantic.criticalBg : semantic.attentionBg)
    : tierTheme.bg;
  const Icon = leading
    ? (exposureTone === 'critical' ? AlertTriangle : ShieldAlert)
    : _tierIcon(safeTier);
  const timeAgo = formatTimeAgo(lastEvaluatedAt);

  return (
    <View
      style={[styles.card, { backgroundColor: bg, borderColor: fg }]}
      accessibilityRole="summary"
      accessibilityLabel={
        leading
          ? `Open exposure: ${exposureSummary}`
          : `Defcon tier: ${tierToLabel(safeTier)}`
      }
    >
      <View style={styles.row}>
        <Icon size={18} strokeWidth={1.5} color={fg} />
        {/* PR #52 — single-line tier label + timestamp; tier label
            shrinks before the timestamp so neither overflows the row. */}
        <Text
          style={[styles.tierLabel, { color: fg }]}
          numberOfLines={1}
          ellipsizeMode="tail"
        >
          {leading ? 'OPEN EXPOSURE' : tierToLabel(safeTier).toUpperCase()}
        </Text>
        {timeAgo && (
          <Text
            style={[styles.timeAgo, { color: colors.text.muted }]}
            numberOfLines={1}
          >
            {timeAgo}
          </Text>
        )}
      </View>
      {leading ? (
        <>
          <Text
            style={[styles.reason, { color: colors.text.primary }]}
            numberOfLines={2}
            ellipsizeMode="tail"
          >
            {exposureSummary}
          </Text>
          {/* The backend's NORMAL prose ("All indicators within typical range")
              is NOT rendered here — it overstates what the model examined and
              would contradict the line above. This states the model's actual
              scope instead. */}
          <Text
            style={[styles.scopeNote, { color: colors.text.secondary }]}
            numberOfLines={3}
          >
            Forecast reads acute signals only — stop-work orders, recent
            CLASS-1/2 violations, complaint clustering. It does not count
            standing open items.
          </Text>
        </>
      ) : primaryReason ? (
        // PR #52 — reason is prose; allow up to 3 lines then ellipsize
        // rather than letting it run unbounded on small screens.
        <Text
          style={[styles.reason, { color: colors.text.primary }]}
          numberOfLines={3}
          ellipsizeMode="tail"
        >
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
  scopeNote: {
    fontSize: 11,
    lineHeight: 15,
  },
  whyLink: {
    ...typography.label,
    fontSize: 11,
    letterSpacing: 1,
    paddingTop: 2,
  },
});
