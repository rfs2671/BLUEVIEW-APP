import React, { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Platform,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as DocumentPicker from 'expo-document-picker';
import { ArrowLeft, Check, FileText, Upload } from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import ConfirmDialog from '../../../src/components/ConfirmDialog';
import HeaderBrand from '../../../src/components/HeaderBrand';
import { useToast } from '../../../src/components/Toast';
import { projectScheduleAPI } from '../../../src/utils/api';
import {
  dateLabel, whenLabel, varianceLine, percentLabel, countRows, errorDetail, canManage, confirmMode,
} from '../../../src/utils/projectSchedule';
import { useT } from '../../../src/i18n';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';

// Project → Schedule: import a schedule file, review what was read, confirm.
// The progress report uses a schedule only after an admin confirms it. Every
// figure shown is the file's own; nothing is estimated or verified here.
export default function ProjectScheduleScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { colors } = useTheme();
  const toast = useToast();
  const t = useT('projectSchedule');
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(null); // 'upload' | 'confirm' | 'discard' | `file-<id>`
  const [reviewed, setReviewed] = useState(false);
  const [dialog, setDialog] = useState(null); // 'replace' | 'discard' | 'stop'

  const load = useCallback(async () => {
    setFailed(false);
    try {
      setData(await projectScheduleAPI.get(projectId));
    } catch (e) {
      setFailed(true);
    }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const draft = data?.draft || null;
  const confirmed = data?.confirmed || null;
  const admin = canManage(data);
  const mode = confirmMode(data);

  // A new draft always starts unreviewed.
  useEffect(() => { setReviewed(false); }, [draft?.id]);

  const takeDraft = (view) => setData((d) => ({ ...(d || {}), draft: view }));

  const importFailed = (e) => {
    const rate = e?.response?.status === 429;
    toast?.error?.(t('title'), rate ? t('rateLimited') : errorDetail(e, t('uploadFailed')));
  };

  const pickAndUpload = async () => {
    setBusy('upload');
    try {
      const result = await DocumentPicker.getDocumentAsync({ type: '*/*', copyToCacheDirectory: true });
      if (result.canceled) return;
      const file = result.assets?.[0];
      if (!file) { toast?.error?.(t('title'), t('pickError')); return; }
      const name = file.name || 'schedule';
      const form = new FormData();
      if (Platform.OS === 'web') {
        let blob = file.file;
        if (!blob && file.uri) blob = await (await fetch(file.uri)).blob();
        if (!blob || blob.size === 0) throw new Error('empty');
        form.append('file', blob, name);
      } else {
        form.append('file', { uri: file.uri, name, type: file.mimeType || 'application/octet-stream' });
      }
      takeDraft(await projectScheduleAPI.upload(projectId, form));
    } catch (e) {
      importFailed(e);
    } finally {
      setBusy(null);
    }
  };

  const importSynced = async (c) => {
    setBusy(`file-${c.id}`);
    try {
      takeDraft(await projectScheduleAPI.fromFile(projectId, c.id));
    } catch (e) {
      importFailed(e);
    } finally {
      setBusy(null);
    }
  };

  const confirm = async (replace) => {
    setDialog(null);
    setBusy('confirm');
    try {
      const view = await projectScheduleAPI.confirm(projectId, draft.id, replace);
      setData((d) => ({ ...(d || {}), confirmed: view, draft: null }));
      toast?.success?.(t('confirmedToast'), t('confirmedToastBody'));
    } catch (e) {
      const status = e?.response?.status;
      if (status === 409) {
        // The server says a confirmed schedule exists: show its words and the
        // explicit replace dialog, never a silent retry.
        toast?.error?.(t('title'), errorDetail(e, t('replaceBody')));
        load();
        setDialog('replace');
      } else {
        toast?.error?.(t('title'), errorDetail(e, t('confirmFailed')));
      }
    } finally {
      setBusy(null);
    }
  };

  const discard = async (which) => {
    const target = which === 'stop' ? confirmed : draft;
    setDialog(null);
    if (!target) return;
    setBusy('discard');
    try {
      await projectScheduleAPI.discard(projectId, target.id);
      setData((d) => ({ ...(d || {}), [which === 'stop' ? 'confirmed' : 'draft']: null }));
      toast?.success?.(t(which === 'stop' ? 'stopped' : 'discarded'), '');
    } catch (e) {
      toast?.error?.(t('title'), errorDetail(e, t('actionFailed')));
    } finally {
      setBusy(null);
    }
  };

  const onConfirmPress = () => {
    if (!reviewed) return;
    if (mode === 'replace') setDialog('replace'); else confirm(false);
  };

  const text = { color: colors.text.primary };
  const muted = { color: colors.text.muted };

  const fact = (label, value) => (value === null || value === undefined || value === '' ? null : (
    <View style={styles.fact} key={label}>
      <Text style={[styles.factLabel, muted]}>{label}</Text>
      <Text style={[styles.factValue, text]}>{String(value)}</Text>
    </View>
  ));

  const list = (title, items) => (items && items.length ? (
    <View style={styles.block}>
      <Text style={[styles.label, muted]}>{title}</Text>
      {items.map((w, i) => <Text key={i} style={[styles.hint, text]}>{`• ${w}`}</Text>)}
    </View>
  ) : null);

  const header = (
    <View style={styles.header}>
      <Pressable onPress={() => router.back()} hitSlop={12} accessibilityRole="button"
        accessibilityLabel={t('back')}>
        <ArrowLeft size={22} color={text.color} />
      </Pressable>
      <HeaderBrand />
    </View>
  );

  const importCard = admin ? (
    <GlassCard style={styles.card}>
      <Text style={[styles.section, text]} accessibilityRole="header">{t('importTitle')}</Text>
      <Text style={[styles.hint, muted]}>{t('importFormats')}</Text>
      <View style={styles.buttons}>
        <GlassButton title={busy === 'upload' ? t('uploading') : t('chooseFile')} icon={<Upload size={16} color={text.color} />}
          onPress={pickAndUpload} disabled={!!busy} loading={busy === 'upload'} />
      </View>
      {(data.candidates || []).length > 0 && (
        <View style={styles.block}>
          <Text style={[styles.label, muted]}>{t('syncedTitle')}</Text>
          {data.candidates.map((c) => (
            <View key={c.id} style={styles.candidate}>
              <FileText size={16} color={muted.color} />
              <Text style={[styles.line, text, styles.grow]} numberOfLines={2}>{c.name}</Text>
              <Pressable onPress={() => importSynced(c)} disabled={!!busy} hitSlop={8}
                accessibilityRole="button" accessibilityLabel={`${t('syncedImportLabel')}: ${c.name}`}
                style={[styles.chip, { borderColor: colors.primary }]}>
                {busy === `file-${c.id}`
                  ? <ActivityIndicator size="small" />
                  : <Text style={[styles.chipText, text]}>{t('syncedImport')}</Text>}
              </Pressable>
            </View>
          ))}
        </View>
      )}
    </GlassCard>
  ) : null;

  const preview = draft?.preview || null;
  const proj = preview?.project || null;
  const rows = countRows(preview?.counts);
  const variance = proj ? varianceLine(t, proj.variance_days) : null;
  const pct = proj ? percentLabel(proj.reported_percent) : null;
  const usable = !draft?.preview || preview.usable !== false;

  const draftCard = draft ? (
    <GlassCard style={styles.card}>
      <Text style={[styles.section, text]} accessibilityRole="header">{t('draftTitle')}</Text>
      <Text style={[styles.hint, muted]}>{t('draftNotConfirmed')}</Text>
      <View style={styles.block}>
        {fact(t('source'), draft.source_name)}
        {fact(t('format'), draft.format)}
        {fact(t('dataDate'), dateLabel(draft.data_date))}
        {fact(t('activities'), draft.activities)}
        {fact(t('milestones'), draft.milestones)}
        {fact(t('importedAt'), whenLabel(draft.imported_at))}
      </View>
      {preview && (
        <View style={styles.block}>
          <Text style={[styles.label, muted]}>{t('previewTitle')}</Text>
          <Text style={[styles.hint, muted]}>{t('previewNote')}</Text>
          {rows.map(([k, v]) => fact(t(k), v))}
          {proj && fact(t('originalFinish'), dateLabel(proj.baseline_finish))}
          {proj && fact(t('forecastFinish'), dateLabel(proj.forecast_finish))}
          {variance ? <Text style={[styles.line, text]}>{variance}</Text> : null}
          {pct ? fact(t('reportedPercent'), pct) : null}
          {list(t('limitations'), preview.limitations)}
        </View>
      )}
      {list(t('warnings'), draft.warnings)}
      {!usable && <Text style={[styles.line, { color: colors.status?.error || colors.text.primary }]}>{t('notUsable')}</Text>}
      {admin ? (
        <>
          <Pressable onPress={() => setReviewed((v) => !v)} disabled={!!busy || !usable}
            accessibilityRole="checkbox" accessibilityLabel={t('reviewedLabel')}
            accessibilityState={{ checked: reviewed, disabled: !!busy || !usable }} style={styles.checkRow}>
            <View style={[styles.box, reviewed && { borderColor: colors.primary }]}>
              {reviewed ? <Check size={14} color={text.color} /> : null}
            </View>
            <Text style={[styles.line, text, styles.grow]}>{t('reviewedLabel')}</Text>
          </Pressable>
          <View style={styles.buttons}>
            <GlassButton title={busy === 'confirm' ? t('confirming') : t(mode === 'replace' ? 'confirmReplace' : 'confirm')}
              onPress={onConfirmPress} disabled={!reviewed || !usable || !!busy} loading={busy === 'confirm'} />
            <GlassButton title={t('discard')} onPress={() => setDialog('discard')} disabled={!!busy} />
          </View>
        </>
      ) : null}
    </GlassCard>
  ) : null;

  const confirmedCard = confirmed ? (
    <GlassCard style={styles.card}>
      <Text style={[styles.section, text]} accessibilityRole="header">{t('confirmedTitle')}</Text>
      <Text style={[styles.hint, muted]}>{t('confirmedNote')}</Text>
      <View style={styles.block}>
        {fact(t('source'), confirmed.source_name)}
        {fact(t('format'), confirmed.format)}
        {fact(t('dataDate'), dateLabel(confirmed.data_date))}
        {fact(t('activities'), confirmed.activities)}
        {fact(t('milestones'), confirmed.milestones)}
        {fact(t('confirmedBy'),
          [confirmed.confirmed_by, whenLabel(confirmed.confirmed_at)].filter(Boolean).join(' · '))}
      </View>
      {admin && (
        <View style={styles.buttons}>
          <GlassButton title={t('stopUsing')} onPress={() => setDialog('stop')} disabled={!!busy} />
        </View>
      )}
    </GlassCard>
  ) : null;

  let content;
  if (failed && !data) {
    content = (
      <GlassCard style={styles.card}>
        <Text style={[styles.line, text]} accessibilityRole="alert">{t('loadError')}</Text>
        <View style={styles.buttons}><GlassButton title={t('retry')} onPress={load} /></View>
      </GlassCard>
    );
  } else if (!data) {
    content = <ActivityIndicator style={styles.spinner} accessibilityLabel="Loading" />;
  } else {
    content = (
      <>
        {confirmedCard}
        {draftCard}
        {!confirmed && !draft && (
          <GlassCard style={styles.card}>
            <Text style={[styles.section, text]} accessibilityRole="header">{t('noneTitle')}</Text>
            <Text style={[styles.line, muted]}>{admin ? t('noneBody') : t('noneReadOnly')}</Text>
          </GlassCard>
        )}
        {admin ? importCard : <Text style={[styles.hint, muted]}>{t('readOnlyNote')}</Text>}
      </>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.flex} edges={['top']}>
        {header}
        <ScrollView contentContainerStyle={styles.body}>
          <Text style={[styles.title, text]} accessibilityRole="header">{t('title')}</Text>
          <Text style={[styles.sub, muted]}>{t('intro')}</Text>
          <GlassCard style={styles.card}>
            <Text style={[styles.line, text]}>{t('honesty')}</Text>
          </GlassCard>
          {content}
        </ScrollView>
      </SafeAreaView>

      <ConfirmDialog visible={dialog === 'replace'} destructive title={t('replaceTitle')}
        message={t('replaceBody')}
        details={confirmed ? [`${t('replaceCurrent')}: ${confirmed.source_name || ''}`.trim()] : []}
        confirmLabel={t('replaceAction')} cancelLabel={t('cancel')}
        onConfirm={() => confirm(true)} onCancel={() => setDialog(null)} />
      <ConfirmDialog visible={dialog === 'discard'} title={t('discardTitle')} message={t('discardBody')}
        confirmLabel={t('discard')} cancelLabel={t('cancel')}
        onConfirm={() => discard('discard')} onCancel={() => setDialog(null)} />
      <ConfirmDialog visible={dialog === 'stop'} title={t('stopTitle')} message={t('stopBody')}
        confirmLabel={t('stopAction')} cancelLabel={t('cancel')}
        onConfirm={() => discard('stop')} onCancel={() => setDialog(null)} />
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', gap: spacing.md,
            paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  body: { padding: spacing.lg, paddingBottom: spacing.xl * 2 },
  title: { ...(typography?.h2 || { fontSize: 22, fontWeight: '700' }) },
  sub: { marginTop: spacing.xs, marginBottom: spacing.md },
  card: { padding: spacing.md, marginBottom: spacing.md, borderRadius: borderRadius.lg },
  spinner: { marginVertical: spacing.md },
  section: { fontWeight: '700', marginBottom: spacing.xs },
  label: { fontSize: 12, fontWeight: '700', textTransform: 'uppercase', marginBottom: spacing.xs },
  block: { marginTop: spacing.md },
  fact: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.md, paddingVertical: 2 },
  factLabel: { fontSize: 13, flexShrink: 1 },
  factValue: { fontSize: 14, fontWeight: '600', textAlign: 'right', flexShrink: 1 },
  hint: { fontSize: 12, lineHeight: 18 },
  line: { fontSize: 15, lineHeight: 21 },
  grow: { flex: 1 },
  buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.md },
  candidate: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.xs },
  chip: { paddingVertical: spacing.xs, paddingHorizontal: spacing.md, borderRadius: 999, borderWidth: 1,
          minHeight: 32, justifyContent: 'center' },
  chipText: { fontSize: 14, fontWeight: '600' },
  checkRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: spacing.md,
              minHeight: 44 },
  box: { width: 22, height: 22, borderRadius: 4, borderWidth: 1, borderColor: 'rgba(148,163,184,0.6)',
         alignItems: 'center', justifyContent: 'center' },
});
