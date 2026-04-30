/**
 * FilingHistorySection
 * ════════════════════
 * MR.7. Read-only collapsed listing of every filing_job (terminal +
 * non-terminal) for a permit_renewal_id. Operator clicks to expand;
 * each row shows status, created_at, completed_at, dob_confirmation_
 * number (if any), failure_reason (if any). The active job (if any)
 * is rendered separately by ManualRenewalPanel via FilingStatusCard
 * with full audit-log timeline; this component is for the historical
 * audit trail.
 *
 * Props:
 *   filingJobs — array of FilingJob docs from the parent's fetch.
 *                Newest-first (matches the GET endpoint's order).
 *                Pass [] for "no history yet"; the section auto-hides
 *                rather than rendering an empty card.
 */

import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
} from 'react-native';
import { ChevronDown, ChevronUp, History } from 'lucide-react-native';
import { spacing, borderRadius, typography } from '../../styles/theme';
import { useTheme } from '../../context/ThemeContext';

// Status palette mirrors FilingStatusCard's STATUS_BADGE — same color
// per status so the operator's eye correlates between active panel
// and history rows. Compact form, label-only (no icon) since the row
// surface is dense.
const STATUS_PALETTE = {
  queued:      { label: 'Queued',           color: '#6b7280' },
  claimed:     { label: 'Claimed',          color: '#3b82f6' },
  in_progress: { label: 'In Progress',      color: '#f59e0b' },
  filed:       { label: 'Filed',            color: '#10b981' },
  completed:   { label: 'Completed',        color: '#10b981' },
  failed:      { label: 'Failed',           color: '#ef4444' },
  cancelled:   { label: 'Cancelled',        color: '#6b7280' },
};

const formatTime = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
};

const FilingHistorySection = ({ filingJobs = [] }) => {
  const { colors } = useTheme();
  const s = buildStyles(colors);
  const [expanded, setExpanded] = useState(false);

  // Hide entirely when there are no jobs — operator's eye doesn't
  // need an empty card on a permit that's never been filed.
  if (!filingJobs.length) return null;

  const ChevronIcon = expanded ? ChevronUp : ChevronDown;

  return (
    <View style={s.container}>
      <Pressable
        style={s.headerRow}
        onPress={() => setExpanded((v) => !v)}
      >
        <View style={s.headerLeft}>
          <History size={14} color={colors.text.muted} />
          <Text style={s.headerLabel}>
            Filing History ({filingJobs.length})
          </Text>
        </View>
        <ChevronIcon size={16} color={colors.text.muted} />
      </Pressable>

      {expanded && (
        <View style={s.list}>
          {filingJobs.map((job) => {
            const palette = STATUS_PALETTE[job.status] || STATUS_PALETTE.queued;
            const jobId = job.id || job._id;
            return (
              <View key={jobId} style={s.row}>
                <View style={s.rowHeader}>
                  <View
                    style={[
                      s.statusPill,
                      { backgroundColor: `${palette.color}20`, borderColor: palette.color },
                    ]}
                  >
                    <Text style={[s.statusPillText, { color: palette.color }]}>
                      {palette.label}
                    </Text>
                  </View>
                  <Text style={s.rowDate}>{formatTime(job.created_at)}</Text>
                </View>

                <View style={s.rowDetails}>
                  {job.completed_at && (
                    <View style={s.rowDetailLine}>
                      <Text style={s.detailLabel}>Completed</Text>
                      <Text style={s.detailValue}>{formatTime(job.completed_at)}</Text>
                    </View>
                  )}
                  {job.dob_confirmation_number && (
                    <View style={s.rowDetailLine}>
                      <Text style={s.detailLabel}>DOB Confirmation</Text>
                      <Text style={s.detailValue}>{job.dob_confirmation_number}</Text>
                    </View>
                  )}
                  {job.failure_reason && (
                    <View style={s.rowDetailLine}>
                      <Text style={s.detailLabel}>Failure</Text>
                      <Text style={[s.detailValue, s.detailValueError]}>
                        {job.failure_reason}
                      </Text>
                    </View>
                  )}
                  {typeof job.retry_count === 'number' && job.retry_count > 0 && (
                    <View style={s.rowDetailLine}>
                      <Text style={s.detailLabel}>Retries</Text>
                      <Text style={s.detailValue}>{job.retry_count}</Text>
                    </View>
                  )}
                </View>
              </View>
            );
          })}
        </View>
      )}
    </View>
  );
};

function buildStyles(colors) {
  return StyleSheet.create({
    container: {
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      marginTop: spacing.sm,
    },
    headerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingVertical: spacing.sm,
      paddingHorizontal: spacing.md,
    },
    headerLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
    },
    headerLabel: {
      fontFamily: typography.semibold,
      fontSize: 13,
      color: colors.text.secondary,
    },
    list: {
      paddingHorizontal: spacing.md,
      paddingBottom: spacing.md,
      gap: spacing.sm,
    },
    row: {
      paddingVertical: spacing.sm,
      paddingHorizontal: spacing.sm,
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: colors.glass.background,
      gap: 4,
    },
    rowHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    statusPill: {
      paddingHorizontal: 8,
      paddingVertical: 2,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
    },
    statusPillText: {
      fontFamily: typography.semibold,
      fontSize: 11,
      letterSpacing: 0.3,
    },
    rowDate: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
    },
    rowDetails: {
      gap: 2,
      paddingTop: 4,
    },
    rowDetailLine: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      gap: spacing.sm,
    },
    detailLabel: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
    },
    detailValue: {
      flex: 1,
      textAlign: 'right',
      fontFamily: typography.medium,
      fontSize: 12,
      color: colors.text.primary,
    },
    detailValueError: {
      color: '#ef4444',
    },
  });
}

export default FilingHistorySection;
