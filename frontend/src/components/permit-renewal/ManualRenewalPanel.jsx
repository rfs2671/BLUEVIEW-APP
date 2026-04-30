/**
 * ManualRenewalPanel
 * ══════════════════
 * Renders the structured manual-renewal panel for permits the v2
 * dispatcher emits with action.kind === "manual_renewal_dob_now"
 * (the MANUAL_1YR_CEILING strategy in backend/lib/eligibility_v2.py).
 *
 * History:
 *   MR.1 (commit 967294c) — introduced inline; pure information layer.
 *   MR.1.5 (commit 8daee73) — extracted to its own component file +
 *     wired through the actionRenderers-map dispatch.
 *   MR.1.6 (commit 50bf481) — issuance_date plumbing for date-specific copy.
 *   MR.7 (this commit)     — replaces the disabled "Prepare Filing"
 *     placeholder with a live "File Renewal" button. When a filing_job
 *     is active for this permit, renders FilingStatusCard in place of
 *     the button. Caption: "Filed under your own DOB NOW credentials
 *     by the LeveLog agent." Readiness gate (MR.3) blocks the button
 *     with a blocker-summary tooltip when filing-readiness reports
 *     ready=false.
 *
 * Props:
 *   renewal         — the permit_renewal doc (MR.1's contract).
 *   filingJobs      — array of filing_jobs for this permit_renewal_id,
 *                     newest-first. MR.6's GET response shape. Pass
 *                     [] if not yet loaded; the panel renders the idle
 *                     File button in that case (no flash of empty state).
 *   onJobsChange    — callback invoked after enqueue / cancel / status
 *                     transition to ask the parent to refetch the jobs
 *                     for this renewal.
 */

import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
} from 'react-native';
import { Send, Lock } from 'lucide-react-native';
import { spacing, borderRadius, typography } from '../../styles/theme';
import { useTheme } from '../../context/ThemeContext';
import { MANUAL_RENEWAL_RULE_CITATION } from '../../constants/dobRules';
import apiClient from '../../utils/api';
import FilingStatusCard from './FilingStatusCard';

// MR.6 terminal statuses — kept in sync with FilingStatusCard.jsx
// and backend/server.py FILING_JOB_TERMINAL_STATUSES.
const TERMINAL_STATUSES = new Set([
  'filed', 'completed', 'failed', 'cancelled',
]);

// Local formatDate — matches the helper in
// frontend/app/project/[id]/permit-renewal.jsx line ~132. Inlined
// here rather than promoted to a shared util to keep MR.1.5 a
// pure refactor; future commit can DRY this up if a third caller
// emerges.
const formatDate = (dateStr) => {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) {
    if (typeof dateStr === 'string' && dateStr.includes('/')) return dateStr;
    return String(dateStr).slice(0, 10);
  }
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
};

const ManualRenewalPanel = ({ renewal, filingJobs = [], onJobsChange }) => {
  const { colors } = useTheme();
  const s = buildStyles(colors);

  // Active filing job = newest non-terminal entry. The list is sorted
  // newest-first by the backend so [0] when present is the relevant one.
  const activeJob =
    filingJobs.find((j) => !TERMINAL_STATUSES.has(j.status)) || null;

  // Readiness gate state — only fetched when there's no active job AND
  // the operator might click File. We don't pre-fetch readiness for
  // every panel mount because /filing-readiness runs 10 checks on the
  // server and is heavier than a single doc fetch. We fetch on first
  // render of the idle state only.
  const [readiness, setReadiness] = useState(null);
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [enqueueLoading, setEnqueueLoading] = useState(false);
  const [enqueueError, setEnqueueError] = useState(null);

  // Fetch readiness when the idle button could render (no active job).
  // Re-fetch when the jobs list flips back to "no active" (e.g. after
  // a job completes or is cancelled and the operator might re-file).
  useEffect(() => {
    if (activeJob) return undefined;
    let cancelled = false;
    setReadinessLoading(true);
    apiClient
      .get(`/api/permit-renewals/${renewal.id || renewal._id}/filing-readiness`)
      .then((resp) => {
        if (!cancelled) setReadiness(resp.data);
      })
      .catch((e) => {
        // Soft fail — show a neutral state (button disabled with a
        // generic message) rather than blocking the whole panel.
        if (!cancelled) {
          console.warn('[ManualRenewalPanel] readiness fetch failed:', e?.message);
          setReadiness({ ready: false, blockers: ['Could not check readiness'] });
        }
      })
      .finally(() => {
        if (!cancelled) setReadinessLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeJob, renewal.id, renewal._id]);

  const handleFile = async () => {
    setEnqueueLoading(true);
    setEnqueueError(null);
    try {
      await apiClient.post(
        `/api/permit-renewals/${renewal.id || renewal._id}/file`
      );
      // Tell the parent to re-fetch jobs; the next render will show
      // FilingStatusCard with the freshly-queued job.
      if (typeof onJobsChange === 'function') {
        onJobsChange();
      }
    } catch (e) {
      // The 6-gate enqueue endpoint surfaces structured detail.code
      // values: mode_not_live, readiness_blocked, mapper_unmappable_fields,
      // no_filing_rep, no_active_credential, filing_job_already_active,
      // redis_enqueue_failed. We surface a friendly message + the
      // structured code so the operator (or support) can correlate.
      const detail = e?.response?.data?.detail;
      const code = typeof detail === 'object' ? detail.code : null;
      const message = typeof detail === 'object'
        ? (detail.message || 'Enqueue failed')
        : (typeof detail === 'string' ? detail : 'Enqueue failed');
      setEnqueueError({ code, message });
      setEnqueueLoading(false);
    }
  };

  return (
    <View style={s.manualRenewalPanel}>
      <Text style={s.manualRenewalHeader}>
        Manual Renewal Required
      </Text>
      <Text style={s.manualRenewalExplanation}>
        {renewal.issuance_date
          ? `This permit was issued on ${formatDate(renewal.issuance_date)}. NYC DOB requires work permits older than one year to be renewed manually, regardless of insurance status. Filing happens at DOB NOW with the licensee's NYC.ID.`
          : `This permit has reached the one-year mark from original issuance. NYC DOB requires work permits older than one year to be renewed manually, regardless of insurance status. Filing happens at DOB NOW with the licensee's NYC.ID.`}
      </Text>

      <View style={s.manualRenewalFeeBlock}>
        <Text style={s.manualRenewalFee}>$130</Text>
        <Text style={s.manualRenewalFeeCaption}>
          paid directly to NYC DOB
        </Text>
      </View>

      <View style={s.manualRenewalDetails}>
        <View style={s.manualRenewalDetailRow}>
          <Text style={s.manualRenewalDetailLabel}>
            Job Filing Number
          </Text>
          <Text style={s.manualRenewalDetailValue}>
            {renewal.job_number || '—'}
          </Text>
        </View>
        <View style={s.manualRenewalDetailRow}>
          <Text style={s.manualRenewalDetailLabel}>
            Work Type
          </Text>
          <Text style={s.manualRenewalDetailValue}>
            {renewal.permit_type || '—'}
          </Text>
        </View>
        <View style={s.manualRenewalDetailRow}>
          <Text style={s.manualRenewalDetailLabel}>
            Current Expiration
          </Text>
          <Text style={s.manualRenewalDetailValue}>
            {formatDate(renewal.current_expiration)}
          </Text>
        </View>
        <View style={s.manualRenewalDetailRow}>
          <Text style={s.manualRenewalDetailLabel}>
            Days Until Expiration
          </Text>
          <Text style={s.manualRenewalDetailValue}>
            {typeof renewal.days_until_expiry === 'number'
              ? `${renewal.days_until_expiry}d`
              : '—'}
          </Text>
        </View>
      </View>

      {/* MR.7: live trigger OR FilingStatusCard depending on whether
          a non-terminal filing job exists for this renewal. */}
      {activeJob ? (
        <FilingStatusCard
          permitRenewalId={renewal.id || renewal._id}
          initialJob={activeJob}
          onJobUpdate={() => {
            // FilingStatusCard polls and feeds us the freshest job;
            // we ask the parent to re-sync its master jobs list so
            // History (and any other consumers) stay aligned.
            if (typeof onJobsChange === 'function') onJobsChange();
          }}
          onTerminal={() => {
            if (typeof onJobsChange === 'function') onJobsChange();
          }}
          onRetryRequested={handleFile}
        />
      ) : (
        <View style={s.idleStateBlock}>
          <FilingButton
            readiness={readiness}
            readinessLoading={readinessLoading}
            enqueueLoading={enqueueLoading}
            enqueueError={enqueueError}
            onPress={handleFile}
            colors={colors}
            styles={s}
          />
          <Text style={s.manualRenewalCtaCaption}>
            Filed under your own DOB NOW credentials by the LeveLog agent.
          </Text>
        </View>
      )}

      <Text style={s.manualRenewalCitation}>
        Reference: {MANUAL_RENEWAL_RULE_CITATION}
      </Text>
    </View>
  );
};

// ── FilingButton subcomponent ──────────────────────────────────────

const FilingButton = ({
  readiness,
  readinessLoading,
  enqueueLoading,
  enqueueError,
  onPress,
  colors,
  styles: s,
}) => {
  // Loading state while readiness resolves — render a stable button
  // shape so layout doesn't jump. We disable until we know.
  if (readinessLoading || readiness === null) {
    return (
      <Pressable disabled style={[s.manualRenewalCta, s.manualRenewalCtaDisabled]}>
        <ActivityIndicator size="small" color={colors.text.muted} />
        <Text style={s.manualRenewalCtaText}>Checking readiness…</Text>
      </Pressable>
    );
  }

  if (!readiness.ready) {
    // Disabled button + blockers list. React Native doesn't have a
    // native tooltip primitive, so we render the blockers as a
    // compact bullet list under the button — operator sees the
    // reason without hover.
    const blockers = readiness.blockers || [];
    return (
      <View style={s.disabledStack}>
        <Pressable disabled style={[s.manualRenewalCta, s.manualRenewalCtaDisabled]}>
          <Lock size={14} color={colors.text.muted} />
          <Text style={s.manualRenewalCtaText}>File Renewal</Text>
        </Pressable>
        <View style={s.blockersBlock}>
          <Text style={s.blockersHeader}>Blocked — resolve before filing:</Text>
          {blockers.map((b, i) => (
            <Text key={i} style={s.blockerItem}>• {b}</Text>
          ))}
        </View>
      </View>
    );
  }

  // Idle / loading / error states for the active button.
  return (
    <View style={s.activeStack}>
      <Pressable
        style={[
          s.manualRenewalCta,
          s.manualRenewalCtaActive,
          enqueueLoading && s.buttonDisabled,
        ]}
        onPress={onPress}
        disabled={enqueueLoading}
      >
        {enqueueLoading ? (
          <>
            <ActivityIndicator size="small" color="#fff" />
            <Text style={[s.manualRenewalCtaText, s.manualRenewalCtaTextActive]}>
              Enqueuing…
            </Text>
          </>
        ) : (
          <>
            <Send size={14} color="#fff" />
            <Text style={[s.manualRenewalCtaText, s.manualRenewalCtaTextActive]}>
              File Renewal
            </Text>
          </>
        )}
      </Pressable>
      {enqueueError && (
        <View style={s.errorBlock}>
          <Text style={s.errorMessage}>{enqueueError.message}</Text>
          {enqueueError.code && (
            <Text style={s.errorCode}>code: {enqueueError.code}</Text>
          )}
        </View>
      )}
    </View>
  );
};

// ── Styles ─────────────────────────────────────────────────────────

function buildStyles(colors) {
  return StyleSheet.create({
    manualRenewalPanel: {
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      padding: spacing.lg,
      marginBottom: spacing.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    manualRenewalHeader: {
      fontFamily: typography.semibold,
      fontSize: 16,
      color: colors.text.primary,
      marginBottom: spacing.sm,
    },
    manualRenewalExplanation: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.secondary,
      lineHeight: 19,
      marginBottom: spacing.md,
    },
    manualRenewalFeeBlock: {
      flexDirection: 'row',
      alignItems: 'baseline',
      gap: spacing.sm,
      marginBottom: spacing.md,
      paddingVertical: spacing.sm,
      paddingHorizontal: spacing.md,
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    manualRenewalFee: {
      fontFamily: typography.semibold,
      fontSize: 22,
      color: colors.text.primary,
    },
    manualRenewalFeeCaption: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.muted,
    },
    manualRenewalDetails: {
      marginBottom: spacing.md,
      gap: 4,
    },
    manualRenewalDetailRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      paddingVertical: 4,
    },
    manualRenewalDetailLabel: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.muted,
    },
    manualRenewalDetailValue: {
      fontFamily: typography.medium,
      fontSize: 13,
      color: colors.text.primary,
    },

    // ── CTA stack ─────────────────────────────────────────────────
    idleStateBlock: {
      gap: 6,
      marginTop: spacing.xs,
    },
    activeStack: {
      gap: spacing.sm,
    },
    disabledStack: {
      gap: spacing.sm,
    },
    manualRenewalCta: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 8,
      paddingVertical: spacing.sm + 2,
      paddingHorizontal: spacing.md,
      borderRadius: borderRadius.md,
      marginTop: spacing.xs,
    },
    manualRenewalCtaActive: {
      backgroundColor: '#3b82f6',
      borderWidth: 0,
    },
    manualRenewalCtaDisabled: {
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
      opacity: 0.7,
    },
    buttonDisabled: {
      opacity: 0.6,
    },
    manualRenewalCtaText: {
      fontFamily: typography.semibold,
      fontSize: 14,
      color: colors.text.muted,
      letterSpacing: 0.3,
    },
    manualRenewalCtaTextActive: {
      color: '#fff',
    },
    manualRenewalCtaCaption: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      textAlign: 'center',
      marginTop: 6,
      marginBottom: spacing.sm,
    },

    // ── blockers ──────────────────────────────────────────────────
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

    // ── error block ───────────────────────────────────────────────
    errorBlock: {
      padding: spacing.sm,
      backgroundColor: '#ef444415',
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: '#ef444440',
      gap: 2,
    },
    errorMessage: {
      fontFamily: typography.medium,
      fontSize: 12,
      color: '#ef4444',
    },
    errorCode: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: '#ef4444',
      opacity: 0.8,
    },

    // ── citation ──────────────────────────────────────────────────
    manualRenewalCitation: {
      fontFamily: typography.regular,
      fontSize: 11,
      fontStyle: 'italic',
      color: colors.text.muted,
      marginTop: spacing.sm,
      paddingTop: spacing.sm,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
    },
  });
}

export default ManualRenewalPanel;
