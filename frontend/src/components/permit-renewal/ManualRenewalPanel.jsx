/**
 * ManualRenewalPanel
 * ══════════════════
 * Renders the structured manual-renewal information panel for permits
 * the v2 dispatcher emits with action.kind === "manual_renewal_dob_now"
 * (the MANUAL_1YR_CEILING strategy in backend/lib/eligibility_v2.py).
 *
 * Originally introduced inline in
 * frontend/app/project/[id]/permit-renewal.jsx as part of MR.1
 * (commit 967294c). Extracted to its own component file in MR.1.5 to
 * enable the actionRenderers-map dispatch pattern. Each future
 * action-kind panel (ShedRenewalPanel, AwaitingExtensionPanel, etc.)
 * will live alongside this one in
 * frontend/src/components/permit-renewal/.
 *
 * Visual output is byte-identical to MR.1's inline version. Styles
 * and copy moved verbatim. The TODO(data plumbing) note in MR.1
 * about renewal.issuance_date being absent from the persisted record
 * is now tracked as MR.1.6 in §14 of permit-renewal-v3.md.
 */

import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { spacing, borderRadius, typography } from '../../styles/theme';
import { useTheme } from '../../context/ThemeContext';
import { MANUAL_RENEWAL_RULE_CITATION } from '../../constants/dobRules';

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

const ManualRenewalPanel = ({ renewal }) => {
  const { colors } = useTheme();
  const s = buildStyles(colors);

  return (
    <View style={s.manualRenewalPanel}>
      <Text style={s.manualRenewalHeader}>
        Manual Renewal Required
      </Text>
      <Text style={s.manualRenewalExplanation}>
        This permit has reached the one-year mark from
        original issuance. NYC DOB requires work permits
        older than one year to be renewed manually,
        regardless of insurance status. Filing happens at
        DOB NOW with the licensee's NYC.ID.
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

      <Pressable
        disabled
        style={[s.manualRenewalCta, s.manualRenewalCtaDisabled]}
      >
        <Text style={s.manualRenewalCtaText}>Prepare Filing</Text>
      </Pressable>
      <Text style={s.manualRenewalCtaCaption}>
        Filing workflow coming soon — MR.2 through MR.6
      </Text>

      <Text style={s.manualRenewalCitation}>
        Reference: {MANUAL_RENEWAL_RULE_CITATION}
      </Text>
    </View>
  );
};

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
    manualRenewalCta: {
      paddingVertical: spacing.sm + 2,
      paddingHorizontal: spacing.md,
      borderRadius: borderRadius.md,
      alignItems: 'center',
      marginTop: spacing.xs,
    },
    manualRenewalCtaDisabled: {
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
      opacity: 0.6,
    },
    manualRenewalCtaText: {
      fontFamily: typography.semibold,
      fontSize: 14,
      color: colors.text.muted,
      letterSpacing: 0.3,
    },
    manualRenewalCtaCaption: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      textAlign: 'center',
      marginTop: 6,
      marginBottom: spacing.sm,
    },
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
