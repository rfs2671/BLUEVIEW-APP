import React from 'react';
import {
  View, Text, Modal, Pressable, ScrollView, ActivityIndicator, StyleSheet,
} from 'react-native';
import { X, ShieldCheck, AlertTriangle, RefreshCw } from 'lucide-react-native';
import {
  spacing, borderRadius, typography, touchTarget, outdoor, outdoorShadow,
} from '../styles/theme';
import { opacity } from '../styles/tokens';
import { useT } from '../i18n';
import {
  READY, NOT_AGREED, STALE, UNKNOWN, consentCopyKey,
} from '../utils/esraConsentState';

/**
 * THE AGREEMENT TO SIGN ELECTRONICALLY, ASKED AT THE MOMENT OF SIGNING.
 *
 * ── IT APPEARS IN PLACE, AND THAT IS THE POINT ──────────────────────────────
 *
 * The alternative was a route: send him to a consent page, then back. That is
 * the shape CpNav rejected for the check-in QR and for the same reason — a
 * control reached mid-task must not take a man off what he was doing and make
 * him find his way back. Here it is stronger than a convenience argument: he
 * has just filled five steps of a statutory log, and navigating away from an
 * unsaved form to answer a legal question is how work gets lost.
 *
 * SO IT IS NEVER A DEAD END. Whatever state he is in, this says what is
 * missing and offers the way through it, on the screen he is already on:
 *
 *   NOT_AGREED   the wording, and an Agree button
 *   STALE        the same, and it says the words CHANGED — because telling a
 *                man who agreed last year that he never agreed is false
 *   UNKNOWN      names the outage and offers Retry. It does NOT offer Agree:
 *                recording an agreement we cannot first read back is how a
 *                duplicate or a contradiction gets written.
 *
 * ── THE TEXT IS THE SERVER'S, VERBATIM ──────────────────────────────────────
 *
 * `text` is rendered exactly as `GET /api/esra-consent` returned it. Nothing
 * here paraphrases, truncates or reformats it beyond paragraph breaks, and
 * there is no fallback copy: if the server did not send wording, this shows
 * the UNKNOWN state rather than words of its own. lib/esra_consent.py is
 * explicit that a consent whose text the client chooses is evidence of
 * nothing, and a client that invents wording when the real wording is missing
 * is exactly that.
 *
 * ── DISMISSABLE, DELIBERATELY ───────────────────────────────────────────────
 *
 * Closing leaves him on the editor with his entry intact and unsigned. A
 * consent that cannot be declined is not freely given — the wording itself
 * promises he can withdraw — so a modal he cannot escape would contradict the
 * text it is showing.
 */
export default function EsraConsentModal({
  visible, state, text, busy, error, onAgree, onRetry, onClose,
}) {
  const t = useT('esraConsent');
  const key = consentCopyKey(state);
  const isUnknown = state === UNKNOWN;
  // The wording is required to ask for agreement. Without it there is nothing
  // to agree TO, so this degrades to the outage state rather than showing a
  // button over an empty box.
  const haveText = typeof text === 'string' && text.trim().length > 0;
  const askable = !isUnknown && haveText;

  return (
    <Modal
      visible={!!visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <View style={s.overlay}>
        <Pressable
          style={s.backdrop}
          onPress={onClose}
          accessibilityRole="button"
          accessibilityLabel={t('close')}
        />
        <View style={s.sheet}>
          <View style={s.header}>
            {askable
              ? <ShieldCheck size={22} strokeWidth={1.75} color={outdoor.text} />
              : <AlertTriangle size={22} strokeWidth={1.75} color={outdoor.text} />}
            <Text style={s.title} numberOfLines={2}>{t(key)}</Text>
            <Pressable
              onPress={onClose}
              style={s.headerBtn}
              accessibilityRole="button"
              accessibilityLabel={t('close')}
            >
              <X size={24} color={outdoor.text} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={s.body}>
            <Text style={s.lede}>{t(`${key}Body`)}</Text>

            {askable ? (
              <View style={s.textWell}>
                {/* Split on blank lines only. The server sends four
                    paragraphs; rendering them as one block is how a wall of
                    text gets skipped by the person it is written for. */}
                {String(text).split(/\n\s*\n/).map((para, i) => (
                  // eslint-disable-next-line react/no-array-index-key
                  <Text key={i} style={[s.para, i > 0 && s.paraGap]}>
                    {para.trim()}
                  </Text>
                ))}
              </View>
            ) : null}

            {error ? <Text style={s.error}>{error}</Text> : null}
          </ScrollView>

          <View style={s.footer}>
            {askable ? (
              <Pressable
                onPress={onAgree}
                disabled={busy}
                style={[s.primary, busy && s.busy]}
                accessibilityRole="button"
              >
                {busy
                  ? <ActivityIndicator color={outdoor.textOnSelected} />
                  : <Text style={s.primaryText}>{t('agree')}</Text>}
              </Pressable>
            ) : (
              <Pressable
                onPress={onRetry}
                disabled={busy}
                style={[s.primary, busy && s.busy]}
                accessibilityRole="button"
              >
                {busy
                  ? <ActivityIndicator color={outdoor.textOnSelected} />
                  : (
                    <>
                      <RefreshCw size={18} strokeWidth={2} color={outdoor.textOnSelected} />
                      <Text style={s.primaryText}>{t('retry')}</Text>
                    </>
                  )}
              </Pressable>
            )}
            {/* NOT "Cancel". He is not cancelling the log — it stays exactly
                as he left it, unsigned. The label says what actually happens. */}
            <Pressable onPress={onClose} style={s.secondary} accessibilityRole="button">
              <Text style={s.secondaryText}>{t('notNow')}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

// PINNED, like every other surface a CP meets outdoors. This appears ON TOP of
// the logbook stepper, whose canvas AnimatedBackground pins light regardless of
// theme — a live-themed sheet would be a dark card on a light page in dark
// mode, which is the defect outdoorCanvasPin.test.cjs exists to prevent.
const s = StyleSheet.create({
  overlay: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(10, 25, 41, 0.45)' },
  sheet: {
    backgroundColor: outdoor.cardTop,
    borderTopLeftRadius: borderRadius.lg,
    borderTopRightRadius: borderRadius.lg,
    maxHeight: '88%',
    ...outdoorShadow,
  },
  header: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.md,
    borderBottomWidth: 1, borderBottomColor: outdoor.line,
  },
  headerBtn: {
    minWidth: touchTarget.min, minHeight: touchTarget.min,
    alignItems: 'center', justifyContent: 'center',
  },
  title: {
    flex: 1, color: outdoor.text,
    fontSize: typography.sizes.lg, fontWeight: '700',
  },
  body: { padding: spacing.md },
  lede: {
    color: outdoor.textSoft, fontSize: typography.sizes.dense,
    lineHeight: 20, marginBottom: spacing.md,
  },
  textWell: {
    backgroundColor: outdoor.surfaceSunk,
    borderRadius: borderRadius.md,
    borderWidth: 1, borderColor: outdoor.line,
    padding: spacing.md,
  },
  para: { color: outdoor.text, fontSize: typography.sizes.dense, lineHeight: 21 },
  paraGap: { marginTop: spacing.sm },
  error: {
    marginTop: spacing.md, color: outdoor.text,
    fontSize: typography.sizes.fine, lineHeight: 18,
  },
  footer: {
    padding: spacing.md, gap: spacing.sm,
    borderTopWidth: 1, borderTopColor: outdoor.line,
  },
  primary: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: spacing.sm,
    minHeight: touchTarget.primary,
    borderRadius: borderRadius.md,
    backgroundColor: outdoor.surfaceSelected,
  },
  busy: { opacity: opacity.o50 },
  primaryText: {
    color: outdoor.textOnSelected,
    fontSize: typography.sizes.lg, fontWeight: '700',
  },
  secondary: {
    minHeight: touchTarget.min,
    alignItems: 'center', justifyContent: 'center',
  },
  secondaryText: { color: outdoor.textDim, fontSize: typography.sizes.dense },
});
