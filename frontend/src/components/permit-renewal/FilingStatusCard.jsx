/**
 * FilingStatusCard
 * ════════════════
 * MR.14 commit 4c. Renewal-state status card.
 *
 * History:
 *   MR.7   — original; polled GET /filing-jobs every 5s, rendered
 *            CAPTCHA / 2FA prompts, audit-log timeline, cancel
 *            button. Full automation control surface.
 *   MR.14 4a — worker container removed; filing_jobs are no longer
 *            being created by any code path.
 *   MR.14 4b — DOB NOW credentials removed.
 *   MR.14 4c — this commit. The card is rewritten as a pure status
 *            display driven by fields ON THE RENEWAL DOC ITSELF
 *            (manual_renewal_started_at, status, new_expiration_date).
 *            No polling, no audit_log timeline, no operator-input
 *            prompts. Three render branches:
 *              1. Pre-renewal:    "Start Renewal" CTA (parent owns
 *                                  the click handler so it can also
 *                                  open DOB NOW + show the slide-out
 *                                  panel).
 *              2. In-progress:    "Filing in progress" reminder +
 *                                  "View values again" link to re-
 *                                  open the panel.
 *              3. Renewed:        DOB confirmation # + new expiration
 *                                  date (sourced from MR.8's Open
 *                                  Data watcher, which transitions
 *                                  renewal.status → COMPLETED when
 *                                  it sees the new permit at DOB).
 *
 * v1 framing: LeveLog never files. The user files manually at DOB
 * NOW; LeveLog tracks the click and waits for the Open Data watcher
 * to confirm the renewed expiration.
 *
 * Props:
 *   renewal          — the permit_renewal doc, including
 *                      manual_renewal_started_at + status +
 *                      new_expiration_date when present.
 *   readiness        — filing-readiness report (MR.3 shape).
 *                      May be null while loading.
 *   readinessLoading — bool, true while readiness is being fetched.
 *   onStartRenewal   — callback invoked when the operator clicks
 *                      "Start Renewal". Parent runs POST
 *                      /start-renewal-clicked, opens DOB NOW, and
 *                      surfaces the StartRenewalPanel.
 *   onViewValuesAgain — callback to re-open the panel without
 *                      re-recording the click. Shown in the
 *                      in-progress state.
 *   starting         — bool, true while POST /start-renewal-clicked
 *                      is in flight. Disables the button.
 *   error            — { message, code, blockers? } — surfaced when
 *                      the start endpoint or readiness fetch fails.
 */

import React from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from 'react-native';
import {
  CheckCircle,
  Clock,
  AlertCircle,
  Lock,
  Send,
  Eye,
  ShieldCheck,
} from 'lucide-react-native';
import { spacing, borderRadius, typography } from '../../styles/theme';
import { useTheme } from '../../context/ThemeContext';

const formatDate = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
};

const formatDateTime = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
};

// Renewed state covers two source signals:
//   • renewal.status === 'completed' (MR.8 watcher transition), OR
//   • renewal.new_expiration_date is set (defensive — same watcher
//     stamps the field, but a future code path might land the date
//     before the status flip).
const isRenewedState = (renewal) =>
  renewal?.status === 'completed' ||
  Boolean(renewal?.new_expiration_date);

// In-progress state: operator clicked Start Renewal but the Open
// Data watcher hasn't yet detected the new permit at DOB.
const isInProgressState = (renewal) =>
  Boolean(renewal?.manual_renewal_started_at) && !isRenewedState(renewal);

const FilingStatusCard = ({
  renewal,
  readiness,
  readinessLoading,
  onStartRenewal,
  onViewValuesAgain,
  starting,
  error,
}) => {
  const { colors } = useTheme();
  const s = buildStyles(colors);

  if (!renewal) {
    return (
      <View style={s.cardEmpty}>
        <ActivityIndicator size="small" color={colors.text.muted} />
        <Text style={s.emptyText}>Loading status…</Text>
      </View>
    );
  }

  // ── Branch 3: Renewed ──────────────────────────────────────────
  if (isRenewedState(renewal)) {
    return (
      <View style={s.card}>
        <View style={[s.banner, s.bannerSuccess]}>
          <ShieldCheck size={16} color="#10b981" />
          <Text style={[s.bannerText, s.bannerTextSuccess]}>
            Renewed — DOB stamped the new expiration.
          </Text>
        </View>
        {renewal.new_expiration_date && (
          <View style={s.confirmationRow}>
            <Text style={s.confirmationLabel}>New Expiration</Text>
            <Text style={s.confirmationValue}>
              {formatDate(renewal.new_expiration_date)}
            </Text>
          </View>
        )}
        {renewal.dob_confirmation_number && (
          <View style={s.confirmationRow}>
            <Text style={s.confirmationLabel}>DOB Confirmation</Text>
            <Text style={s.confirmationValue}>
              {renewal.dob_confirmation_number}
            </Text>
          </View>
        )}
        <Text style={s.helperText}>
          LeveLog detected this renewal automatically via the NYC Open
          Data feed; no further action is needed.
        </Text>
      </View>
    );
  }

  // ── Branch 2: In-progress (operator clicked, watcher hasn't seen it yet) ──
  if (isInProgressState(renewal)) {
    return (
      <View style={s.card}>
        <View style={[s.banner, s.bannerInfo]}>
          <Clock size={16} color="#3b82f6" />
          <Text style={[s.bannerText, s.bannerTextInfo]}>
            Filing in progress — refresh after submitting at DOB NOW.
          </Text>
        </View>
        <Text style={s.helperText}>
          You started this renewal{' '}
          {formatDateTime(renewal.manual_renewal_started_at)}. After you
          submit at DOB NOW, LeveLog will detect the new permit on the
          next 15-minute Open Data poll and update this card to "Renewed."
        </Text>
        {typeof onViewValuesAgain === 'function' && (
          <Pressable style={s.linkRow} onPress={onViewValuesAgain}>
            <Eye size={13} color={colors.text.primary} />
            <Text style={s.linkText}>View values again</Text>
          </Pressable>
        )}
      </View>
    );
  }

  // ── Branch 1: Pre-renewal (idle / start) ───────────────────────
  return (
    <View style={s.card}>
      {readinessLoading || readiness === null ? (
        <Pressable disabled style={[s.startButton, s.startButtonDisabled]}>
          <ActivityIndicator size="small" color={colors.text.muted} />
          <Text style={s.startButtonText}>Checking readiness…</Text>
        </Pressable>
      ) : !readiness.ready ? (
        <View style={s.disabledStack}>
          <Pressable disabled style={[s.startButton, s.startButtonDisabled]}>
            <Lock size={14} color={colors.text.muted} />
            <Text style={s.startButtonText}>Start Renewal</Text>
          </Pressable>
          <View style={s.blockersBlock}>
            <Text style={s.blockersHeader}>
              Blocked — resolve before starting:
            </Text>
            {(readiness.blockers || []).map((b, i) => (
              <Text key={i} style={s.blockerItem}>• {b}</Text>
            ))}
          </View>
        </View>
      ) : (
        <View style={s.activeStack}>
          <Pressable
            style={[
              s.startButton,
              s.startButtonActive,
              starting && s.buttonDisabled,
            ]}
            onPress={onStartRenewal}
            disabled={starting}
          >
            {starting ? (
              <>
                <ActivityIndicator size="small" color="#fff" />
                <Text style={[s.startButtonText, s.startButtonTextActive]}>
                  Starting…
                </Text>
              </>
            ) : (
              <>
                <Send size={14} color="#fff" />
                <Text style={[s.startButtonText, s.startButtonTextActive]}>
                  Start Renewal
                </Text>
              </>
            )}
          </Pressable>
          <Text style={s.helperText}>
            Opens DOB NOW in a new tab and shows your pre-filled values
            to copy in. LeveLog tracks the click; you file manually.
          </Text>
          {error && (
            <View style={s.errorBlock}>
              <AlertCircle size={14} color="#ef4444" />
              <View style={{ flex: 1 }}>
                <Text style={s.errorMessage}>
                  {error.message || 'Could not start renewal.'}
                </Text>
                {Array.isArray(error.blockers) && error.blockers.length > 0 && (
                  <View style={{ marginTop: 4 }}>
                    {error.blockers.map((b, i) => (
                      <Text key={i} style={s.errorBlockerItem}>• {b}</Text>
                    ))}
                  </View>
                )}
                {error.code && (
                  <Text style={s.errorCode}>code: {error.code}</Text>
                )}
              </View>
            </View>
          )}
        </View>
      )}
    </View>
  );
};

export default FilingStatusCard;

// Exported so tests can pin the state-derivation rules without
// reaching into render output.
export const _internals = {
  isRenewedState,
  isInProgressState,
};

// ── Styles ───────────────────────────────────────────────────────

function buildStyles(colors) {
  return StyleSheet.create({
    card: {
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      padding: spacing.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      gap: spacing.md,
      marginTop: spacing.sm,
    },
    cardEmpty: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      padding: spacing.md,
    },
    emptyText: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.muted,
    },

    // ── banners ───────────────────────────────────────────────────
    banner: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 8,
      padding: spacing.sm,
      borderRadius: borderRadius.md,
      borderWidth: 1,
    },
    bannerSuccess: {
      backgroundColor: '#10b98115',
      borderColor: '#10b98140',
    },
    bannerInfo: {
      backgroundColor: '#3b82f615',
      borderColor: '#3b82f640',
    },
    bannerText: {
      flex: 1,
      fontFamily: typography.medium,
      fontSize: 12,
      lineHeight: 18,
    },
    bannerTextSuccess: {
      color: '#065f46',
    },
    bannerTextInfo: {
      color: '#1e3a8a',
    },

    // ── helper text ───────────────────────────────────────────────
    helperText: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.secondary,
      lineHeight: 18,
    },

    // ── confirmation rows (renewed state) ─────────────────────────
    confirmationRow: {
      paddingVertical: spacing.sm,
      paddingHorizontal: spacing.md,
      backgroundColor: '#10b98115',
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: '#10b98140',
    },
    confirmationLabel: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      letterSpacing: 0.3,
      marginBottom: 2,
    },
    confirmationValue: {
      fontFamily: typography.semibold,
      fontSize: 16,
      color: colors.text.primary,
    },

    // ── start button (pre-renewal) ────────────────────────────────
    activeStack: {
      gap: spacing.sm,
    },
    disabledStack: {
      gap: spacing.sm,
    },
    startButton: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 8,
      paddingVertical: spacing.sm + 2,
      paddingHorizontal: spacing.md,
      borderRadius: borderRadius.md,
    },
    startButtonActive: {
      backgroundColor: '#3b82f6',
    },
    startButtonDisabled: {
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
      opacity: 0.7,
    },
    startButtonText: {
      fontFamily: typography.semibold,
      fontSize: 14,
      color: colors.text.muted,
      letterSpacing: 0.3,
    },
    startButtonTextActive: {
      color: '#fff',
    },
    buttonDisabled: {
      opacity: 0.6,
    },

    // ── blockers (readiness fail) ────────────────────────────────
    blockersBlock: {
      padding: spacing.sm,
      backgroundColor: '#f59e0b15',
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: '#f59e0b40',
      gap: 4,
    },
    blockersHeader: {
      fontFamily: typography.semibold,
      fontSize: 12,
      color: '#f59e0b',
      marginBottom: 2,
    },
    blockerItem: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.secondary,
      lineHeight: 18,
    },

    // ── view values again link (in-progress) ─────────────────────
    linkRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      paddingVertical: spacing.xs,
    },
    linkText: {
      fontFamily: typography.medium,
      fontSize: 13,
      color: colors.text.primary,
      textDecorationLine: 'underline',
    },

    // ── error block ──────────────────────────────────────────────
    errorBlock: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 8,
      padding: spacing.sm,
      backgroundColor: '#ef444415',
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: '#ef444440',
    },
    errorMessage: {
      fontFamily: typography.medium,
      fontSize: 12,
      color: '#ef4444',
    },
    errorBlockerItem: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: '#ef4444',
      lineHeight: 18,
    },
    errorCode: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: '#ef4444',
      opacity: 0.8,
      marginTop: 2,
    },
  });
}
