/**
 * RenewalAlertCard
 * ═══════════════
 * UNMOUNTED — nothing imports this file. Do not re-mount it without
 * reading the note below.
 *
 * It was mounted twice on the project detail screen (app/project/[id].jsx)
 * and read /api/permit-renewals directly. Both mounts were removed because
 * the rows it renders are not trustworthy:
 *
 *   • `days_until_expiry` is measured against the v2 limiting-factor
 *     expiry, while `current_expiration` beside it holds the calendar
 *     expiry — two different dates by construction
 *     (backend/lib/eligibility_dispatcher.py:172,181). The card labelled
 *     the first with the second's meaning: "N days until permit expires".
 *   • `job_number` is hardcoded to None by the same adapter (:178), so the
 *     mini-bar's `a.job_number ? ... : 'Permit'` fallback always took the
 *     false branch — substituting a category noun for missing identity and
 *     continuing to render the urgency bar, the colour, and the day count.
 *     A control asserting that a specific thing expires in N days while
 *     unable to say which thing.
 *   • The rows themselves multiply: they key on a dob_logs _id, which
 *     changes on every DOB status transition and on every reset-resync.
 *
 * The fix is in the writer and the adapter, not here. This component comes
 * back when the permit-renewal module is unparked deliberately.
 *
 * See docs/audits/permit-expiry-claim-2026-08-27.md §7.
 */

import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
} from 'react-native';
import { useRouter } from 'expo-router';
import {
  ShieldCheck,
  ShieldAlert,
  ArrowRight,
  Clock,
  AlertTriangle,
  ExternalLink,
} from 'lucide-react-native';
import { GlassCard } from './GlassCard';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius, typography } from '../styles/theme';
import { semantic } from '../styles/semanticColors';
import apiClient from '../utils/api';

const RenewalAlertCard = ({ projectId }) => {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();

  const [loading, setLoading] = useState(true);
  const [alerts, setAlerts] = useState([]);

  useEffect(() => {
    if (projectId) fetchAlerts();
  }, [projectId]);

  const fetchAlerts = async () => {
    try {
      const resp = await apiClient.get(
        `/api/permit-renewals?project_id=${projectId}&limit=10`
      );
      const data = resp.data;
      const actionable = (data.renewals || []).filter((r) =>
        [
          'eligible',
          'draft_ready',
          'awaiting_gc',
        ].includes(r.status)
      );
      setAlerts(actionable);
    } catch (error) {
      // Non-critical — fail silently
      console.log(
        'Renewal alerts fetch skipped:',
        error.message
      );
    } finally {
      setLoading(false);
    }
  };

  if (loading || alerts.length === 0) return null;

  // Step 6.2.4: prefer the v2 `limiting_factor.expires_in_days` over
  // the legacy `days_until_expiry` when present. The v2 value reflects
  // the post-§1.1-ceiling effective expiry (e.g. 1-year-since-issuance
  // ceiling overriding the calendar date), which is what the user
  // actually needs to act on. Falls back to the legacy field when v2
  // enrichment is absent — that's the deploy-window state between the
  // 6.2.3 writer ship and the dispatcher flip, plus older persisted
  // records.
  const getDays = (r) => {
    const v2 = r?.limiting_factor?.expires_in_days;
    if (typeof v2 === 'number') return v2;
    return r?.days_until_expiry ?? null;
  };

  const totalAlerts = alerts.length;
  const mostUrgent = alerts.reduce((min, a) => {
    const d = getDays(a) ?? 999;
    return d < (getDays(min) ?? 999) ? a : min;
  }, alerts[0]);

  const mostUrgentDays = getDays(mostUrgent);
  const isUrgent = (mostUrgentDays ?? 999) <= 7;
  const hasAwaitingGC = alerts.some((a) =>
    ['draft_ready', 'awaiting_gc'].includes(a.status)
  );

  let accentColor = semantic.verified;
  let AlertIcon = ShieldCheck;
  let title = 'Renewal Ready';
  let subtitle = `${totalAlerts} permit${totalAlerts > 1 ? 's' : ''} eligible for renewal`;

  if (isUrgent) {
    accentColor = semantic.critical;
    AlertIcon = AlertTriangle;
    title = 'Urgent Renewal';
    // When v2 supplies the limiting_factor label, surface the "why"
    // ("…until permit expires — 1-year issuance ceiling") so the user
    // sees the real reason rather than the generic calendar phrasing.
    // Absent → legacy phrasing unchanged.
    const reason = mostUrgent?.limiting_factor?.label;
    const base = `${mostUrgentDays} day${mostUrgentDays !== 1 ? 's' : ''} until permit expires`;
    subtitle = reason ? `${base} — ${reason}` : base;
  } else if (hasAwaitingGC) {
    accentColor = '#8b5cf6';
    AlertIcon = ExternalLink;
    title = 'Sign & Pay on DOB NOW';
    subtitle = 'Renewal draft ready — complete on DOB portal';
  }

  return (
    <Pressable
      onPress={() =>
        router.push(`/project/${projectId}/dob-logs`)
      }
    >
      <GlassCard
        style={[
          s.card,
          { borderColor: accentColor + '30' },
        ]}
      >
        <View style={s.cardContent}>
          <View
            style={[
              s.iconCircle,
              {
                backgroundColor: accentColor + '15',
                borderColor: accentColor + '30',
              },
            ]}
          >
            <AlertIcon
              size={22}
              color={accentColor}
              strokeWidth={1.5}
            />
          </View>
          <View style={s.textBlock}>
            <Text style={[s.title, { color: accentColor === semantic.critical ? semantic.criticalText : accentColor }]}>
              {title}
            </Text>
            <Text style={s.subtitle}>{subtitle}</Text>
          </View>
          <ArrowRight size={18} color={colors.text.muted} />
        </View>

        {totalAlerts > 0 && (
          <View style={s.progressRow}>
            {alerts.slice(0, 3).map((a) => {
              // Same v2-prefer-then-fallback pattern as the urgency
              // calc above — keeps the mini-progress bars in sync
              // with the headline subtitle.
              const days = getDays(a) ?? 0;
              const pct = Math.max(
                0,
                Math.min(100, ((30 - days) / 30) * 100)
              );
              return (
                <View key={a.id} style={s.miniProgress}>
                  <View style={s.miniProgressBg}>
                    <View
                      style={[
                        s.miniProgressFill,
                        {
                          width: `${pct}%`,
                          backgroundColor:
                            days <= 7
                              ? '#ef4444'
                              : days <= 14
                                ? semantic.attention
                                : '#22c55e',
                        },
                      ]}
                    />
                  </View>
                  <Text style={s.miniLabel}>
                    {a.job_number
                      ? `J-${a.job_number.slice(-4)}`
                      : 'Permit'}{' '}
                    · {days}d
                  </Text>
                </View>
              );
            })}
          </View>
        )}
      </GlassCard>
    </Pressable>
  );
};

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    card: {
      marginBottom: spacing.lg,
      borderWidth: 1,
    },
    cardContent: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
    },
    iconCircle: {
      width: 44,
      height: 44,
      borderRadius: 22,
      borderWidth: 1,
      alignItems: 'center',
      justifyContent: 'center',
    },
    textBlock: { flex: 1 },
    title: {
      fontFamily: typography.semibold,
      fontSize: 15,
      marginBottom: 2,
    },
    subtitle: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.muted,
    },
    progressRow: {
      marginTop: spacing.md,
      gap: spacing.sm,
    },
    miniProgress: { gap: 3 },
    miniProgressBg: {
      height: 4,
      borderRadius: 2,
      backgroundColor: colors.glass.border,
      overflow: 'hidden',
    },
    miniProgressFill: {
      height: '100%',
      borderRadius: 2,
    },
    miniLabel: {
      fontFamily: typography.regular,
      fontSize: 10,
      color: colors.text.muted,
      letterSpacing: 0.3,
    },
  });
}

export default RenewalAlertCard;
