/**
 * RenewalAlertCard
 * ═══════════════
 * Drop-in component for the project detail screen ([id].jsx).
 * Shows a prominent card when permits are expiring.
 *
 * Usage in frontend/app/project/[id].jsx:
 *   import RenewalAlertCard from '../../../src/components/RenewalAlertCard';
 *   <RenewalAlertCard projectId={projectId} />
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

  const totalAlerts = alerts.length;
  const mostUrgent = alerts.reduce((min, a) => {
    const d = a.days_until_expiry ?? 999;
    return d < (min?.days_until_expiry ?? 999) ? a : min;
  }, alerts[0]);

  const isUrgent = (mostUrgent.days_until_expiry ?? 999) <= 7;
  const hasAwaitingGC = alerts.some((a) =>
    ['draft_ready', 'awaiting_gc'].includes(a.status)
  );

  let accentColor = '#22c55e';
  let AlertIcon = ShieldCheck;
  let title = 'Renewal Ready';
  let subtitle = `${totalAlerts} permit${totalAlerts > 1 ? 's' : ''} eligible for renewal`;

  if (isUrgent) {
    accentColor = '#ef4444';
    AlertIcon = AlertTriangle;
    title = 'Urgent Renewal';
    subtitle = `${mostUrgent.days_until_expiry} day${mostUrgent.days_until_expiry !== 1 ? 's' : ''} until permit expires`;
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
            <Text style={[s.title, { color: accentColor }]}>
              {title}
            </Text>
            <Text style={s.subtitle}>{subtitle}</Text>
          </View>
          <ArrowRight size={18} color={colors.text.muted} />
        </View>

        {totalAlerts > 0 && (
          <View style={s.progressRow}>
            {alerts.slice(0, 3).map((a) => {
              const days = a.days_until_expiry ?? 0;
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
                                ? '#f59e0b'
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
