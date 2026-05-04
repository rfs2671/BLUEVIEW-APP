/**
 * StartRenewalPanel
 * ═════════════════
 * MR.14 commit 4c. Manual-renewal helper panel.
 *
 * The user clicks "Start Renewal" → DOB NOW opens in a new tab AND
 * this panel slides in showing the pre-filled PW2 values for them to
 * copy into the form. LeveLog never files; the user files manually.
 *
 * Renders the MR.4 PW2 mapper output (see backend/lib/pw2_field_mapper.py)
 * grouped into operator-friendly sections, with a click-to-copy
 * affordance on each value. Plain markdown-style bullet lists for
 * attachments + notes — those aren't copy targets, they're checklists.
 *
 * Props:
 *   visible      — bool. When false the panel is collapsed (caller
 *                  controls visibility from a sibling state hook).
 *   fieldMap     — POST /api/permit-renewals/{id}/start-renewal-clicked
 *                  response.field_map. Shape mirrors Pw2FieldMap.model_dump
 *                  + critical_unmappable_fields + non_critical_unmappable_fields.
 *   onClose      — callback to dismiss the panel.
 *   onReopenDob  — callback when the operator clicks "Reopen DOB NOW".
 *                  Lets the parent re-trigger the new-tab open without
 *                  re-running the audit log click.
 */

import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  Platform,
} from 'react-native';
import {
  X,
  Copy,
  Check,
  ExternalLink,
  Info,
  AlertCircle,
} from 'lucide-react-native';
import { spacing, borderRadius, typography } from '../../styles/theme';
import { useTheme } from '../../context/ThemeContext';

// ── Field → section assignment ────────────────────────────────────
//
// MR.4's mapper emits a flat dict of field_name → FieldValue. Operator
// brains group fields by where they live on the PW2 form: who is
// filing, what permit, where the project is, what dates apply, what
// renewal type. This maps the flat names back into those mental
// buckets so the operator's eye doesn't have to scan a 12-row table
// looking for "applicant_email" amongst "permit_subtype".
//
// Order of sections is the order they render top-to-bottom; order
// of fields within a section follows the array below.

const SECTIONS = [
  {
    title: 'Applicant Info',
    description:
      'Filing representative + their company. DOB requires the licensed individual to file under their own NYC.ID.',
    fields: [
      'applicant_name',
      'applicant_license_class',
      'applicant_license_number',
      'applicant_email',
      'applicant_business_name',
      'gc_license_number',
    ],
  },
  {
    title: 'Job & Permit',
    description:
      'Identifies the permit being renewed. job_filing_number is the DOB job number; bin is the building identifier.',
    fields: [
      'job_filing_number',
      'work_permit_number',
      'work_type',
      'permit_subtype',
      'bin',
      'bbl',
      'project_address',
    ],
  },
  {
    title: 'Renewal Details',
    description:
      'Dates and renewal-type values DOB NOW asks for in the PW2 form fields.',
    fields: [
      'renewal_type',
      'current_expiration_date',
      'issuance_date',
      'effective_expiry',
      'renewal_fee_amount',
    ],
  },
];

// Pretty labels for the field keys. Anything not in this dict falls
// back to a sentence-cased version of the key.
const FIELD_LABELS = {
  applicant_name: 'Applicant Name',
  applicant_license_class: 'License Class',
  applicant_license_number: 'License Number',
  applicant_email: 'Applicant Email',
  applicant_business_name: 'Business Name',
  gc_license_number: 'GC License Number',
  job_filing_number: 'Job Filing Number',
  work_permit_number: 'Work Permit Number',
  work_type: 'Work Type',
  permit_subtype: 'Permit Subtype',
  bin: 'BIN',
  bbl: 'BBL',
  project_address: 'Project Address',
  renewal_type: 'Renewal Type',
  current_expiration_date: 'Current Expiration',
  issuance_date: 'Issuance Date',
  effective_expiry: 'Effective Expiry',
  renewal_fee_amount: 'Renewal Fee',
};

const prettyLabel = (key) =>
  FIELD_LABELS[key] ||
  key
    .split('_')
    .map((w) => (w.length ? w[0].toUpperCase() + w.slice(1) : ''))
    .join(' ');

// ── Clipboard helper ─────────────────────────────────────────────
//
// React Native Web → navigator.clipboard.writeText. Native (iOS /
// Android) → @react-native-clipboard/clipboard, but the project
// doesn't ship that dep yet (search confirms zero imports). Fall
// back to a no-op on native; the v1 product is web-first per the
// architecture doc and this panel is the only copy-required surface.

const copyToClipboard = async (text) => {
  if (Platform.OS === 'web') {
    if (
      typeof navigator !== 'undefined' &&
      navigator.clipboard &&
      typeof navigator.clipboard.writeText === 'function'
    ) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (_e) {
        // fall-through to legacy approach
      }
    }
    // Legacy fallback for browsers without clipboard API.
    if (typeof document !== 'undefined' && document.body) {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        return ok;
      } catch (_e) {
        return false;
      }
    }
  }
  // No clipboard on native — the operator can long-press the value
  // text and use the platform's native copy menu.
  return false;
};

// ── Single copyable row ───────────────────────────────────────────

const CopyRow = ({ label, value, styles: s, colors }) => {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(async () => {
    const ok = await copyToClipboard(String(value ?? ''));
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    }
  }, [value]);

  return (
    <View style={s.copyRow}>
      <View style={s.copyRowText}>
        <Text style={s.copyRowLabel}>{label}</Text>
        <Text style={s.copyRowValue} selectable>
          {value || '—'}
        </Text>
      </View>
      <Pressable
        onPress={handleCopy}
        style={[s.copyButton, copied && s.copyButtonCopied]}
        accessibilityLabel={`Copy ${label}`}
      >
        {copied ? (
          <>
            <Check size={12} color="#10b981" />
            <Text style={[s.copyButtonText, { color: '#10b981' }]}>Copied</Text>
          </>
        ) : (
          <>
            <Copy size={12} color={colors.text.primary} />
            <Text style={s.copyButtonText}>Copy</Text>
          </>
        )}
      </Pressable>
    </View>
  );
};

// ── Main panel ───────────────────────────────────────────────────

const DOB_NOW_URL = 'https://a810-dobnow.nyc.gov/Publish/Index.html';

const StartRenewalPanel = ({ visible, fieldMap, onClose, onReopenDob }) => {
  const { colors } = useTheme();
  const s = buildStyles(colors);

  if (!visible || !fieldMap) return null;

  // Resolve fields in the order declared in SECTIONS. Any field that
  // wasn't emitted by the mapper (legitimately missing — see
  // Pw2FieldMap.unmappable_fields) is skipped silently in the
  // section render. The unmappable list still surfaces below so the
  // operator knows what's missing.
  const fields = fieldMap.fields || {};
  const attachments = Array.isArray(fieldMap.attachments_required)
    ? fieldMap.attachments_required
    : [];
  const notes = Array.isArray(fieldMap.notes) ? fieldMap.notes : [];
  const criticalUnmappable = Array.isArray(fieldMap.critical_unmappable_fields)
    ? fieldMap.critical_unmappable_fields
    : [];
  const nonCriticalUnmappable = Array.isArray(
    fieldMap.non_critical_unmappable_fields
  )
    ? fieldMap.non_critical_unmappable_fields
    : [];

  return (
    <View style={s.panel}>
      <View style={s.header}>
        <View style={s.headerText}>
          <Text style={s.headerTitle}>Renewal Values</Text>
          <Text style={s.headerSubtitle}>
            Open DOB NOW (new tab) and copy these values into the PW2 form.
            LeveLog will detect when DOB processes the renewal.
          </Text>
        </View>
        <Pressable
          onPress={onClose}
          style={s.closeButton}
          accessibilityLabel="Close renewal values panel"
        >
          <X size={18} color={colors.text.muted} />
        </Pressable>
      </View>

      <Pressable style={s.dobButton} onPress={onReopenDob}>
        <ExternalLink size={14} color="#fff" />
        <Text style={s.dobButtonText}>Open DOB NOW (new tab)</Text>
      </Pressable>

      <ScrollView style={s.body}>
        {SECTIONS.map((section) => {
          const visibleFields = section.fields.filter(
            (key) => fields[key] && fields[key].value
          );
          if (visibleFields.length === 0) return null;
          return (
            <View key={section.title} style={s.section}>
              <Text style={s.sectionTitle}>{section.title}</Text>
              {section.description ? (
                <Text style={s.sectionDescription}>{section.description}</Text>
              ) : null}
              {visibleFields.map((key) => (
                <CopyRow
                  key={key}
                  label={prettyLabel(key)}
                  value={fields[key].value}
                  styles={s}
                  colors={colors}
                />
              ))}
            </View>
          );
        })}

        {attachments.length > 0 && (
          <View style={s.section}>
            <Text style={s.sectionTitle}>Required Attachments</Text>
            <Text style={s.sectionDescription}>
              Upload each of these in the PW2 attachments step. Insurance
              certificates must be current as of the filing date.
            </Text>
            {attachments.map((a, i) => (
              <View key={i} style={s.bulletRow}>
                <View style={s.bulletDot} />
                <Text style={s.bulletText}>{a}</Text>
              </View>
            ))}
          </View>
        )}

        {criticalUnmappable.length > 0 && (
          <View style={[s.section, s.warnSection]}>
            <View style={s.warnHeader}>
              <AlertCircle size={14} color="#ef4444" />
              <Text style={s.warnTitle}>Missing required fields</Text>
            </View>
            <Text style={s.warnDescription}>
              These required values aren't on file. Resolve them before
              filing or DOB will reject the renewal.
            </Text>
            {criticalUnmappable.map((entry, i) => (
              <Text key={i} style={s.warnItem}>• {entry}</Text>
            ))}
          </View>
        )}

        {nonCriticalUnmappable.length > 0 && (
          <View style={[s.section, s.infoSection]}>
            <View style={s.infoHeader}>
              <Info size={14} color={colors.text.muted} />
              <Text style={s.infoTitle}>Informational only</Text>
            </View>
            <Text style={s.infoDescription}>
              These fields aren't required for filing — DOB tolerates
              their absence. Listed for reference.
            </Text>
            {nonCriticalUnmappable.map((entry, i) => (
              <Text key={i} style={s.infoItem}>• {entry}</Text>
            ))}
          </View>
        )}

        {notes.length > 0 && (
          <View style={s.section}>
            <Text style={s.sectionTitle}>Notes</Text>
            {notes.map((n, i) => (
              <View key={i} style={s.bulletRow}>
                <View style={s.bulletDot} />
                <Text style={s.bulletText}>{n}</Text>
              </View>
            ))}
          </View>
        )}
      </ScrollView>
    </View>
  );
};

StartRenewalPanel.DOB_NOW_URL = DOB_NOW_URL;

export default StartRenewalPanel;

// ── Styles ───────────────────────────────────────────────────────

function buildStyles(colors) {
  return StyleSheet.create({
    panel: {
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      padding: spacing.lg,
      gap: spacing.md,
      marginTop: spacing.sm,
    },
    header: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: spacing.sm,
    },
    headerText: {
      flex: 1,
    },
    headerTitle: {
      fontFamily: typography.semibold,
      fontSize: 15,
      color: colors.text.primary,
      marginBottom: 4,
    },
    headerSubtitle: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.secondary,
      lineHeight: 18,
    },
    closeButton: {
      padding: 4,
    },
    dobButton: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 6,
      paddingVertical: spacing.sm,
      paddingHorizontal: spacing.md,
      borderRadius: borderRadius.md,
      backgroundColor: '#3b82f6',
    },
    dobButtonText: {
      fontFamily: typography.semibold,
      fontSize: 13,
      color: '#fff',
      letterSpacing: 0.3,
    },
    body: {
      maxHeight: 480,
    },
    section: {
      paddingVertical: spacing.sm,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
      gap: 4,
    },
    sectionTitle: {
      fontFamily: typography.semibold,
      fontSize: 12,
      color: colors.text.muted,
      letterSpacing: 0.5,
      textTransform: 'uppercase',
      marginBottom: 2,
    },
    sectionDescription: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.secondary,
      lineHeight: 16,
      marginBottom: spacing.xs,
    },
    copyRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: spacing.sm,
      paddingVertical: 6,
    },
    copyRowText: {
      flex: 1,
      gap: 2,
    },
    copyRowLabel: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
    },
    copyRowValue: {
      fontFamily: typography.medium,
      fontSize: 13,
      color: colors.text.primary,
    },
    copyButton: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      paddingVertical: 4,
      paddingHorizontal: 8,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: 'transparent',
    },
    copyButtonCopied: {
      borderColor: '#10b981',
      backgroundColor: '#10b98115',
    },
    copyButtonText: {
      fontFamily: typography.medium,
      fontSize: 11,
      color: colors.text.primary,
    },
    bulletRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 8,
      paddingVertical: 3,
    },
    bulletDot: {
      width: 4,
      height: 4,
      borderRadius: 2,
      backgroundColor: colors.text.muted,
      marginTop: 8,
    },
    bulletText: {
      flex: 1,
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.secondary,
      lineHeight: 18,
    },

    // ── Warning / info sub-sections ─────────────────────────────
    warnSection: {
      borderTopColor: '#ef444440',
    },
    warnHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    warnTitle: {
      fontFamily: typography.semibold,
      fontSize: 12,
      color: '#ef4444',
    },
    warnDescription: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.secondary,
      lineHeight: 16,
      marginBottom: spacing.xs,
    },
    warnItem: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: '#ef4444',
      lineHeight: 17,
      marginLeft: spacing.xs,
    },
    infoSection: {
      borderTopColor: colors.glass.border,
    },
    infoHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    infoTitle: {
      fontFamily: typography.semibold,
      fontSize: 12,
      color: colors.text.muted,
    },
    infoDescription: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      lineHeight: 16,
      marginBottom: spacing.xs,
    },
    infoItem: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      lineHeight: 17,
      marginLeft: spacing.xs,
    },
  });
}
