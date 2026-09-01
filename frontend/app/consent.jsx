/**
 * SIGNING ELECTRONICALLY — the agreement, as a screen.
 *
 * ── WHY A SCREEN AND NOT A SHEET ────────────────────────────────────────────
 *
 * This was built as a modal first, and the modal was wrong. It is a legal act:
 * it has to be readable at length, and a sheet invites the gesture that
 * dismisses it. Signing feels like something; agreeing to sign should feel
 * like the same kind of something. So it is a route, with the wording in the
 * body of the page rather than in a box on top of another page.
 *
 * ── AND THE OBJECTION THAT MADE IT A MODAL IS ANSWERED, NOT IGNORED ─────────
 *
 * He reaches this from the middle of an UNSAVED five-step log, and losing that
 * would be unforgivable. `router.push` onto the expo-router Stack does not
 * unmount the screen beneath it — app/_layout.jsx sets no `unmountOnBlur` and
 * no `detachInactiveScreens` — so the editor keeps its state and `router.back()`
 * returns him to it with every field as he left it. That is a property of the
 * navigator rather than of this file, so it is verified in the browser and
 * pinned by esraConsentGate.test.cjs rather than assumed.
 *
 * ── ONLY WHEN REQUIRED ──────────────────────────────────────────────────────
 *
 * Nothing routes here on login or onboarding. The only way in is trying to
 * sign something that needs recorded consent, which today is the BC 3301.13.13
 * superintendent log. A worker who signs nothing never sees it.
 *
 * ── HE MAY DECLINE, AND IT IS AN HONEST DEAD END ────────────────────────────
 *
 * Declining is recorded with a timestamp and the wording verbatim, and the
 * screen then says plainly what it costs: he cannot file electronically, and
 * paper remains available. It is never a silent block and never a loop — the
 * refusal is stated, and the agreement stays on the page so he can change his
 * mind. A one-tap permanent lock would be a state with no exit.
 *
 * ── THE WORDING IS THE SERVER'S ─────────────────────────────────────────────
 *
 * Rendered verbatim from GET /api/esra-consent. There is no copy of the
 * agreement in this file and no fallback text: lib/esra_consent.py is explicit
 * that a consent whose text the client chooses is evidence of nothing, and a
 * client that invents wording when the real wording is missing is exactly
 * that. No wording means the outage state, not an Agree button over a blank.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, Pressable, ScrollView, ActivityIndicator, StyleSheet,
} from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ArrowLeft, ShieldCheck, AlertTriangle, RefreshCw, FileText } from 'lucide-react-native';

import AnimatedBackground from '../src/components/AnimatedBackground';
import { esraConsentAPI } from '../src/utils/api';
import {
  consentState, consentCopyKey, versionToAgree, isAskable, consentGateCopy,
  READY, DECLINED, UNKNOWN,
} from '../src/utils/esraConsentState';
import { useT } from '../src/i18n';
import {
  spacing, borderRadius, typography, touchTarget, outdoor, outdoorShadow,
} from '../src/styles/theme';
import { opacity } from '../src/styles/tokens';

export default function ConsentScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const t = useT('esraConsent');

  const [state, setState] = useState(null);   // null = first read not back yet
  const [text, setText] = useState('');
  const [declinedAt, setDeclinedAt] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const read = useCallback(async () => {
    try {
      const payload = await esraConsentAPI.get();
      if (!alive.current) return null;
      setState(consentState(payload));
      // Only the server's wording, and only when it sent some. Keeping the
      // previous text on a failed read would show him words this response did
      // not carry — the version-pointer failure one layer up.
      setText(typeof payload?.current_text === 'string' ? payload.current_text : '');
      setDeclinedAt(payload?.declined_at || null);
      return payload;
    } catch (_e) {
      if (alive.current) { setState(UNKNOWN); setText(''); }
      return null;
    }
  }, []);

  useEffect(() => { (async () => { setBusy(true); await read(); if (alive.current) setBusy(false); })(); }, [read]);

  /** Agree, then RE-READ rather than trusting the POST's own answer. */
  const onAgree = async () => {
    setBusy(true); setError('');
    try {
      const payload = await read();
      const version = versionToAgree(payload);
      if (!version) { if (alive.current) setBusy(false); return; }
      await esraConsentAPI.agree(version);
      const after = await read();
      if (!alive.current) return;
      setBusy(false);
      // BACK TO WHAT HE WAS DOING, with his entry intact. He then taps Sign
      // himself: agreeing must not apply a signature, because a signature
      // applied from a tap on a different button is not an intent to sign.
      if (consentState(after) === READY) router.back();
    } catch (e) {
      if (alive.current) {
        setBusy(false);
        setError(e?.response?.data?.detail?.code || 'UNKNOWN');
      }
    }
  };

  /** Decline. Recorded, then STATED — he stays here and reads what it costs. */
  const onDecline = async () => {
    setBusy(true); setError('');
    try {
      const payload = await read();
      const version = versionToAgree(payload);
      if (!version) { if (alive.current) setBusy(false); return; }
      await esraConsentAPI.decline(version);
      await read();
      if (alive.current) setBusy(false);
    } catch (e) {
      if (alive.current) {
        setBusy(false);
        setError(e?.response?.data?.detail?.code || 'UNKNOWN');
      }
    }
  };

  const key = state ? consentCopyKey(state) : 'consentNeeded';
  const askable = isAskable(state, text);
  const first = state === null && busy;

  return (
    <AnimatedBackground pinned>
      <View style={[s.page, { paddingTop: insets.top }]}>
        <View style={s.header}>
          <Pressable
            onPress={() => router.back()}
            style={s.headerBtn}
            accessibilityRole="button"
            accessibilityLabel={t('back')}
          >
            <ArrowLeft size={24} strokeWidth={2} color={outdoor.text} />
          </Pressable>
          <Text style={s.headerTitle} numberOfLines={1}>{t('screenTitle')}</Text>
          <View style={s.headerBtn} />
        </View>

        <ScrollView
          contentContainerStyle={[s.body, { paddingBottom: insets.bottom + spacing.xl }]}
        >
          {first ? (
            <View style={s.centre}><ActivityIndicator color={outdoor.text} /></View>
          ) : (
            <>
              <View style={s.ledeRow}>
                {state === UNKNOWN || state === DECLINED
                  ? <AlertTriangle size={22} strokeWidth={1.75} color={outdoor.text} />
                  : <ShieldCheck size={22} strokeWidth={1.75} color={outdoor.text} />}
                <Text style={s.lede}>{t(key)}</Text>
              </View>
              <Text style={s.ledeBody}>{t(`${key}Body`)}</Text>

              {/* THE REFUSAL, WITH ITS DATE. Shown before the agreement so the
                  page states the consequence first and does not read as the
                  same question asked again. */}
              {state === DECLINED ? (
                <View style={s.declinedWell}>
                  <FileText size={18} strokeWidth={1.75} color={outdoor.text} />
                  <Text style={s.declinedText}>
                    {declinedAt
                      ? t('declinedOn').replace('{date}', String(declinedAt).slice(0, 10))
                      : t('declinedNoDate')}
                  </Text>
                </View>
              ) : null}

              {askable ? (
                <View style={s.textWell}>
                  {/* Split on blank lines only. The server sends four
                      paragraphs; one block is how a wall of text gets skipped
                      by the person it was written for. */}
                  {String(text).split(/\n\s*\n/).map((para, i) => (
                    // eslint-disable-next-line react/no-array-index-key
                    <Text key={i} style={[s.para, i > 0 && s.paraGap]}>{para.trim()}</Text>
                  ))}
                </View>
              ) : null}

              {error ? (
                <Text style={s.error}>{consentGateCopy(t, error)}</Text>
              ) : null}

              <View style={s.actions}>
                {askable ? (
                  <>
                    <Pressable
                      onPress={onAgree}
                      disabled={busy}
                      style={[s.primary, busy && s.dim]}
                      accessibilityRole="button"
                    >
                      {busy
                        ? <ActivityIndicator color={outdoor.textOnSelected} />
                        : (
                          <Text style={s.primaryText}>
                            {state === DECLINED ? t('agreeAfterAll') : t('agree')}
                          </Text>
                        )}
                    </Pressable>

                    {/* NOT OFFERED AGAIN ONCE RECORDED. Declining twice writes
                        a second row saying the same thing; the state already
                        says it, and the way forward from here is agreeing or
                        leaving. */}
                    {state === DECLINED ? null : (
                      <Pressable
                        onPress={onDecline}
                        disabled={busy}
                        style={[s.secondary, busy && s.dim]}
                        accessibilityRole="button"
                      >
                        <Text style={s.secondaryText}>{t('decline')}</Text>
                      </Pressable>
                    )}
                  </>
                ) : (
                  <Pressable
                    onPress={async () => { setBusy(true); setError(''); await read(); if (alive.current) setBusy(false); }}
                    disabled={busy}
                    style={[s.primary, busy && s.dim]}
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

                <Pressable
                  onPress={() => router.back()}
                  style={s.tertiary}
                  accessibilityRole="button"
                >
                  <Text style={s.tertiaryText}>{t('backToLog')}</Text>
                </Pressable>
              </View>

              {/* WHICH WORDING THIS IS. Not decoration: the record stores the
                  text verbatim against a dated version, and a person is
                  entitled to see which one he is being shown. */}
              {askable ? (
                <Text style={s.version}>{t('versionNote')}</Text>
              ) : null}
            </>
          )}
        </ScrollView>
      </View>
    </AnimatedBackground>
  );
}

// PINNED. Reached only from the pinned logbook editors, and readable in sun
// for the same reason they are. If a live-themed screen ever routes here, this
// becomes a light page inside a dark app and the decision has to be re-taken.
const s = StyleSheet.create({
  page: { flex: 1 },
  header: {
    flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
  },
  headerBtn: {
    minWidth: touchTarget.min, minHeight: touchTarget.min,
    alignItems: 'center', justifyContent: 'center',
  },
  headerTitle: {
    flex: 1, textAlign: 'center', color: outdoor.text,
    fontSize: typography.sizes.lg, fontWeight: '700',
  },
  body: { paddingHorizontal: spacing.md, paddingTop: spacing.sm },
  centre: { paddingTop: spacing.xxl, alignItems: 'center' },
  ledeRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  lede: {
    flex: 1, color: outdoor.text,
    fontSize: typography.sizes.xl, fontWeight: '700',
  },
  ledeBody: {
    color: outdoor.textSoft, fontSize: typography.sizes.md,
    lineHeight: 23, marginTop: spacing.sm, marginBottom: spacing.md,
  },
  declinedWell: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    backgroundColor: outdoor.surfaceSunk,
    borderRadius: borderRadius.md,
    borderWidth: 1, borderColor: outdoor.lineStrong,
    padding: spacing.md, marginBottom: spacing.md,
  },
  declinedText: { flex: 1, color: outdoor.text, fontSize: typography.sizes.dense, lineHeight: 20 },
  textWell: {
    backgroundColor: outdoor.cardTop,
    borderRadius: borderRadius.md,
    borderWidth: 1, borderColor: outdoor.line,
    padding: spacing.md,
    ...outdoorShadow,
  },
  // 16, not 13. He is reading a legal agreement outdoors, possibly at arm's
  // length, and this is the one screen where the words are the product.
  para: { color: outdoor.text, fontSize: typography.sizes.md, lineHeight: 24 },
  paraGap: { marginTop: spacing.md },
  error: {
    marginTop: spacing.md, color: outdoor.text,
    fontSize: typography.sizes.dense, lineHeight: 20,
  },
  actions: { marginTop: spacing.lg, gap: spacing.sm },
  primary: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: spacing.sm,
    minHeight: touchTarget.primary,
    borderRadius: borderRadius.md,
    backgroundColor: outdoor.surfaceSelected,
  },
  primaryText: {
    color: outdoor.textOnSelected,
    fontSize: typography.sizes.lg, fontWeight: '700',
  },
  secondary: {
    alignItems: 'center', justifyContent: 'center',
    minHeight: touchTarget.min,
    borderRadius: borderRadius.md,
    borderWidth: 1, borderColor: outdoor.lineStrong,
  },
  secondaryText: { color: outdoor.text, fontSize: typography.sizes.md, fontWeight: '600' },
  tertiary: { minHeight: touchTarget.min, alignItems: 'center', justifyContent: 'center' },
  tertiaryText: { color: outdoor.textDim, fontSize: typography.sizes.dense },
  dim: { opacity: opacity.o50 },
  version: {
    marginTop: spacing.md, color: outdoor.textDim,
    fontSize: typography.sizes.fine, lineHeight: 17,
  },
});
