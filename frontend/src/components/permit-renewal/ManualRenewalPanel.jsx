/**
 * ManualRenewalPanel
 * ══════════════════
 * Manual-renewal information + Start Renewal flow for v2-dispatcher
 * permits whose action.kind is "manual_renewal_dob_now".
 *
 * History:
 *   MR.1   — introduced inline; pure information layer.
 *   MR.1.5 — extracted to its own component file.
 *   MR.1.6 — issuance_date plumbing.
 *   MR.7   — replaced "Prepare Filing" placeholder with a live
 *            "File Renewal" button + FilingStatusCard polling.
 *   MR.14 4a — worker container removed.
 *   MR.14 4b — credentials field removed.
 *   MR.14 4c — this commit. Replaced "File Renewal" with the
 *            "Start Renewal" affordance: clicking opens DOB NOW
 *            in a new tab AND surfaces a slide-out panel with the
 *            pre-filled PW2 values for the operator to copy in
 *            manually. LeveLog never files; the user files manually.
 *            Detection of completion is delegated to MR.8's
 *            dob_approval_watcher (NYC Open Data poll).
 *
 * Props:
 *   renewal       — the permit_renewal doc. Carries
 *                   manual_renewal_started_at when the operator has
 *                   already clicked Start Renewal (MR.14 4c new
 *                   field), and new_expiration_date / status when
 *                   MR.8's watcher has detected the renewed permit.
 *   onRenewalChange — optional callback invoked after a successful
 *                   POST /start-renewal-clicked so the parent can
 *                   refetch the renewal list and surface the new
 *                   state on the next render.
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Linking,
  Platform,
} from 'react-native';
import { spacing, borderRadius, typography } from '../../styles/theme';
import { useTheme } from '../../context/ThemeContext';
import { MANUAL_RENEWAL_RULE_CITATION } from '../../constants/dobRules';
import apiClient from '../../utils/api';
import FilingStatusCard from './FilingStatusCard';
import StartRenewalPanel from './StartRenewalPanel';

// Local formatDate — matches the helper in
// frontend/app/project/[id]/permit-renewal.jsx line ~132. Inlined
// here rather than promoted to a shared util to keep the cross-file
// surface minimal.
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

// Open the DOB NOW landing page in a new browser tab (web) or via
// Linking (native). The constant is exported by StartRenewalPanel so
// both UX surfaces stay in lockstep.
const openDobNow = () => {
  const url = StartRenewalPanel.DOB_NOW_URL;
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    window.open(url, '_blank', 'noopener,noreferrer');
    return;
  }
  Linking.openURL(url).catch((e) => {
    console.warn('[ManualRenewalPanel] could not open DOB NOW:', e?.message);
  });
};

const ManualRenewalPanel = ({ renewal, onRenewalChange }) => {
  const { colors } = useTheme();
  const s = buildStyles(colors);

  const renewalId = renewal.id || renewal._id;

  // Has the operator already clicked Start Renewal? Sourced from the
  // renewal doc — MR.14 4c stamps manual_renewal_started_at on the
  // /start-renewal-clicked endpoint.
  const alreadyStarted = Boolean(renewal.manual_renewal_started_at);

  const [readiness, setReadiness] = useState(null);
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState(null);

  // Slide-out panel state: visible flag + the most recently fetched
  // field map. The map comes back inline from the start-renewal-clicked
  // response so we don't need a second round-trip in the happy path;
  // for "View values again" in the in-progress state we fall back to
  // the MR.4 GET /pw2-field-map endpoint.
  const [panelVisible, setPanelVisible] = useState(false);
  const [fieldMap, setFieldMap] = useState(null);

  // Pre-fetch readiness only when the idle button could render (no
  // started-at yet AND not in renewed state). Skip when alreadyStarted
  // because the readiness check is for the click; a re-render of the
  // in-progress branch doesn't need it.
  useEffect(() => {
    if (alreadyStarted) return undefined;
    if (renewal?.status === 'completed') return undefined;
    let cancelled = false;
    setReadinessLoading(true);
    apiClient
      .get(`/api/permit-renewals/${renewalId}/filing-readiness`)
      .then((resp) => {
        if (!cancelled) setReadiness(resp.data);
      })
      .catch((e) => {
        if (!cancelled) {
          console.warn(
            '[ManualRenewalPanel] readiness fetch failed:',
            e?.message
          );
          setReadiness({
            ready: false,
            blockers: ['Could not check readiness'],
          });
        }
      })
      .finally(() => {
        if (!cancelled) setReadinessLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [alreadyStarted, renewal?.status, renewalId]);

  const handleStartRenewal = useCallback(async () => {
    setStarting(true);
    setStartError(null);
    try {
      const resp = await apiClient.post(
        `/api/permit-renewals/${renewalId}/start-renewal-clicked`
      );
      // Open DOB NOW first — operator's eye lands on the new tab,
      // then they switch back to LeveLog and the panel is already
      // populated with values to copy.
      openDobNow();
      setFieldMap(resp.data?.field_map || null);
      setPanelVisible(true);
      if (typeof onRenewalChange === 'function') {
        onRenewalChange();
      }
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (typeof detail === 'object' && detail !== null) {
        setStartError({
          message: detail.message || 'Could not start renewal.',
          code: detail.code,
          blockers: detail.blockers,
        });
      } else {
        setStartError({
          message:
            typeof detail === 'string'
              ? detail
              : e?.message || 'Could not start renewal.',
        });
      }
    } finally {
      setStarting(false);
    }
  }, [renewalId, onRenewalChange]);

  // "View values again" — operator already clicked, panel was closed,
  // they want to see the values without re-recording the click.
  const handleViewValuesAgain = useCallback(async () => {
    setStartError(null);
    if (fieldMap) {
      // We have a cached map from the original click. Just re-open.
      setPanelVisible(true);
      return;
    }
    try {
      const resp = await apiClient.get(
        `/api/permit-renewals/${renewalId}/pw2-field-map`
      );
      setFieldMap(resp.data || null);
      setPanelVisible(true);
    } catch (e) {
      console.warn(
        '[ManualRenewalPanel] re-fetch field map failed:',
        e?.message
      );
      setStartError({
        message: 'Could not load renewal values. Try refreshing.',
      });
    }
  }, [fieldMap, renewalId]);

  return (
    <View style={s.manualRenewalPanel}>
      <Text style={s.manualRenewalHeader}>Manual Renewal Required</Text>
      <Text style={s.manualRenewalExplanation}>
        {renewal.issuance_date
          ? `This permit was issued on ${formatDate(renewal.issuance_date)}. NYC DOB requires work permits older than one year to be renewed manually, regardless of insurance status. You file at DOB NOW with the licensee's NYC.ID; LeveLog tracks the click and detects completion via the NYC Open Data feed.`
          : `This permit has reached the one-year mark from original issuance. NYC DOB requires work permits older than one year to be renewed manually, regardless of insurance status. You file at DOB NOW with the licensee's NYC.ID; LeveLog tracks the click and detects completion via the NYC Open Data feed.`}
      </Text>

      <View style={s.manualRenewalFeeBlock}>
        <Text style={s.manualRenewalFee}>$130</Text>
        <Text style={s.manualRenewalFeeCaption}>
          paid directly to NYC DOB
        </Text>
      </View>

      <View style={s.manualRenewalDetails}>
        <DetailRow s={s} label="Job Filing Number" value={renewal.job_number || '—'} />
        <DetailRow s={s} label="Work Type" value={renewal.permit_type || '—'} />
        <DetailRow
          s={s}
          label="Current Expiration"
          value={formatDate(renewal.current_expiration)}
        />
        <DetailRow
          s={s}
          label="Days Until Expiration"
          value={
            typeof renewal.days_until_expiry === 'number'
              ? `${renewal.days_until_expiry}d`
              : '—'
          }
        />
      </View>

      <FilingStatusCard
        renewal={renewal}
        readiness={readiness}
        readinessLoading={readinessLoading}
        onStartRenewal={handleStartRenewal}
        onViewValuesAgain={handleViewValuesAgain}
        starting={starting}
        error={startError}
      />

      <StartRenewalPanel
        visible={panelVisible}
        fieldMap={fieldMap}
        onClose={() => setPanelVisible(false)}
        onReopenDob={openDobNow}
      />

      <Text style={s.manualRenewalCitation}>
        Reference: {MANUAL_RENEWAL_RULE_CITATION}
      </Text>
    </View>
  );
};

const DetailRow = ({ s, label, value }) => (
  <View style={s.manualRenewalDetailRow}>
    <Text style={s.manualRenewalDetailLabel}>{label}</Text>
    <Text style={s.manualRenewalDetailValue}>{value}</Text>
  </View>
);

export default ManualRenewalPanel;

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
