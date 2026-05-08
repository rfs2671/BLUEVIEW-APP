// DEPRECATED: replaced by RiskScoreCircle + RiskScoreDrawer in V2.1.2.
// Will be deleted after the redesign is verified in production.
// No longer mounted anywhere as of V2.1.2 — kept here as a
// reference for the V2.1 → V2.1.2 migration window only.
//
/**
 * Phase V2.1 — Risk Score Card.
 *
 * Drop-in component for the project detail screen
 * (frontend/app/project/[id].jsx). Renders the latest
 * `risk_scores` doc as a colored band with the score, the 95%
 * confidence interval, the top contributing factors, and an
 * admin-only "Was this score correct?" review button that opens
 * a modal posting to /risk-score/calibration.
 *
 * Hard rules pinned by tests:
 *   • useFeatureFlag('v2_risk_score') is the FIRST hook in the
 *     component (rules-of-hooks; same C1.3 / V2.0 pattern).
 *   • If the flag returns false the component returns null
 *     BEFORE fetching anything.
 *   • All inspector-review writes go to
 *     /api/projects/{id}/risk-score/calibration.
 *
 * Usage in [id].jsx:
 *   import RiskScoreCard from '../../src/components/RiskScoreCard';
 *   <RiskScoreCard projectId={projectId} isAdmin={isAdmin} />
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  Modal,
  TextInput,
} from 'react-native';
import {
  ShieldCheck,
  ShieldAlert,
  TrendingUp,
  ChevronDown,
  ChevronUp,
  X,
} from 'lucide-react-native';
import { GlassCard } from './GlassCard';
import GlassButton from './GlassButton';
import { useTheme } from '../context/ThemeContext';
import { useFeatureFlag } from '../hooks/useFeatureFlag';
import { spacing, borderRadius, typography } from '../styles/theme';
import apiClient from '../utils/api';

// Color band thresholds — kept in sync with
// backend/lib/risk_score/schema.py::score_band. Tests pin both.
const BAND_GREEN  = { bg: 'rgba(34, 197, 94, 0.15)',  border: 'rgba(34, 197, 94, 0.7)',  fg: '#22c55e', label: 'LOW' };
const BAND_YELLOW = { bg: 'rgba(234, 179, 8, 0.15)',  border: 'rgba(234, 179, 8, 0.7)',  fg: '#eab308', label: 'MODERATE' };
const BAND_ORANGE = { bg: 'rgba(249, 115, 22, 0.15)', border: 'rgba(249, 115, 22, 0.7)', fg: '#f97316', label: 'ELEVATED' };
const BAND_RED    = { bg: 'rgba(239, 68, 68, 0.18)',  border: 'rgba(239, 68, 68, 0.8)',  fg: '#ef4444', label: 'HIGH' };

function bandFor(score) {
  if (score == null) return BAND_GREEN;
  if (score <= 30) return BAND_GREEN;
  if (score <= 60) return BAND_YELLOW;
  if (score <= 80) return BAND_ORANGE;
  return BAND_RED;
}

// Human-readable factor labels. Backend returns canonical
// snake_case keys; the FE renders these.
const FACTOR_LABELS = {
  active_dob_violations:               'Active DOB violations',
  permit_days_to_expiration:           'Permit expiration',
  inspection_compliance_missed:        'Missed inspections',
  deficiency_count_30d:                'Logbook deficiencies (30d)',
  subcontractor_insurance_expirations: 'Sub COI expirations',
  missing_logs_30d:                    'Missing daily logs (30d)',
  sst_expirations_next_30d:            'SST cards expiring (30d)',
  days_since_last_activity:            'Days since last activity',
};

const RiskScoreCard = ({ projectId, isAdmin = false }) => {
  // ── Flag check FIRST (rules-of-hooks). Must stay at top of
  //    component, never inside a conditional or after an early
  //    return — see C1.3 incident pattern.
  const v2RiskScoreEnabled = useFeatureFlag('v2_risk_score');

  // The other hooks must also be unconditional. They run on
  // every render even when the flag is off; the return-null is
  // the LAST step of the function body.
  const { colors, isDark } = useTheme();
  const styles = useMemo(() => buildStyles(colors, isDark), [colors, isDark]);

  const [loading, setLoading] = useState(true);
  const [scoreDoc, setScoreDoc] = useState(null);
  const [history, setHistory] = useState([]);
  const [expanded, setExpanded] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewWasCorrect, setReviewWasCorrect] = useState(true);
  const [reviewNotes, setReviewNotes] = useState('');

  useEffect(() => {
    if (!v2RiskScoreEnabled || !projectId) return;
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const [latestResp, historyResp] = await Promise.all([
          apiClient.get(`/api/projects/${projectId}/risk-score`)
            .catch(() => ({ data: null })),
          apiClient.get(`/api/projects/${projectId}/risk-score/history?days=30`)
            .catch(() => ({ data: { history: [] } })),
        ]);
        if (cancelled) return;
        setScoreDoc(latestResp?.data?.score || null);
        setHistory(historyResp?.data?.history || []);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [v2RiskScoreEnabled, projectId]);

  // ── Fail-closed render: flag OFF → nothing. ───────────────
  if (!v2RiskScoreEnabled) {
    return null;
  }

  if (loading) {
    return (
      <GlassCard style={styles.card}>
        <ActivityIndicator color={colors.text.primary} />
      </GlassCard>
    );
  }

  if (!scoreDoc) {
    // Flag on, no score yet — render a calm empty state. Never
    // crash the parent screen.
    return (
      <GlassCard style={styles.card}>
        <View style={styles.headerRow}>
          <ShieldCheck size={20} strokeWidth={1.5} color={colors.text.muted} />
          <Text style={styles.headerLabel}>RISK SCORE</Text>
        </View>
        <Text style={styles.emptyText}>
          No score yet. The next 4 AM ET tick will compute one.
        </Text>
      </GlassCard>
    );
  }

  const score = Number(scoreDoc.score || 0);
  const band = bandFor(score);
  const ciLow = Number(scoreDoc.confidence_low || 0);
  const ciHigh = Number(scoreDoc.confidence_high || 0);
  const factors = Array.isArray(scoreDoc.contributing_factors)
    ? scoreDoc.contributing_factors.slice(0, 5)
    : [];
  const sparkline = (history || [])
    .slice()
    .reverse()  // oldest -> newest for left-to-right rendering
    .map((row) => Number(row.score || 0));

  const onSubmitReview = async () => {
    if (!scoreDoc) return;
    setReviewBusy(true);
    try {
      await apiClient.post(
        `/api/projects/${projectId}/risk-score/calibration`,
        {
          score_id: String(scoreDoc.id || scoreDoc._id || ''),
          was_high_risk_correct: reviewWasCorrect,
          notes: reviewNotes,
        },
      );
      setReviewOpen(false);
      setReviewNotes('');
    } catch (_err) {
      // Soft-fail; the modal stays open so the user can retry.
    } finally {
      setReviewBusy(false);
    }
  };

  return (
    <GlassCard style={[styles.card, { borderColor: band.border, borderWidth: 1.5 }]}>
      <View style={styles.headerRow}>
        {score > 60 ? (
          <ShieldAlert size={20} strokeWidth={1.5} color={band.fg} />
        ) : (
          <ShieldCheck size={20} strokeWidth={1.5} color={band.fg} />
        )}
        <Text style={[styles.headerLabel, { color: band.fg }]}>
          RISK SCORE · {band.label}
        </Text>
      </View>

      <View style={styles.scoreRow}>
        <Text style={[styles.scoreNumber, { color: band.fg }]}>
          {Math.round(score)}
        </Text>
        <Text style={styles.scoreOutOf}>/100</Text>
      </View>

      <Text style={styles.ciText}>
        95% CI: {Math.round(ciLow)} – {Math.round(ciHigh)}
      </Text>

      {sparkline.length > 1 && (
        <View style={styles.sparklineRow}>
          <TrendingUp size={12} strokeWidth={1.5} color={colors.text.muted} />
          <Text style={styles.sparklineText}>
            {sparkline.length}d trend: {sparkline.map((v) => Math.round(v)).join(' · ')}
          </Text>
        </View>
      )}

      <Pressable
        onPress={() => setExpanded(!expanded)}
        style={styles.factorsToggle}
      >
        {expanded ? (
          <ChevronUp size={16} strokeWidth={1.5} color={colors.text.muted} />
        ) : (
          <ChevronDown size={16} strokeWidth={1.5} color={colors.text.muted} />
        )}
        <Text style={styles.factorsToggleText}>
          Top contributing factors
        </Text>
      </Pressable>

      {expanded && (
        <View style={styles.factorsList}>
          {factors.length === 0 ? (
            <Text style={styles.factorEmpty}>No factor breakdown.</Text>
          ) : (
            factors.map((f, i) => {
              const label = FACTOR_LABELS[f.factor] || f.factor;
              const contribution = Number(f.contribution || 0);
              return (
                <View key={`${f.factor}-${i}`} style={styles.factorRow}>
                  <Text style={styles.factorLabel}>{label}</Text>
                  <Text style={styles.factorContribution}>
                    +{contribution.toFixed(1)}
                  </Text>
                </View>
              );
            })
          )}
        </View>
      )}

      {isAdmin && (
        <Pressable
          onPress={() => setReviewOpen(true)}
          style={styles.reviewButton}
        >
          <Text style={styles.reviewButtonText}>
            Was this score correct?
          </Text>
        </Pressable>
      )}

      <Modal
        visible={reviewOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setReviewOpen(false)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <View style={styles.modalHeaderRow}>
              <Text style={styles.modalTitle}>Inspector review</Text>
              <Pressable onPress={() => setReviewOpen(false)}>
                <X size={18} strokeWidth={1.5} color={colors.text.primary} />
              </Pressable>
            </View>
            <Text style={styles.modalSubtitle}>
              Was this risk score correct?
            </Text>
            <View style={styles.modalChoicesRow}>
              <Pressable
                onPress={() => setReviewWasCorrect(true)}
                style={[
                  styles.modalChoice,
                  reviewWasCorrect && styles.modalChoiceActive,
                ]}
              >
                <Text style={styles.modalChoiceText}>Yes</Text>
              </Pressable>
              <Pressable
                onPress={() => setReviewWasCorrect(false)}
                style={[
                  styles.modalChoice,
                  !reviewWasCorrect && styles.modalChoiceActive,
                ]}
              >
                <Text style={styles.modalChoiceText}>No</Text>
              </Pressable>
            </View>
            <TextInput
              value={reviewNotes}
              onChangeText={setReviewNotes}
              placeholder="Notes (optional)"
              placeholderTextColor={colors.text.muted}
              style={styles.modalNotes}
              multiline
            />
            <GlassButton
              onPress={onSubmitReview}
              disabled={reviewBusy}
              style={styles.modalSubmit}
            >
              {reviewBusy ? 'Sending…' : 'Submit review'}
            </GlassButton>
          </View>
        </View>
      </Modal>
    </GlassCard>
  );
};

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    card: {
      padding: spacing.md,
      marginBottom: spacing.md,
    },
    headerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
    },
    headerLabel: {
      fontSize: 11,
      letterSpacing: 0.8,
      fontWeight: '700',
      color: colors.text.muted,
    },
    scoreRow: {
      flexDirection: 'row',
      alignItems: 'flex-end',
      marginTop: spacing.sm,
    },
    scoreNumber: {
      fontSize: 44,
      fontWeight: '700',
      lineHeight: 48,
    },
    scoreOutOf: {
      fontSize: 16,
      color: colors.text.muted,
      marginLeft: 4,
      marginBottom: 6,
    },
    ciText: {
      fontSize: 12,
      color: colors.text.muted,
      marginTop: 2,
    },
    sparklineRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      marginTop: spacing.sm,
    },
    sparklineText: {
      fontSize: 11,
      color: colors.text.muted,
    },
    factorsToggle: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      marginTop: spacing.md,
    },
    factorsToggleText: {
      fontSize: 12,
      color: colors.text.secondary,
    },
    factorsList: {
      marginTop: spacing.sm,
      gap: 4,
    },
    factorEmpty: {
      fontSize: 12,
      color: colors.text.muted,
    },
    factorRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      paddingVertical: 4,
    },
    factorLabel: {
      fontSize: 12,
      color: colors.text.secondary,
      flex: 1,
    },
    factorContribution: {
      fontSize: 12,
      color: colors.text.primary,
      fontWeight: '600',
    },
    emptyText: {
      fontSize: 13,
      color: colors.text.muted,
      marginTop: spacing.sm,
    },
    reviewButton: {
      marginTop: spacing.md,
      paddingVertical: 8,
      paddingHorizontal: 12,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
      borderColor: colors.text.muted,
      alignSelf: 'flex-start',
    },
    reviewButtonText: {
      fontSize: 12,
      color: colors.text.secondary,
    },
    modalBackdrop: {
      flex: 1,
      backgroundColor: 'rgba(0,0,0,0.5)',
      justifyContent: 'center',
      alignItems: 'center',
      padding: spacing.lg,
    },
    modalCard: {
      width: '100%',
      maxWidth: 420,
      backgroundColor: isDark ? '#1a1a1a' : '#ffffff',
      padding: spacing.lg,
      borderRadius: borderRadius.md,
      gap: spacing.sm,
    },
    modalHeaderRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
    },
    modalTitle: {
      fontSize: 16,
      fontWeight: '700',
      color: colors.text.primary,
    },
    modalSubtitle: {
      fontSize: 13,
      color: colors.text.secondary,
    },
    modalChoicesRow: {
      flexDirection: 'row',
      gap: spacing.sm,
    },
    modalChoice: {
      flex: 1,
      paddingVertical: 10,
      alignItems: 'center',
      borderWidth: 1,
      borderRadius: borderRadius.sm,
      borderColor: colors.text.muted,
    },
    modalChoiceActive: {
      backgroundColor: 'rgba(34, 197, 94, 0.15)',
      borderColor: '#22c55e',
    },
    modalChoiceText: {
      color: colors.text.primary,
      fontWeight: '600',
    },
    modalNotes: {
      minHeight: 80,
      borderWidth: 1,
      borderColor: colors.text.muted,
      borderRadius: borderRadius.sm,
      padding: spacing.sm,
      color: colors.text.primary,
      textAlignVertical: 'top',
    },
    modalSubmit: {
      marginTop: spacing.sm,
    },
  });
}

export default RiskScoreCard;
