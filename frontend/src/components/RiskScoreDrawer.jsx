/**
 * Phase V2.1.2 — Risk Score side drawer.
 *
 * Slides in from the right when the operator taps a
 * <RiskScoreCircle/>. Renders the full score breakdown that the
 * old full-width RiskScoreCard used to take a whole row for:
 *
 *   • Big score number with band color
 *   • 95% confidence interval
 *   • Top 5 contributing factors with proportional bars
 *   • "Recalculate now" button — POST /risk-score/calculate
 *   • Inspector review modal trigger (admin only)
 *
 * Behavior:
 *   • Visible iff `visible === true` (parent owns the open state).
 *   • Closes on: X button, Escape key (web), backdrop tap.
 *   • Fetches on open if no `initialScore` was passed; honors
 *     `initialScore` so the parent's pre-fetched data flows
 *     through and there's no flash of empty state.
 *   • Drawer width: 460 px on desktop. <768 px viewport falls
 *     back to full-width via the StyleSheet's responsive media-
 *     query approximation (Dimensions hook).
 *
 * Hard rules pinned by tests:
 *   • useFeatureFlag('v2_risk_score') is the FIRST hook in the
 *     component (rules-of-hooks; same pattern as RiskScoreCircle).
 *   • Flag OFF returns null BEFORE any fetch.
 *   • Calibration POST goes to
 *     /api/projects/{id}/risk-score/calibration.
 *   • Recalculate POST goes to
 *     /api/projects/{id}/risk-score/calculate.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  ScrollView,
  Modal,
  Animated,
  Dimensions,
  TextInput,
  Platform,
} from 'react-native';
import {
  X,
  ShieldCheck,
  ShieldAlert,
  RefreshCw,
} from 'lucide-react-native';
import { useFeatureFlag } from '../hooks/useFeatureFlag';
import { useTheme } from '../context/ThemeContext';
import GlassButton from './GlassButton';
import { spacing, borderRadius, typography } from '../styles/theme';
import apiClient from '../utils/api';
import { bandFor, RISK_SCORE_TITLE } from './RiskScoreCircle';

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

const RiskScoreDrawer = ({
  projectId,
  isAdmin = false,
  visible,
  onClose,
  initialScore = null,
}) => {
  // ── Flag check FIRST (rules-of-hooks). Same pattern as the
  //    circle component. ─────────────────────────────────────
  const v2RiskScoreEnabled = useFeatureFlag('v2_risk_score');

  // All hooks unconditional — the return-null at the bottom is
  // the LAST step.
  const { colors, isDark } = useTheme();
  const styles = useMemo(() => buildStyles(colors, isDark), [colors, isDark]);
  const [scoreDoc, setScoreDoc] = useState(initialScore);
  const [loading, setLoading]   = useState(false);
  const [recalcBusy, setRecalcBusy] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewWasCorrect, setReviewWasCorrect] = useState(true);
  const [reviewNotes, setReviewNotes] = useState('');

  // Track the latest initialScore so a parent re-fetch flows
  // through. Skipped if the operator has already triggered a
  // recalc — they want to see THEIR result, not the stale one.
  useEffect(() => {
    if (initialScore && !scoreDoc) {
      setScoreDoc(initialScore);
    }
  }, [initialScore, scoreDoc]);

  // Open-time fetch, only if the parent didn't provide one.
  useEffect(() => {
    if (!v2RiskScoreEnabled || !visible || !projectId) return;
    if (scoreDoc) return;
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const r = await apiClient.get(
          `/api/projects/${projectId}/risk-score`,
        );
        if (!cancelled) setScoreDoc(r?.data?.score || null);
      } catch (_e) {
        if (!cancelled) setScoreDoc(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [v2RiskScoreEnabled, visible, projectId, scoreDoc]);

  // ESC-to-close on web. RN-Web wires keypresses to window.
  useEffect(() => {
    if (Platform.OS !== 'web' || !visible) return;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose && onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [visible, onClose]);

  const onRecalc = useCallback(async () => {
    if (!projectId) return;
    setRecalcBusy(true);
    try {
      const r = await apiClient.post(
        `/api/projects/${projectId}/risk-score/calculate`,
      );
      if (r?.data?.score) {
        setScoreDoc(r.data.score);
      }
    } catch (_e) {
      // Soft-fail. The button stops spinning; data stays stale.
    } finally {
      setRecalcBusy(false);
    }
  }, [projectId]);

  const onSubmitReview = useCallback(async () => {
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
    } catch (_e) {
      // Modal stays open so the operator can retry.
    } finally {
      setReviewBusy(false);
    }
  }, [projectId, scoreDoc, reviewWasCorrect, reviewNotes]);

  // ── Fail-closed render: flag OFF → nothing. ────────────────
  if (!v2RiskScoreEnabled) {
    return null;
  }
  if (!visible) {
    return null;
  }

  const hasScore = scoreDoc && typeof scoreDoc.score === 'number';
  const score    = hasScore ? Number(scoreDoc.score) : null;
  const band     = hasScore ? bandFor(score) : null;
  const bandFg   = band ? band.fg : colors.text.muted;
  const ciLow    = hasScore ? Math.round(Number(scoreDoc.confidence_low  || 0)) : 0;
  const ciHigh   = hasScore ? Math.round(Number(scoreDoc.confidence_high || 0)) : 0;
  const factors  = Array.isArray(scoreDoc?.contributing_factors)
    ? scoreDoc.contributing_factors.slice(0, 5)
    : [];

  // Mobile responsive — the drawer becomes full-width when the
  // viewport is narrower than 768 px. Computed at render time so
  // it tracks orientation changes.
  const winW = Dimensions.get('window').width;
  const drawerWidth = winW < 768 ? winW : 460;

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <Pressable style={styles.backdrop} onPress={onClose}>
        {/* Inner Pressable swallows backdrop taps so clicks INSIDE
            the drawer don't close it. */}
        <Pressable
          style={[styles.drawer, { width: drawerWidth }]}
          onPress={(e) => e.stopPropagation && e.stopPropagation()}
        >
          <View style={styles.headerRow}>
            <View style={styles.headerLeft}>
              {hasScore && score > 60 ? (
                <ShieldAlert size={20} strokeWidth={1.5} color={bandFg} />
              ) : (
                <ShieldCheck size={20} strokeWidth={1.5} color={bandFg} />
              )}
              {/* V2.1.4 — header title now matches the circle's
                  title text ("DOB Risk Score") so the drawer
                  reads as a continuation of the gauge the user
                  just clicked. The band label moves to a
                  prominent line under the score number below. */}
              <Text style={[styles.headerTitle, { color: bandFg }]}>
                {RISK_SCORE_TITLE.toUpperCase()}
              </Text>
            </View>
            <Pressable
              onPress={onClose}
              accessibilityRole="button"
              accessibilityLabel="Close drawer"
              style={styles.closeButton}
            >
              <X size={18} strokeWidth={1.5} color={colors.text.primary} />
            </Pressable>
          </View>

          <ScrollView
            contentContainerStyle={styles.body}
            showsVerticalScrollIndicator={false}
          >
            {loading && !hasScore ? (
              <ActivityIndicator color={colors.text.primary} />
            ) : !hasScore ? (
              <Text style={styles.emptyText}>
                No score yet. The next 4 AM ET tick will compute one,
                or use Recalculate now to force one immediately.
              </Text>
            ) : (
              <>
                <View style={styles.scoreRow}>
                  <Text style={[styles.scoreNumber, { color: bandFg }]}>
                    {Math.round(score)}
                  </Text>
                  <Text style={styles.scoreOutOf}>/ 100</Text>
                </View>
                {/* V2.1.4 — band-word ("LOW RISK" / "MODERATE
                    RISK" / etc.) displayed prominently below the
                    score number, color-matched to the band. Same
                    label string as the circle's band-word so the
                    user sees a consistent verdict in both places. */}
                {band && (
                  <Text style={[styles.bandWord, { color: bandFg }]}>
                    {band.label}
                  </Text>
                )}
                <Text style={styles.ciText}>
                  95% confidence interval: {ciLow} – {ciHigh}
                </Text>

                <Text style={styles.sectionLabel}>
                  TOP CONTRIBUTING FACTORS
                </Text>
                <View style={styles.factorsList}>
                  {factors.length === 0 ? (
                    <Text style={styles.emptyText}>
                      No factor breakdown.
                    </Text>
                  ) : (
                    factors.map((f, i) => {
                      const label = FACTOR_LABELS[f.factor] || f.factor;
                      const contribution = Number(f.contribution || 0);
                      const weight = Number(f.weight || 0);
                      const fillPct = weight > 0
                        ? Math.max(0, Math.min(1, contribution / weight))
                        : 0;
                      return (
                        <View key={`${f.factor}-${i}`} style={styles.factorRow}>
                          <View style={styles.factorHeaderRow}>
                            <Text style={styles.factorLabel}>{label}</Text>
                            <Text style={styles.factorContribution}>
                              +{contribution.toFixed(1)}
                            </Text>
                          </View>
                          <View style={styles.factorBarTrack}>
                            <View
                              style={[
                                styles.factorBarFill,
                                {
                                  width: `${fillPct * 100}%`,
                                  backgroundColor: bandFg,
                                },
                              ]}
                            />
                          </View>
                        </View>
                      );
                    })
                  )}
                </View>
              </>
            )}
          </ScrollView>

          <View style={styles.footerRow}>
            <Pressable
              onPress={onRecalc}
              disabled={recalcBusy}
              accessibilityRole="button"
              accessibilityLabel="Recalculate now"
              style={({ pressed }) => [
                styles.recalcButton,
                pressed && { opacity: 0.7 },
                recalcBusy && { opacity: 0.5 },
              ]}
            >
              <RefreshCw
                size={14}
                strokeWidth={1.5}
                color={colors.text.primary}
              />
              <Text style={styles.recalcText}>
                {recalcBusy ? 'Recalculating…' : 'Recalculate now'}
              </Text>
            </Pressable>

            {isAdmin && hasScore && (
              <Pressable
                onPress={() => setReviewOpen(true)}
                accessibilityRole="button"
                style={styles.reviewButton}
              >
                <Text style={styles.reviewButtonText}>
                  Was this correct?
                </Text>
              </Pressable>
            )}
          </View>
        </Pressable>
      </Pressable>

      {/* Inspector-review modal nested inside the drawer Modal —
          two layers of Modal stack cleanly on RN-Web. */}
      <Modal
        visible={reviewOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setReviewOpen(false)}
      >
        <View style={styles.reviewBackdrop}>
          <View style={styles.reviewCard}>
            <View style={styles.reviewHeaderRow}>
              <Text style={styles.reviewTitle}>Inspector review</Text>
              <Pressable onPress={() => setReviewOpen(false)}>
                <X size={18} strokeWidth={1.5} color={colors.text.primary} />
              </Pressable>
            </View>
            <Text style={styles.reviewPrompt}>
              Was this risk score correct?
            </Text>
            <View style={styles.reviewChoicesRow}>
              <Pressable
                onPress={() => setReviewWasCorrect(true)}
                style={[
                  styles.reviewChoice,
                  reviewWasCorrect && styles.reviewChoiceActive,
                ]}
              >
                <Text style={styles.reviewChoiceText}>Yes</Text>
              </Pressable>
              <Pressable
                onPress={() => setReviewWasCorrect(false)}
                style={[
                  styles.reviewChoice,
                  !reviewWasCorrect && styles.reviewChoiceActive,
                ]}
              >
                <Text style={styles.reviewChoiceText}>No</Text>
              </Pressable>
            </View>
            <TextInput
              value={reviewNotes}
              onChangeText={setReviewNotes}
              placeholder="Notes (optional)"
              placeholderTextColor={colors.text.muted}
              style={styles.reviewNotes}
              multiline
            />
            <GlassButton
              onPress={onSubmitReview}
              disabled={reviewBusy}
              style={styles.reviewSubmit}
            >
              {reviewBusy ? 'Sending…' : 'Submit review'}
            </GlassButton>
          </View>
        </View>
      </Modal>
    </Modal>
  );
};

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    backdrop: {
      flex: 1,
      backgroundColor: 'rgba(0, 0, 0, 0.45)',
      // Drawer slides in from the right; aligning to flex-end
      // achieves "right side of viewport".
      flexDirection: 'row',
      justifyContent: 'flex-end',
    },
    drawer: {
      height: '100%',
      backgroundColor: isDark ? '#0A1929' : '#ffffff',
      borderLeftWidth: 1,
      borderLeftColor: colors.border.subtle,
      paddingTop: spacing.lg,
      shadowColor: '#000',
      shadowOpacity: 0.3,
      shadowOffset: { width: -4, height: 0 },
      shadowRadius: 16,
    },
    headerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingBottom: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: colors.border.subtle,
    },
    headerLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
    },
    headerTitle: {
      fontSize: 12,
      letterSpacing: 0.8,
      fontWeight: '700',
    },
    closeButton: {
      padding: 6,
      borderRadius: borderRadius.sm,
    },
    body: {
      paddingHorizontal: spacing.lg,
      paddingTop: spacing.md,
      paddingBottom: spacing.xl,
    },
    scoreRow: {
      flexDirection: 'row',
      alignItems: 'flex-end',
    },
    scoreNumber: {
      fontSize: 56,
      fontWeight: '700',
      lineHeight: 60,
    },
    scoreOutOf: {
      fontSize: 18,
      color: colors.text.muted,
      marginLeft: 6,
      marginBottom: 8,
    },
    bandWord: {
      // V2.1.4 — drawer-body band-word. Slightly larger than the
      // circle's band-word so it reads as a verdict heading.
      marginTop: 4,
      fontSize: 14,
      fontWeight: '700',
      letterSpacing: 1.2,
    },
    ciText: {
      fontSize: 13,
      color: colors.text.muted,
      marginTop: 4,
    },
    sectionLabel: {
      marginTop: spacing.lg,
      marginBottom: spacing.sm,
      fontSize: 11,
      letterSpacing: 0.8,
      fontWeight: '700',
      color: colors.text.muted,
    },
    factorsList: {
      gap: spacing.sm,
    },
    factorRow: {
      gap: 4,
    },
    factorHeaderRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
    },
    factorLabel: {
      fontSize: 13,
      color: colors.text.secondary,
      flex: 1,
    },
    factorContribution: {
      fontSize: 13,
      color: colors.text.primary,
      fontWeight: '600',
    },
    factorBarTrack: {
      height: 4,
      backgroundColor: colors.border.subtle,
      borderRadius: 2,
      overflow: 'hidden',
    },
    factorBarFill: {
      height: 4,
      borderRadius: 2,
    },
    emptyText: {
      fontSize: 13,
      color: colors.text.muted,
      lineHeight: 20,
    },
    footerRow: {
      flexDirection: 'row',
      gap: spacing.sm,
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderTopWidth: 1,
      borderTopColor: colors.border.subtle,
    },
    recalcButton: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      paddingVertical: 8,
      paddingHorizontal: 12,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
      borderColor: colors.border.medium,
    },
    recalcText: {
      fontSize: 12,
      color: colors.text.primary,
      fontWeight: '500',
    },
    reviewButton: {
      paddingVertical: 8,
      paddingHorizontal: 12,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
      borderColor: colors.text.muted,
    },
    reviewButtonText: {
      fontSize: 12,
      color: colors.text.secondary,
    },
    reviewBackdrop: {
      flex: 1,
      backgroundColor: 'rgba(0,0,0,0.5)',
      justifyContent: 'center',
      alignItems: 'center',
      padding: spacing.lg,
    },
    reviewCard: {
      width: '100%',
      maxWidth: 420,
      backgroundColor: isDark ? '#1a1a1a' : '#ffffff',
      padding: spacing.lg,
      borderRadius: borderRadius.md,
      gap: spacing.sm,
    },
    reviewHeaderRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
    },
    reviewTitle: {
      fontSize: 16,
      fontWeight: '700',
      color: colors.text.primary,
    },
    reviewPrompt: {
      fontSize: 13,
      color: colors.text.secondary,
    },
    reviewChoicesRow: {
      flexDirection: 'row',
      gap: spacing.sm,
    },
    reviewChoice: {
      flex: 1,
      paddingVertical: 10,
      alignItems: 'center',
      borderWidth: 1,
      borderRadius: borderRadius.sm,
      borderColor: colors.text.muted,
    },
    reviewChoiceActive: {
      backgroundColor: 'rgba(34, 197, 94, 0.15)',
      borderColor: '#22c55e',
    },
    reviewChoiceText: {
      color: colors.text.primary,
      fontWeight: '600',
    },
    reviewNotes: {
      minHeight: 80,
      borderWidth: 1,
      borderColor: colors.text.muted,
      borderRadius: borderRadius.sm,
      padding: spacing.sm,
      color: colors.text.primary,
      textAlignVertical: 'top',
    },
    reviewSubmit: {
      marginTop: spacing.sm,
    },
  });
}

export default RiskScoreDrawer;
