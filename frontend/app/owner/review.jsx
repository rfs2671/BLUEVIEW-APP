import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Modal,
  RefreshControl, TextInput,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ShieldAlert, Check, X, Square, SquareCheck } from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import OwnerNav from '../../src/components/OwnerNav';
import MarkWrongForm from '../../src/components/MarkWrongForm';
import OfflineNotice from '../../src/components/OfflineNotice';
import { useToast } from '../../src/components/Toast';
import { useAuth, isPlatformOperator } from '../../src/context/AuthContext';
import { useTheme } from '../../src/context/ThemeContext';
import { ownerAPI } from '../../src/utils/api';
import { settleFetch, isOfflineError } from '../../src/utils/offlineState';
import { serverMessage } from '../../src/utils/ownerPortal';
import {
  STATUS_FILTERS, REASON_FILTERS, listParams, itemView, decideRequest,
  reconcileAfterDecision, companyChoices,
} from '../../src/utils/reviewQueue';
import { spacing, borderRadius } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';

const PAGE = 25;

/**
 * OWNER PORTAL → REVIEW QUEUE (L6.4). Auto-queued findings, newest first.
 * Default "Needs decision": pending, normal priority. An item opens with its
 * question, answer, records and gates; Approve / Deny need an explanation.
 * Nobody is notified (customers do not flag answers). A decided item can be
 * decided again with a new explanation; its history is shown. An item with
 * an answer also carries Mark wrong (MarkWrongForm): the correct answer and
 * an optional note, saved as an append-only correction. The Approve / Deny row is pinned at the bottom of the detail (a
 * footer outside the scroll), so it is always in view on a phone. The server
 * is the gate: /api/owner/* is 404 to anyone else.
 */
export default function OwnerReviewScreen() {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const router = useRouter();
  const toast = useToast();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const isOperator = isPlatformOperator(user);

  const [status, setStatus] = useState('pending');
  const [reason, setReason] = useState('');
  const [company, setCompany] = useState('');
  const [showLow, setShowLow] = useState(false);
  const [items, setItems] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [hasMore, setHasMore] = useState(false);
  const [state, setState] = useState('loading');
  const [refreshing, setRefreshing] = useState(false);
  const [open, setOpen] = useState(null);      // { item, state }
  const [explanation, setExplanation] = useState('');
  const [formError, setFormError] = useState('');
  const [corrections, setCorrections] = useState([]);
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [authLoading, isAuthenticated]);

  const load = useCallback(async (more = false) => {
    if (!isOperator) return;
    const offset = more ? items.length : 0;
    const res = await settleFetch(() => ownerAPI.reviewQueue(
      listParams({ status, reason, company, showLow, offset, limit: PAGE })));
    setState(res.status);
    if (res.status === 'ok') {
      const got = Array.isArray(res.data?.items) ? res.data.items : [];
      setItems(more ? items.concat(got) : got);
      setHasMore(res.data?.has_more === true);
      if (Array.isArray(res.data?.companies)) setCompanies(res.data.companies);
    }
    setRefreshing(false);
  }, [isOperator, status, reason, company, showLow, items]);

  useEffect(() => { load(false); }, [isOperator, status, reason, company, showLow]);

  const openItem = async (row) => {
    setExplanation(''); setFormError(''); setCorrections([]);
    setOpen({ item: row, state: 'loading' });
    const res = await settleFetch(() => ownerAPI.reviewItem(row.id));
    setOpen((o) => (o && o.item.id === row.id
      ? { item: res.status === 'ok' && res.data?.item ? res.data.item : row, state: res.status }
      : o));
    // The answer's corrections so far (Mark wrong lists them above the form).
    const answerId = row.answer?.id || row.answer_log_id;
    if (answerId) {
      const got = await settleFetch(() => ownerAPI.answer(answerId));
      if (got.status === 'ok' && Array.isArray(got.data?.corrections)) {
        setCorrections(got.data.corrections);
      }
    }
  };

  const decide = async (decision) => {
    const it = open?.item;
    if (!it) return;
    const iv = itemView(it);
    const req = decideRequest(decision, explanation,
      iv.decision ? iv.decision.explanation : null);
    if (req.error) { setFormError(req.error); return; }
    setFormError('');
    setBusy(decision);
    try {
      const res = await ownerAPI.reviewDecide(it.id, req.body);
      toast.success(decision === 'approve' ? 'Approved' : 'Denied', 'Decided.');
      setOpen({ item: res?.item || it, state: 'ok' });
      setExplanation('');
      // A decided item that no longer matches the status filter leaves the
      // list, so the next "Load more" offset (items.length) stays aligned
      // with the server's shrunken result set.
      setItems((list) => reconcileAfterDecision(list, it.id, res?.item, status));
    } catch (e) {
      const msg = isOfflineError(e)
        ? 'Deciding needs a connection. Nothing changed.' : serverMessage(e);
      setFormError(msg);
    } finally {
      setBusy(null);
    }
  };

  if (!authLoading && isAuthenticated && !isOperator) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <OwnerNav />
          <GlassCard style={s.emptyCard}>
            <ShieldAlert size={28} strokeWidth={1.5} color={semantic.attention} />
            <Text style={s.line}>Platform operator access required.</Text>
          </GlassCard>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  const chip = (key, label, on, onPress) => (
    <Pressable key={key} onPress={onPress} accessibilityRole="tab"
      accessibilityState={{ selected: on }}
      style={({ pressed }) => [s.chip, on && s.chipOn, pressed && s.pressed]}>
      <Text style={[s.chipText, on && s.chipTextOn]}>{label}</Text>
    </Pressable>
  );

  const ov = open ? itemView(open.item) : null;

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <OwnerNav title="Review queue" />
        <ScrollView
          style={s.scroll}
          contentContainerStyle={s.content}
          refreshControl={(
            <RefreshControl refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); load(false); }} />
          )}
        >
          <View style={s.filters}>
            {STATUS_FILTERS.map((f) => chip(f.key, f.label, f.key === status,
              () => setStatus(f.key)))}
          </View>
          <View style={s.filters}>
            {REASON_FILTERS.map((f) => chip(f.key || 'all', f.label, f.key === reason,
              () => setReason(f.key)))}
          </View>
          {companies.length > 1 || company ? (
            <View style={s.filters}>
              {chip('all-co', 'All companies', company === '', () => setCompany(''))}
              {companyChoices(companies, company).map((c) => chip(c.id, c.name || c.id,
                c.id === company, () => setCompany(c.id)))}
            </View>
          ) : null}
          <Pressable onPress={() => setShowLow(!showLow)} accessibilityRole="checkbox"
            accessibilityState={{ checked: showLow }}
            style={({ pressed }) => [s.check, pressed && s.pressed]}>
            {showLow
              ? <SquareCheck size={18} strokeWidth={1.75} color={colors.text.primary} />
              : <Square size={18} strokeWidth={1.75} color={colors.text.secondary} />}
            <Text style={s.checkText}>Show low priority</Text>
          </Pressable>

          {state === 'loading' ? (
            <ActivityIndicator size="small" color={colors.text.secondary} />
          ) : state !== 'ok' ? (
            <OfflineNotice mode={state}
              detail="The review queue could not be loaded. Do not read this as nothing to review." />
          ) : items.length === 0 ? (
            <GlassCard style={s.emptyCard}>
              <Text style={s.line}>Nothing here.</Text>
            </GlassCard>
          ) : items.map((row) => {
            const v = itemView(row);
            return (
              <Pressable key={v.key} onPress={() => openItem(row)} accessibilityRole="button"
                accessibilityLabel={`Open ${v.label} item, ${v.company}`}>
                {({ pressed }) => (
                  <GlassCard style={[s.rowCard, pressed && s.pressed]}>
                    <View style={s.rowHead}>
                      <Text style={s.kind}>{v.label}</Text>
                      {v.low ? <Text style={s.lowBadge}>Low priority</Text> : null}
                      {v.decision ? (
                        <Text style={[s.badge, v.decision.text === 'Approved'
                          ? s.badgeOk : s.badgeNo]}>{v.decision.text}</Text>
                      ) : null}
                    </View>
                    <Text style={s.meta}>
                      {v.company}{v.project ? ` · ${v.project}` : ''} · {v.when}
                    </Text>
                    {v.summary ? <Text style={s.name} numberOfLines={2}>{v.summary}</Text> : null}
                    {v.question ? (
                      <Text style={s.meta} numberOfLines={1}>Q: {v.question}</Text>
                    ) : null}
                    {v.answer ? (
                      <Text style={s.meta} numberOfLines={2}>A: {v.answer}</Text>
                    ) : null}
                  </GlassCard>
                )}
              </Pressable>
            );
          })}
          {state === 'ok' && hasMore ? (
            <Pressable onPress={() => load(true)} accessibilityRole="button"
              style={({ pressed }) => [s.btn, s.more, pressed && s.pressed]}>
              <Text style={s.btnText}>Load more</Text>
            </Pressable>
          ) : null}
        </ScrollView>

        <Modal visible={!!open} transparent animationType="fade"
          onRequestClose={() => setOpen(null)}>
          <View style={s.backdrop}>
            <GlassCard variant="modal" style={s.modalCard} contentStyle={s.modalContent}>
              {ov ? (
                <ScrollView style={s.detailScroll} contentContainerStyle={s.detail}>
                  <View style={s.rowHead}>
                    <Text style={s.kind}>{ov.label}</Text>
                    {ov.low ? <Text style={s.lowBadge}>Low priority</Text> : null}
                  </View>
                  <Text style={s.meta}>
                    {ov.company}{ov.project ? ` · ${ov.project}` : ''} · {ov.when}
                  </Text>
                  {ov.summary ? <Text style={s.name}>{ov.summary}</Text> : null}
                  {open.state === 'loading'
                    ? <ActivityIndicator size="small" color={colors.text.secondary} /> : null}
                  {ov.question !== null ? (
                    <>
                      <Text style={s.section}>QUESTION</Text>
                      <Text style={s.line}>{ov.question || '—'}</Text>
                      <Text style={s.section}>ANSWER</Text>
                      <Text style={s.line}>{ov.answer || '—'}</Text>
                      <Text style={s.section}>RECORDS</Text>
                      {ov.records.length === 0 ? <Text style={s.meta}>None shown.</Text>
                        : ov.records.map((r) => (
                          <Text key={r.key} style={s.meta}>
                            {r.sheet ? `${r.sheet}: ` : ''}{r.text}
                          </Text>
                        ))}
                      {ov.recordsMore ? <Text style={s.meta}>+{ov.recordsMore} more</Text> : null}
                      <Text style={s.section}>GATES</Text>
                      {ov.gates.length === 0 ? <Text style={s.meta}>None recorded.</Text>
                        : ov.gates.map((g, i) => <Text key={`${g}-${i}`} style={s.meta}>{g}</Text>)}
                      {ov.build ? <Text style={s.pending}>{ov.build}</Text> : null}
                      {ov.answerLog && ov.answerLog.id ? (
                        <MarkWrongForm answerId={ov.answerLog.id} corrections={corrections} />
                      ) : null}
                    </>
                  ) : null}
                  {ov.evidence && Object.keys(ov.evidence).length ? (
                    <>
                      <Text style={s.section}>EVIDENCE</Text>
                      <Text style={s.mono}>{JSON.stringify(ov.evidence, null, 2)}</Text>
                    </>
                  ) : null}

                  {ov.decision ? (
                    <View style={s.decided}>
                      <Text style={s.section}>
                        {ov.history.length > 1 ? `DECISIONS (${ov.history.length})` : 'DECISION'}
                      </Text>
                      {(ov.history.length ? ov.history : [ov.decision]).map((d, i) => (
                        <View key={`${d.when}-${i}`} style={[s.decisionRow, i > 0 && s.decisionOld]}>
                          <Text style={[s.name, d.text === 'Approved' ? s.badgeOk : s.badgeNo]}>
                            {d.text}{i === 0 ? '' : ' (earlier)'}
                          </Text>
                          <Text style={s.line}>{d.explanation}</Text>
                          <Text style={s.meta}>{d.when}</Text>
                        </View>
                      ))}
                    </View>
                  ) : null}
                  {ov.decision || ov.pending ? (
                    <View style={s.form}>
                      <Text style={s.section}>
                        {ov.decision ? 'CHANGE THE DECISION: NEW EXPLANATION (REQUIRED)'
                          : 'EXPLANATION (REQUIRED)'}
                      </Text>
                      <TextInput
                        value={explanation}
                        onChangeText={(t) => { setExplanation(t); setFormError(''); }}
                        placeholder="What you checked, and why"
                        placeholderTextColor={colors.text.subtle}
                        style={s.input}
                        multiline
                        accessibilityLabel="Explanation"
                      />
                      {formError ? <Text style={s.blockText}>{formError}</Text> : null}
                    </View>
                  ) : null}
                </ScrollView>
              ) : null}
              {/* THE FOOTER: pinned below the scroll, always in view. */}
              <View style={s.footer}>
                {ov && (ov.decision || ov.pending) ? (
                  <View style={s.modalActions}>
                    <Pressable onPress={() => decide('deny')} disabled={!!busy}
                      accessibilityRole="button" accessibilityLabel="Deny"
                      style={({ pressed }) => [s.cancelBtn, s.rowBtn, pressed && s.pressed]}>
                      {busy === 'deny'
                        ? <ActivityIndicator size="small" color={colors.text.secondary} />
                        : <X size={15} strokeWidth={1.75} color={colors.text.primary} />}
                      <Text style={s.btnText}>Deny</Text>
                    </Pressable>
                    <Pressable onPress={() => decide('approve')} disabled={!!busy}
                      accessibilityRole="button" accessibilityLabel="Approve"
                      style={({ pressed }) => [s.okBtn, s.rowBtn, pressed && s.pressed]}>
                      {busy === 'approve'
                        ? <ActivityIndicator size="small" color={colors.onPrimary} />
                        : <Check size={15} strokeWidth={2} color={colors.onPrimary} />}
                      <Text style={s.okText}>Approve</Text>
                    </Pressable>
                  </View>
                ) : null}
                <Pressable onPress={() => setOpen(null)} style={[s.cancelBtn, s.closeBtn]}
                  accessibilityRole="button">
                  <Text style={s.cancelText}>Close</Text>
                </Pressable>
              </View>
            </GlassCard>
          </View>
        </Modal>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    container: { flex: 1 },
    scroll: { flex: 1 },
    content: { padding: spacing.lg, paddingBottom: 120, gap: spacing.sm },
    filters: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
    chip: {
      minHeight: 36, justifyContent: 'center', paddingHorizontal: spacing.md,
      borderRadius: borderRadius.full, borderWidth: 1, borderColor: colors.glass.border,
    },
    chipOn: { backgroundColor: colors.glass.background, borderColor: colors.text.secondary },
    chipText: { fontSize: 13, color: colors.text.secondary },
    chipTextOn: { color: colors.text.primary, fontWeight: '600' },
    check: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, minHeight: 44 },
    checkText: { fontSize: 14, color: colors.text.primary },
    emptyCard: { padding: spacing.lg, alignItems: 'center', gap: spacing.sm, margin: spacing.lg },
    line: { fontSize: 14, color: colors.text.primary, lineHeight: 20 },
    rowCard: { padding: spacing.md, gap: 4 },
    rowHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' },
    kind: {
      fontSize: 12, fontWeight: '700', letterSpacing: 1, color: colors.text.muted,
      textTransform: 'uppercase', flexShrink: 1,
    },
    lowBadge: { fontSize: 12, fontWeight: '600', color: semantic.neutral },
    badge: { fontSize: 12, fontWeight: '600' },
    badgeOk: { color: semantic.verified },
    badgeNo: { color: semantic.attention },
    name: { fontSize: 15, fontWeight: '600', color: colors.text.primary, lineHeight: 20 },
    meta: { fontSize: 13, color: colors.text.secondary, lineHeight: 18 },
    section: {
      fontSize: 11, fontWeight: '700', letterSpacing: 1, color: colors.text.muted,
      marginTop: spacing.sm,
    },
    mono: { fontSize: 12, color: colors.text.secondary, fontFamily: 'monospace' },
    btn: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
      minHeight: 44, paddingHorizontal: spacing.md, borderRadius: borderRadius.lg,
      borderWidth: 1, borderColor: colors.glass.border,
    },
    more: { alignSelf: 'center' },
    btnText: { fontSize: 14, fontWeight: '500', color: colors.text.primary },
    pending: { fontSize: 12, color: colors.text.muted, marginTop: 2 },
    backdrop: {
      flex: 1, backgroundColor: withAlpha('#000000', 0.6),
      alignItems: 'center', justifyContent: 'center', padding: spacing.lg,
    },
    modalCard: { padding: spacing.lg, gap: spacing.sm, width: '100%', maxWidth: 560, maxHeight: '90%' },
    // The card's content column shrinks to the card, so the scroll (not the
    // page) takes the overflow and the footer stays inside the card.
    modalContent: { flexShrink: 1, minHeight: 0, gap: spacing.sm },
    // The detail scrolls; the footer (Approve / Deny, Close) does not.
    detailScroll: { flexGrow: 0, flexShrink: 1, minHeight: 0 },
    footer: {
      flexShrink: 0, gap: spacing.xs, paddingTop: spacing.sm,
      borderTopWidth: 1, borderTopColor: colors.glass.border,
    },
    closeBtn: { flex: 0 },
    decisionRow: { gap: 2 },
    decisionOld: { opacity: 0.7, marginTop: spacing.xs },
    detail: { gap: 4 },
    decided: { marginTop: spacing.md, gap: 4 },
    form: { marginTop: spacing.xs, gap: spacing.xs },
    input: {
      minHeight: 88, borderWidth: 1, borderColor: colors.glass.border,
      borderRadius: borderRadius.lg, padding: spacing.sm,
      color: colors.text.primary, fontSize: 15, textAlignVertical: 'top',
    },
    blockText: { fontSize: 13, color: semantic.attention, lineHeight: 18 },
    modalActions: { flexDirection: 'row', gap: spacing.sm },
    rowBtn: { flexDirection: 'row', gap: 6 },
    cancelBtn: {
      flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.glass.border,
    },
    cancelText: { fontSize: 14, color: colors.text.secondary },
    okBtn: {
      flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.lg, backgroundColor: colors.primary || '#2563eb',
    },
    okText: { fontSize: 14, fontWeight: '700', color: colors.onPrimary },
    pressed: { opacity: 0.8 },
  });
}
