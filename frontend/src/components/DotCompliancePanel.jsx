// ─── The DOT tab of the Compliance screen (DOT Phase 1 B) ────────────────────
//
// Rendered by app/project/[id]/dob-logs.jsx when the "DOT Permits" tab is
// active. Top to bottom:
//   1. Setup card (until confirmed): the blocks the site fronts and the names
//      its permits are filed under, suggested by the server; Confirm is one
//      tap for a company admin or full-access Site Manager/PM. A
//      superintendent can only suggest a frontage; a CP reads.
//   2. #852's holiday-embargo banner (passed in as `embargoBanner`).
//   3. Needs confirmation: permits by ANOTHER permittee on a confirmed block,
//      "Yours?" / "Not ours" (admin and full-access PM only).
//   4. Permits: active, then expiring within 14 days, then expired.
//
// The server decides every role question (can_confirm / can_suggest /
// can_review) and every date question (group, days_left): this component
// only renders what it is told, so the screen and the alerts cannot disagree.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Linking } from 'react-native';
import { CheckSquare, Square, Trash2, ExternalLink, RefreshCw } from 'lucide-react-native';
import { GlassCard } from './GlassCard';
import GlassButton from './GlassButton';
import GlassInput from './GlassInput';
import { dobAPI } from '../utils/api';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius } from '../styles/theme';
import { semantic } from '../styles/semanticColors';
import { formatRecordDate } from '../utils/dates';
import { useT } from '../i18n';

const fill = (s, vars) => Object.keys(vars || {}).reduce(
  (out, k) => out.split(`{${k}}`).join(String(vars[k] ?? '')), String(s || ''),
);

const sameFrontage = (a, b) => {
  const pair = (f) => [String(f.from || ''), String(f.to || '')].sort().join('|');
  return String(a.boro || '') === String(b.boro || '')
    && String(a.on || '') === String(b.on || '') && pair(a) === pair(b);
};

export default function DotCompliancePanel({ projectId, embargoBanner, toast }) {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const t = useT('dotCompliance');

  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [board, setBoard] = useState(null);
  const [setupData, setSetupData] = useState(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [permitteeDraft, setPermitteeDraft] = useState([]);
  const [frontageDraft, setFrontageDraft] = useState([]);
  const [newPermittee, setNewPermittee] = useState('');
  const [newFrontage, setNewFrontage] = useState({ on: '', from: '', to: '' });

  const frontageLabel = (f) => {
    if (!f) return '';
    if (f.from && f.to) return fill(t('frontageText'), { on: f.on, from: f.from, to: f.to });
    return fill(t('frontageOneCross'), { on: f.on, cross: f.from || f.to });
  };

  // The drafts the setup card edits: what is stored, plus what the server
  // suggests (pre-checked as it says), plus the fallback blocks (unchecked).
  const buildDrafts = useCallback((data) => {
    const setup = (data && data.setup) || {};
    const sug = (data && data.suggestions) || {};
    const fb = (data && data.fallback) || null;
    const stored = Array.isArray(setup.permittees) ? setup.permittees : [];
    const people = stored.map((p) => ({ name: p.name, norm: p.norm, count: (p.seen_on || []).length, checked: true }));
    (sug.permittees || []).forEach((p) => {
      if (!people.some((x) => x.norm === p.norm)) {
        people.push({ name: p.name, norm: p.norm, count: p.count || 0, checked: !!p.checked });
      }
    });
    const fronts = (setup.frontages || []).map((f) => ({ ...f, checked: true, stored: true }));
    (sug.frontages || []).forEach((f) => {
      if (!fronts.some((x) => sameFrontage(x, f))) fronts.push({ ...f, checked: true });
    });
    if (fb && Array.isArray(fb.cross_segments)) {
      fb.cross_segments.forEach((f) => {
        if (!fronts.some((x) => sameFrontage(x, f))) fronts.push({ ...f, checked: false, fallback: true });
      });
    }
    setPermitteeDraft(people);
    setFrontageDraft(fronts);
    setNewFrontage((cur) => ({ ...cur, on: cur.on || data?.project_street || '' }));
  }, []);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      const [b, st] = await Promise.all([
        dobAPI.getDotPermits(projectId),
        dobAPI.getDotSetup(projectId),
      ]);
      setBoard(b || {});
      setSetupData(st || {});
      buildDrafts(st || {});
    } catch (e) {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [projectId, buildDrafts]);

  useEffect(() => { if (projectId) load(); }, [projectId, load]);

  const fail = () => { if (toast) toast.error('DOT', t('saveFailed')); };

  const setup = (setupData && setupData.setup) || {};
  const status = setup.status || 'unset';
  const canConfirm = !!(setupData && setupData.can_confirm);
  const canSuggest = !!(setupData && setupData.can_suggest);
  const canReview = !!(board && board.can_review);
  const showSetupCard = status !== 'confirmed' || editing;

  const onConfirm = async () => {
    setBusy(true);
    try {
      await dobAPI.confirmDotSetup(projectId, {
        permittees: permitteeDraft.filter((p) => p.checked).map((p) => p.name),
        frontages: frontageDraft.filter((f) => f.checked)
          .map((f) => ({ boro: f.boro, on: f.on, from: f.from, to: f.to })),
      });
      setEditing(false);
      if (toast) toast.success(t('confirmedTitle'), t('nextCheck'));
      await load();
    } catch (e) { fail(); } finally { setBusy(false); }
  };

  const onAddFrontage = async () => {
    const f = { on: newFrontage.on.trim(), from: newFrontage.from.trim(), to: newFrontage.to.trim() };
    if (!f.on || (!f.from && !f.to)) {
      if (toast) toast.warning('DOT', t('frontageInvalid'));
      return;
    }
    setBusy(true);
    try {
      await dobAPI.addDotFrontage(projectId, { ...f, boro: setupData?.project_boro || undefined });
      setNewFrontage({ on: f.on, from: '', to: '' });
      if (!canConfirm && toast) toast.success('DOT', t('suggestionSent'));
      await load();
    } catch (e) {
      if (toast) toast.error('DOT', e?.response?.status === 422 ? t('frontageInvalid') : t('saveFailed'));
    } finally { setBusy(false); }
  };

  const onRemoveFrontage = async (index) => {
    setBusy(true);
    try {
      await dobAPI.removeDotFrontage(projectId, index);
      await load();
    } catch (e) { fail(); } finally { setBusy(false); }
  };

  const onReview = async (permit, decision) => {
    setBusy(true);
    try {
      await dobAPI.reviewDotPermit(projectId, permit, decision);
      await load();
    } catch (e) { fail(); } finally { setBusy(false); }
  };

  const addPermittee = () => {
    const name = newPermittee.trim();
    if (!name) return;
    const norm = name.toUpperCase();
    setPermitteeDraft((cur) => (cur.some((p) => (p.name || '').toUpperCase() === norm)
      ? cur : [...cur, { name, norm, count: 0, checked: true }]));
    setNewPermittee('');
  };

  if (loading) {
    return (
      <View style={s.center}>
        <ActivityIndicator color={colors.text.primary} />
      </View>
    );
  }

  const Check = ({ on, onPress, disabled, children }) => (
    <Pressable onPress={disabled ? undefined : onPress} style={s.checkRow} accessibilityRole="checkbox"
      accessibilityState={{ checked: !!on, disabled: !!disabled }}>
      {on
        ? <CheckSquare size={18} strokeWidth={1.8} color={disabled ? colors.text.muted : semantic.verified} />
        : <Square size={18} strokeWidth={1.8} color={colors.text.muted} />}
      <View style={s.checkBody}>{children}</View>
    </Pressable>
  );

  // ── 1. Setup ──────────────────────────────────────────────────────────────
  const fb = setupData && setupData.fallback;
  const sugFrontages = (setupData?.suggestions?.frontages || []).length;
  const setupCard = showSetupCard ? (
    <GlassCard style={s.card}>
      <Text style={s.cardTitle}>{t('setupTitle')}</Text>
      <Text style={s.body}>{t('setupIntro')}</Text>
      {sugFrontages > 0 ? <Text style={s.note}>{t('suggestedNote')}</Text> : null}
      {sugFrontages === 0 && fb && (fb.cross_segments || []).length > 0
        ? <Text style={s.note}>{fill(t('fallbackNote'), { street: fb.on })}</Text> : null}
      {sugFrontages === 0 && (!fb || !(fb.cross_segments || []).length) && !(setup.frontages || []).length
        ? <Text style={s.note}>{t('noSuggestions')}</Text> : null}

      <Text style={s.section}>{t('frontagesLabel')}</Text>
      {frontageDraft.map((f, i) => {
        const pendingSuper = f.stored && f.source === 'superintendent' && !f.confirmed;
        return (
          <View key={`f-${i}`} style={s.itemRow}>
            <Check on={f.checked} disabled={!canConfirm}
              onPress={() => setFrontageDraft((cur) => cur.map((x, j) => (j === i ? { ...x, checked: !x.checked } : x)))}>
              <Text style={s.itemText}>{frontageLabel(f)}</Text>
              {f.count ? <Text style={s.meta}>{f.count === 1 ? t('seenOnOne') : fill(t('seenOn'), { n: f.count })}</Text> : null}
              {pendingSuper ? (
                <Text style={s.metaAttention}>
                  {f.suggested_by_name ? fill(t('suggestedBy'), { name: f.suggested_by_name }) : t('suggestedByUnknown')}
                  {' · '}{t('pendingSuggestion')}
                </Text>
              ) : null}
            </Check>
            {canConfirm && f.stored && typeof f.index === 'number' ? (
              <Pressable onPress={() => onRemoveFrontage(f.index)} hitSlop={8} accessibilityRole="button"
                accessibilityLabel={t('remove')} style={s.iconBtn} disabled={busy}>
                <Trash2 size={16} strokeWidth={1.6} color={colors.text.muted} />
              </Pressable>
            ) : null}
          </View>
        );
      })}

      {canSuggest ? (
        <View style={s.form}>
          <GlassInput value={newFrontage.on} onChangeText={(v) => setNewFrontage((c) => ({ ...c, on: v }))}
            placeholder={t('onStreet')} autoCapitalize="characters" />
          <View style={s.formRow}>
            <GlassInput style={s.formHalf} value={newFrontage.from}
              onChangeText={(v) => setNewFrontage((c) => ({ ...c, from: v }))}
              placeholder={t('fromStreet')} autoCapitalize="characters" />
            <GlassInput style={s.formHalf} value={newFrontage.to}
              onChangeText={(v) => setNewFrontage((c) => ({ ...c, to: v }))}
              placeholder={t('toStreet')} autoCapitalize="characters" />
          </View>
          <GlassButton title={canConfirm ? t('addFrontage') : t('suggestFrontage')} onPress={onAddFrontage}
            disabled={busy} style={s.smallBtn} />
        </View>
      ) : null}

      {canConfirm ? (
        <>
          <Text style={s.section}>{t('permitteesLabel')}</Text>
          {permitteeDraft.map((p, i) => (
            <View key={`p-${i}`} style={s.itemRow}>
              <Check on={p.checked}
                onPress={() => setPermitteeDraft((cur) => cur.map((x, j) => (j === i ? { ...x, checked: !x.checked } : x)))}>
                <Text style={s.itemText}>{p.name}</Text>
                {p.count ? <Text style={s.meta}>{p.count === 1 ? t('seenOnOne') : fill(t('seenOn'), { n: p.count })}</Text> : null}
              </Check>
            </View>
          ))}
          <View style={s.formRow}>
            <GlassInput style={s.formGrow} value={newPermittee} onChangeText={setNewPermittee}
              placeholder={t('permitteeName')} autoCapitalize="characters" />
            <GlassButton title={t('addPermittee')} onPress={addPermittee} style={s.smallBtn} />
          </View>
          <View style={s.actions}>
            {status === 'confirmed' ? (
              <GlassButton title={t('cancel')} onPress={() => { setEditing(false); buildDrafts(setupData); }}
                style={s.smallBtn} disabled={busy} />
            ) : null}
            <GlassButton variant="primary" title={t('confirm')} onPress={onConfirm} disabled={busy} style={s.primaryBtn} />
          </View>
        </>
      ) : (
        <>
          {(setup.permittees || []).length ? <Text style={s.section}>{t('permitteesLabel')}</Text> : null}
          {(setup.permittees || []).map((p, i) => <Text key={`rp-${i}`} style={s.itemText}>{p.name}</Text>)}
          <Text style={s.note}>{t('readOnly')}</Text>
        </>
      )}
    </GlassCard>
  ) : (
    <GlassCard style={s.card}>
      <View style={s.rowBetween}>
        <View style={s.flex}>
          <Text style={s.cardTitle}>{t('confirmedTitle')}</Text>
          <Text style={s.meta}>
            {fill(t('confirmedSummary'), {
              frontages: (setup.frontages || []).filter((f) => f.confirmed).length,
              permittees: (setup.permittees || []).length,
            })}
          </Text>
          {(setup.frontages || []).filter((f) => f.confirmed).map((f, i) => (
            <Text key={`cf-${i}`} style={s.itemText}>{frontageLabel(f)}</Text>
          ))}
        </View>
        {canConfirm ? <GlassButton title={t('edit')} onPress={() => setEditing(true)} style={s.smallBtn} /> : null}
      </View>
      {!canConfirm && canSuggest ? (
        <View style={s.form}>
          <GlassInput value={newFrontage.on} onChangeText={(v) => setNewFrontage((c) => ({ ...c, on: v }))}
            placeholder={t('onStreet')} autoCapitalize="characters" />
          <View style={s.formRow}>
            <GlassInput style={s.formHalf} value={newFrontage.from}
              onChangeText={(v) => setNewFrontage((c) => ({ ...c, from: v }))}
              placeholder={t('fromStreet')} autoCapitalize="characters" />
            <GlassInput style={s.formHalf} value={newFrontage.to}
              onChangeText={(v) => setNewFrontage((c) => ({ ...c, to: v }))}
              placeholder={t('toStreet')} autoCapitalize="characters" />
          </View>
          <GlassButton title={t('suggestFrontage')} onPress={onAddFrontage} disabled={busy} style={s.smallBtn} />
        </View>
      ) : null}
    </GlassCard>
  );

  // ── 3. Needs confirmation ─────────────────────────────────────────────────
  const pending = (board && Array.isArray(board.needs_confirmation)) ? board.needs_confirmation : [];
  const older = (board && board.needs_confirmation_older) || 0;
  const needsCard = (pending.length || older) ? (
    <GlassCard style={[s.card, s.attentionCard]}>
      <Text style={[s.cardTitle, { color: semantic.attention }]}>{t('needsTitle')}</Text>
      {pending.map((p) => (
        <View key={`n-${p.number}`} style={s.permitRow}>
          <Text style={s.itemText}>{fill(t('needsPrompt'), { permittee: p.permittee || t('unknownPermittee') })}</Text>
          <Text style={s.meta}>{[p.number, p.permit_type].filter(Boolean).join(' · ')}</Text>
          {p.work_start || p.work_end ? (
            <Text style={s.meta}>{fill(t('workDates'), { start: formatRecordDate(p.work_start) || '—', end: formatRecordDate(p.work_end) || '—' })}</Text>
          ) : null}
          {p.segment ? <Text style={s.meta}>{frontageLabel(p.segment)}</Text> : null}
          {canReview ? (
            <View style={s.actions}>
              <GlassButton title={t('reject')} onPress={() => onReview(p.number, 'reject')} disabled={busy} style={s.smallBtn} />
              <GlassButton variant="primary" title={t('accept')} onPress={() => onReview(p.number, 'accept')} disabled={busy} style={s.primaryBtn} />
            </View>
          ) : null}
        </View>
      ))}
      {older ? <Text style={s.note}>{fill(t('needsOlder'), { n: older })}</Text> : null}
    </GlassCard>
  ) : null;

  // ── 4. Permits ────────────────────────────────────────────────────────────
  const permits = (board && Array.isArray(board.permits)) ? board.permits : [];
  const groups = [
    ['active', t('groupActive')],
    ['expiring', t('groupExpiring')],
    ['expired', t('groupExpired')],
  ];
  const daysText = (n) => (n === 0 ? t('endsToday') : n === 1 ? t('dayLeft') : fill(t('daysLeft'), { n }));
  const permitCard = (p) => {
    const tone = p.group === 'expiring' ? semantic.attention : p.group === 'expired' ? colors.text.muted : semantic.verified;
    return (
      <View key={`p-${p.number}`} style={s.permitRow}>
        <View style={s.rowBetween}>
          <Text style={s.permitNum}>{p.number}</Text>
          {p.group !== 'expired' && typeof p.days_left === 'number' ? (
            <Text style={[s.days, { color: tone }]}>{daysText(p.days_left)}</Text>
          ) : <Text style={[s.days, { color: tone }]}>{p.status || ''}</Text>}
        </View>
        <Text style={s.meta}>{[p.permit_type, p.series].filter(Boolean).join(' · ')}</Text>
        {p.work_start || p.work_end ? (
          <Text style={s.meta}>{fill(t('workDates'), { start: formatRecordDate(p.work_start) || '—', end: formatRecordDate(p.work_end) || '—' })}</Text>
        ) : null}
        {p.segment ? <Text style={s.meta}>{frontageLabel(p.segment)}</Text> : null}
        {p.permittee ? <Text style={s.meta}>{fill(t('permittee'), { name: p.permittee })}</Text> : null}
        <View style={s.badges}>
          {p.renewed_by ? (
            <View style={[s.badge, { borderColor: semantic.verifiedBorder, backgroundColor: semantic.verifiedBg }]}>
              <RefreshCw size={11} strokeWidth={2} color={semantic.verified} />
              <Text style={[s.badgeText, { color: semantic.verified }]}>{fill(t('renewedBy'), { permit: p.renewed_by })}</Text>
            </View>
          ) : null}
          {p.waiver_missing ? (
            <View style={[s.badge, { borderColor: semantic.attentionBorder, backgroundColor: semantic.attentionBg }]}>
              <Text style={[s.badgeText, { color: semantic.attention }]}>{t('waiverMissing')}</Text>
            </View>
          ) : null}
          {/* Stipulations could not be read: shown, never emailed or posted. */}
          {!p.waiver_missing && p.waiver_unverified ? (
            <View style={[s.badge, { borderColor: semantic.attentionBorder }]}>
              <Text style={[s.badgeText, { color: semantic.attention }]}>{t('waiverUnverified')}</Text>
            </View>
          ) : null}
          {p.link ? (
            <Pressable onPress={() => Linking.openURL(p.link)} hitSlop={6} accessibilityRole="link" style={s.iconBtn}>
              <ExternalLink size={13} strokeWidth={1.6} color={colors.text.muted} />
            </Pressable>
          ) : null}
        </View>
      </View>
    );
  };
  const permitsCard = (
    <GlassCard style={s.card}>
      <Text style={s.cardTitle}>{t('permitsTitle')}</Text>
      {failed ? <Text style={s.metaAttention}>{t('loadFailed')}</Text> : null}
      {!failed && permits.length === 0 ? <Text style={s.note}>{t('noPermits')}</Text> : null}
      {groups.map(([key, label]) => {
        const list = permits.filter((p) => p.group === key);
        if (!list.length) return null;
        return (
          <View key={key} style={s.group}>
            <Text style={s.section}>{label}</Text>
            {list.map(permitCard)}
          </View>
        );
      })}
    </GlassCard>
  );

  return (
    <View style={s.wrap}>
      {failed ? null : setupCard}
      {embargoBanner || null}
      {needsCard}
      {permitsCard}
    </View>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    wrap: { gap: spacing.md, marginBottom: spacing.lg },
    center: { paddingVertical: spacing.xl, alignItems: 'center' },
    card: { gap: spacing.sm },
    attentionCard: { backgroundColor: semantic.attentionBg, borderColor: semantic.attentionBorder },
    cardTitle: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
    body: { fontSize: 13, color: colors.text.secondary, lineHeight: 18 },
    note: { fontSize: 12, color: colors.text.muted, lineHeight: 17 },
    section: { fontSize: 11, fontWeight: '600', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.6, marginTop: spacing.sm },
    itemRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
    checkRow: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm, paddingVertical: 4, flex: 1, minWidth: 0 },
    checkBody: { flex: 1, minWidth: 0 },
    itemText: { fontSize: 13, color: colors.text.primary, lineHeight: 18 },
    meta: { fontSize: 12, color: colors.text.muted, lineHeight: 17 },
    metaAttention: { fontSize: 12, color: semantic.attention, lineHeight: 17 },
    iconBtn: { padding: 4 },
    form: { gap: spacing.sm, marginTop: spacing.xs },
    formRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, alignItems: 'center' },
    formHalf: { flexGrow: 1, flexBasis: 140, minWidth: 140 },
    formGrow: { flexGrow: 1, flexBasis: 180, minWidth: 160 },
    actions: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'flex-end', gap: spacing.sm, marginTop: spacing.sm },
    smallBtn: { minWidth: 96 },
    primaryBtn: { minWidth: 120 },
    rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' },
    flex: { flex: 1, minWidth: 0, gap: 2 },
    group: { gap: spacing.xs },
    permitRow: { gap: 2, paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: colors.glass.border },
    permitNum: { fontSize: 14, fontWeight: '600', color: colors.text.primary },
    days: { fontSize: 12, fontWeight: '600' },
    badges: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, alignItems: 'center', marginTop: 2 },
    badge: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 2, borderRadius: borderRadius.full, borderWidth: 1 },
    badgeText: { fontSize: 11, fontWeight: '600' },
  });
}
