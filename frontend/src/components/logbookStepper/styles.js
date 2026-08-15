import { StyleSheet } from 'react-native';
import {
  spacing, borderRadius, typography, touchTarget, outdoor, outdoorShadow,
} from '../../styles/theme';
// o50 is the app's existing disabled/busy dim (tokens.js:265), not a new value.
import { opacity } from '../../styles/tokens';

/**
 * The stepper's CHROME styles — every value a logbook form needs to look like
 * the approved Daily Jobsite Log, and nothing specific to that form.
 *
 * LIFTED VERBATIM from app/logbooks/daily_jobsite.jsx, which is the only
 * implementation an operator has device-tested and approved. Nothing here was
 * redesigned during the extraction: the numbers are the numbers that shipped.
 *
 * Not theme-dependent, so it is built once — the outdoor palette deliberately
 * does not flip (see theme.js). Every value comes from the token file; a raw
 * hex, rgba() or numeric fontSize fails src/styles/tokens.test.cjs.
 *
 * A form adds its OWN keys by spreading this into its own StyleSheet, so the
 * shared names cannot drift apart across ten screens while the form-specific
 * ones stay where they are used.
 */
export function buildStepperStyles() {
  return StyleSheet.create({
    container: { flex: 1 },
    loadingCenter: { flex: 1, alignItems: 'center', justifyContent: 'center' },

    header: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.md,
      paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    },
    // GlassButton's icon variant is a 44x44 circular pill. Same look here, but
    // the 56pt floor wins over the visual size: the constraint is a gloved
    // thumb outdoors, not the component.
    headerBack: {
      minWidth: touchTarget.min, minHeight: touchTarget.min,
      alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.full,
      backgroundColor: outdoor.surface,
      borderWidth: 1, borderColor: outdoor.line,
    },
    headerText: { flex: 1 },
    headerTitle: {
      fontSize: typography.sizes.lg, fontWeight: '700', color: outdoor.text,
    },
    headerSub: { fontSize: typography.sizes.fine, color: outdoor.textDim },

    progressRow: {
      flexDirection: 'row', gap: spacing.xs, paddingHorizontal: spacing.md,
      paddingBottom: spacing.sm,
    },
    progressPip: {
      flex: 1, height: spacing.xs, borderRadius: borderRadius.sm,
      backgroundColor: outdoor.line,
    },
    progressPipOn: { backgroundColor: outdoor.surfaceSelected },
    // Reached, left, and still incomplete. Last in the style array so it
    // wins over progressPipOn — an incomplete step he has walked past is
    // the more important of the two things the pip can say.
    progressPipWarn: { backgroundColor: outdoor.warn },
    // ── COMPACT STEP 1 ────────────────────────────────────────────────
    // 40pt: two 13pt lines plus 4pt padding. NOT a touch target, because the
    // row is not tappable — see the note above renderStep1. Anything that
    // makes it interactive goes back to touchTarget.min and the fit
    // arithmetic has to be redone.
    scroll: { flex: 1 },
    scrollContent: { padding: spacing.md, paddingBottom: spacing.xxl },

    stepHeader: { marginBottom: spacing.md },
    stepCount: {
      fontSize: typography.sizes.fine, fontWeight: '600', color: outdoor.textDim,
      letterSpacing: spacing.xs / 4, textTransform: 'uppercase',
    },
    stepTitle: {
      fontSize: typography.sizes.xl, fontWeight: '700', color: outdoor.text,
    },

    // Shadow on the outer view, gradient on the inner - see Card.
    cardShadow: {
      borderRadius: borderRadius.xxl,
      marginBottom: spacing.md,
      backgroundColor: outdoor.cardTop,
      ...outdoorShadow,
    },
    cardFill: {
      borderRadius: borderRadius.xxl,
      borderWidth: 1,
      borderColor: outdoor.line,
      padding: spacing.xl,
      gap: spacing.sm,
      overflow: 'hidden',
    },
    cardWarn: { backgroundColor: outdoor.warnBg },
    warnBody: { flex: 1, gap: spacing.xs },
    warnTitle: {
      fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.text,
    },
    warnText: { fontSize: typography.sizes.sm, color: outdoor.textSoft },

    question: {
      fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.text,
      marginTop: spacing.sm,
    },
    noteText: { fontSize: typography.sizes.dense, color: outdoor.textDim },
    emptyText: {
      fontSize: typography.sizes.md, color: outdoor.textSoft, paddingVertical: spacing.md,
    },
    errorText: {
      fontSize: typography.sizes.dense, fontWeight: '600', color: outdoor.danger,
    },
    lockedHint: {
      fontSize: typography.sizes.sm, color: outdoor.textSoft,
      backgroundColor: outdoor.surfaceSunk, borderRadius: borderRadius.lg,
      padding: spacing.md,
    },

    chipWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
    // Says what the chips above are ranked BY. Advisory, not a warning —
    // a trade list is a perfectly good suggestion, it is just not a
    // sequenced one, and the card must not imply otherwise.
    chipBasisNote: {
      fontSize: typography.sizes.fine, color: outdoor.textDim,
      marginBottom: spacing.xs,
    },
    chip: {
      minHeight: touchTarget.min, justifyContent: 'center',
      paddingHorizontal: spacing.lg, paddingVertical: spacing.sm,
      borderRadius: borderRadius.full, borderWidth: 1,
      borderColor: outdoor.lineStrong, backgroundColor: outdoor.surface,
    },
    chipSelected: {
      backgroundColor: outdoor.surfaceSelected, borderColor: outdoor.surfaceSelected,
    },
    chipText: {
      fontSize: typography.sizes.md, fontWeight: '600', color: outdoor.text,
    },
    chipTextSelected: { color: outdoor.textOnSelected },

    input: {
      minHeight: touchTarget.min, borderRadius: borderRadius.lg, borderWidth: 1,
      borderColor: outdoor.lineStrong, backgroundColor: outdoor.surface,
      paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
      fontSize: typography.sizes.md, color: outdoor.text,
    },

    toggleRow: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
      minHeight: touchTarget.min, paddingHorizontal: spacing.md,
      borderRadius: borderRadius.full, borderWidth: 1,
      borderColor: outdoor.lineStrong,
    },
    toggleRowOn: { borderColor: outdoor.okBorder, backgroundColor: outdoor.okBg },
    toggleBox: {
      width: spacing.lg, height: spacing.lg, borderRadius: borderRadius.sm,
      borderWidth: 2, borderColor: outdoor.lineStrong,
    },
    toggleText: { fontSize: typography.sizes.md, color: outdoor.text, flex: 1 },

    readOnlyValue: {
      backgroundColor: outdoor.surfaceSunk, borderRadius: borderRadius.lg,
      padding: spacing.md, gap: spacing.xs,
    },
    readOnlyText: {
      fontSize: typography.sizes.lg, fontWeight: '600', color: outdoor.text,
    },
    reviewLabel: {
      fontSize: typography.sizes.fine, fontWeight: '600', color: outdoor.textDim,
      textTransform: 'uppercase',
    },
    reviewValue: { fontSize: typography.sizes.md, color: outdoor.text },

    secondaryBtn: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
      gap: spacing.sm, minHeight: touchTarget.min,
      paddingHorizontal: spacing.lg, borderRadius: borderRadius.full,
      borderWidth: 1, borderColor: outdoor.lineStrong,
      backgroundColor: outdoor.surface,
    },
    secondaryBtnText: {
      fontSize: typography.sizes.md, fontWeight: '600', color: outdoor.text,
    },

    footer: { padding: spacing.md },
    primaryBtn: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
      gap: spacing.sm, minHeight: touchTarget.primary,
      borderRadius: borderRadius.full, backgroundColor: outdoor.surfaceSelected,
      paddingHorizontal: spacing.xl,
      ...outdoorShadow,
    },
    primaryBtnText: {
      fontSize: typography.sizes.xl, fontWeight: '700', color: outdoor.textOnSelected,
    },
    // Unreachable, and it LOOKS unreachable. Dimmed rather than hidden: a
    // button that vanishes reads as a broken screen, and the CP needs to see
    // the action he is one signature away from.
    primaryBtnDisabled: { opacity: opacity.o50 },

    // The required-field marking, matching preshift_signin's ynItemRequired /
    // requiredText so one app does not mark a missing answer two ways.
    inputRequired: { borderColor: outdoor.danger, borderWidth: 2 },
    requiredText: {
      fontSize: typography.sizes.fine, color: outdoor.danger,
      fontWeight: '600', marginTop: spacing.xs,
    },

    submitHint: {
      fontSize: typography.sizes.fine, color: outdoor.attention,
      textAlign: 'center', paddingBottom: spacing.sm,
    },

    autosaveNote: {
      fontSize: typography.sizes.fine, color: outdoor.textDim,
      textAlign: 'center', paddingVertical: spacing.sm,
    },

    modalOverlay: {
      flex: 1, alignItems: 'center', justifyContent: 'center',
      backgroundColor: outdoor.scrim, padding: spacing.md,
    },
    modalCard: {
      width: '100%', backgroundColor: outdoor.cardTop,
      borderRadius: borderRadius.xxl,
      padding: spacing.xl, gap: spacing.sm, ...outdoorShadow,
    },
    modalTitle: {
      fontSize: typography.sizes.lg, fontWeight: '700', color: outdoor.text,
    },
    modalActions: { flexDirection: 'row', gap: spacing.sm },

    // ── Labelled field block — a label above its control ──────────────────
    // Used by DateField and by both ported forms' text rows. The label is
    // ABOVE rather than beside: a right-aligned value next to a left-aligned
    // label is unreadable at arm's length once either one wraps.
    fieldBlock: { gap: spacing.xs, marginBottom: spacing.sm },
    fieldValueText: { fontSize: typography.sizes.md, color: outdoor.text },
    fieldPlaceholderText: { fontSize: typography.sizes.md, color: outdoor.textDim },

    // ── DateField's calendar ──────────────────────────────────────────────
    calHead: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      gap: spacing.sm,
    },
    calMonth: {
      flex: 1, textAlign: 'center',
      fontSize: typography.sizes.lg, fontWeight: '700', color: outdoor.text,
    },
    calRow: { flexDirection: 'row' },
    calDayLabel: {
      flex: 1, textAlign: 'center',
      fontSize: typography.sizes.fine, fontWeight: '600', color: outdoor.textDim,
    },
    // Capped so a 6-row month cannot push the Clear/Done actions off a short
    // screen — the calendar scrolls, the actions stay reachable.
    calScroll: { maxHeight: spacing.xxl * 5 },
    calGrid: { flexDirection: 'row', flexWrap: 'wrap' },
    // 1/7th of the row. Percentage rather than a measured width so it holds on
    // every screen size without a second set of numbers.
    calCell: { width: '14.28%', aspectRatio: 1, padding: spacing.xs / 2 },
    calCellDay: { alignItems: 'center', justifyContent: 'center' },
    calCellSelected: {
      backgroundColor: outdoor.surfaceSelected, borderRadius: borderRadius.full,
    },
    calCellText: { fontSize: typography.sizes.md, color: outdoor.text },
    calCellTextSelected: { color: outdoor.textOnSelected, fontWeight: '700' },

  });
}
