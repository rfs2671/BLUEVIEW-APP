import React, { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Linking,
  Platform,
  Share,
  TextInput,
  Alert,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as FileSystem from 'expo-file-system/legacy';
import * as Sharing from 'expo-sharing';
import { ArrowLeft, FileText, Download, Check, Share2, ExternalLink, Mail, Plus, Trash2 } from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import { useToast } from '../../../src/components/Toast';
import DateInput from '../../../src/components/DateInput';
import { toStoredDate } from '../../../src/utils/dateEntry';
import apiClient, { projectReportsAPI, projectsAPI, getToken } from '../../../src/utils/api';
import {
  PRESETS, KINDS, periodLabel, pdfName, settingsBody, toggled, rangeProblem, whoLine, madeLabel,
  shareText, SEND_TIMES, timeLabel, addEmail,
} from '../../../src/utils/projectReports';
import { isOfflineError } from '../../../src/utils/offlineState';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';
import HeaderBrand from '../../../src/components/HeaderBrand';

// Project → Reports: the job's progress reports (lib/progress_report.py --
// the same report the WhatsApp one is).
//   * Generate now: last 7 days, last 2 weeks, this month, last month, this
//     quarter, the whole project, or a custom range.
//   * Schedule (admins and full-access PMs): any combination of daily (the
//     daily report), weekly, bi-weekly, monthly and quarterly; to the admins
//     and PMs picked; by WhatsApp DM and / or email.
//   * Every report made -- scheduled or asked for, here or in WhatsApp --
//     with its period, when, who asked; open, download, share.
//   * The daily report's send time and the extra addresses it is emailed to
//     (admins) -- what the separate Report Settings screen used to hold.
export default function ProjectReportsScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { colors } = useTheme();
  const toast = useToast();
  const [reports, setReports] = useState(null);
  const [settings, setSettings] = useState(null);
  const [preset, setPreset] = useState(PRESETS[1].key);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [making, setMaking] = useState(false);
  const [busy, setBusy] = useState(null);
  const [saving, setSaving] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [savingDaily, setSavingDaily] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await projectReportsAPI.list(projectId);
      setReports(data.reports || []);
    } catch (e) {
      setReports([]);
      toast?.error?.('Reports', 'Could not load. Try again.');
    }
    try {
      setSettings(await projectReportsAPI.settings(projectId));
    } catch (e) {
      setSettings(null);
    }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const generate = async () => {
    let what = preset;
    if (preset === 'custom') {
      // DateInput hands up the typed text; toStoredDate makes it ISO.
      const a = toStoredDate(start);
      const b = toStoredDate(end);
      const why = rangeProblem(a, b);
      if (why) { toast?.error?.('Custom range', why); return; }
      what = { start: a, end: b };
    }
    setMaking(true);
    try {
      const made = await projectReportsAPI.create(projectId, what);
      setReports((list) => [made, ...(list || []).filter((r) => r.id !== made.id)]);
      toast?.success?.('Report ready', made.period || periodLabel(made.start, made.end));
    } catch (e) {
      toast?.error?.('No report', 'Could not make the report. Try again.');
    } finally {
      setMaking(false);
    }
  };

  // The PDF as a local file (native): the no-login link when it still works,
  // else the app's own download with the token in the header -- never in a
  // URL handed to anything else.
  const localPdf = async (r) => {
    const target = `${FileSystem.cacheDirectory}${pdfName(r)}`;
    if (r.link) {
      const { uri, status } = await FileSystem.downloadAsync(r.link, target);
      if (status === 200) return uri;
    }
    const token = await getToken();
    const base = apiClient.defaults.baseURL || '';
    const { uri, status } = await FileSystem.downloadAsync(
      `${base}/api/project-reports/${encodeURIComponent(r.id)}/pdf`, target,
      { headers: { Authorization: `Bearer ${token}` } });
    return status === 200 ? uri : null;
  };

  const webBlobUrl = async (r) => window.URL.createObjectURL(await projectReportsAPI.pdf(r.id));

  const open = async (r) => {
    setBusy(`open-${r.id}`);
    try {
      if (Platform.OS === 'web') {
        window.open(r.link || await webBlobUrl(r), '_blank');
      } else if (r.link) {
        await Linking.openURL(r.link);
      } else {
        const uri = await localPdf(r);
        if (uri && await Sharing.isAvailableAsync()) {
          await Sharing.shareAsync(uri, { mimeType: 'application/pdf', UTI: 'com.adobe.pdf' });
        } else {
          toast?.error?.('Not opened', 'Try again.');
        }
      }
    } catch (e) {
      toast?.error?.('Not opened', 'Try again.');
    } finally {
      setBusy(null);
    }
  };

  const download = async (r) => {
    setBusy(`dl-${r.id}`);
    try {
      if (Platform.OS === 'web') {
        const url = await webBlobUrl(r);
        const a = window.document.createElement('a');
        a.href = url;
        a.download = pdfName(r);
        a.click();
        window.URL.revokeObjectURL(url);
      } else {
        const uri = await localPdf(r);
        if (!uri) throw new Error('no file');
        if (await Sharing.isAvailableAsync()) {
          await Sharing.shareAsync(uri, { mimeType: 'application/pdf', UTI: 'com.adobe.pdf',
            dialogTitle: 'Save report' });
        } else {
          await Linking.openURL(uri);
        }
      }
    } catch (e) {
      toast?.error?.('Not downloaded', 'Try again.');
    } finally {
      setBusy(null);
    }
  };

  const share = async (r) => {
    setBusy(`share-${r.id}`);
    try {
      if (Platform.OS === 'web') {
        if (r.link && window.navigator?.share) {
          await window.navigator.share({ title: r.title || 'Progress report', url: r.link });
        } else if (r.link && window.navigator?.clipboard) {
          await window.navigator.clipboard.writeText(r.link);
          toast?.success?.('Link copied', 'The link works for 30 days, no login.');
        } else {
          toast?.error?.('No link', 'Download the PDF to share it.');
        }
      } else if (await Sharing.isAvailableAsync()) {
        const uri = await localPdf(r);
        if (!uri) throw new Error('no file');
        await Sharing.shareAsync(uri, { mimeType: 'application/pdf', UTI: 'com.adobe.pdf',
          dialogTitle: 'Share report' });
      } else if (shareText(r)) {
        await Share.share({ title: r.title || 'Progress report', message: shareText(r) });
      } else {
        toast?.error?.('Not shared', 'Try again.');
      }
    } catch (e) {
      toast?.error?.('Not shared', 'Try again.');
    } finally {
      setBusy(null);
    }
  };

  const save = async (next) => {
    const body = settingsBody(next.schedules, next.recipient_ids, next.delivery);
    setSaving(true);
    setSettings((s) => ({ ...(s || {}), ...body }));
    try {
      setSettings(await projectReportsAPI.saveSettings(projectId, body));
    } catch (e) {
      toast?.error?.('Not saved', 'Try again.');
      load();
    } finally {
      setSaving(false);
    }
  };

  // The daily report's send time and addresses (PUT /report-settings). Saved
  // on each change, like the rest of this card; nothing is queued offline.
  const saveDaily = async (patch) => {
    const daily = { ...((settings || {}).daily || {}), ...patch };
    setSavingDaily(true);
    setSettings((s) => ({ ...(s || {}), daily: { ...daily, email_list: (daily.emails || []).length } }));
    try {
      const out = await projectsAPI.updateReportSettings(projectId, {
        report_email_list: daily.emails || [], report_send_time: daily.send_time,
      });
      const emails = out.report_email_list || [];
      setSettings((s) => ({ ...(s || {}),
        daily: { ...daily, send_time: out.report_send_time, emails, email_list: emails.length } }));
    } catch (e) {
      toast?.error?.('Not saved', isOfflineError(e)
        ? 'You are offline. Nothing was saved — reconnect and try again.' : 'Try again.');
      load();
    } finally {
      setSavingDaily(false);
    }
  };

  const addDailyEmail = () => {
    const r = addEmail(((settings || {}).daily || {}).emails, newEmail);
    if (r.error) { toast?.error?.('Email', r.error); return; }
    setNewEmail('');
    saveDaily({ emails: r.list });
  };

  const removeDailyEmail = (email) => {
    const drop = () => saveDaily({
      emails: (((settings || {}).daily || {}).emails || []).filter((e) => e !== email) });
    if (Platform.OS === 'web') {
      if (window.confirm(`Remove ${email}?`)) drop();
    } else {
      Alert.alert('Remove email', `Remove ${email} from the daily report?`, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Remove', style: 'destructive', onPress: drop },
      ]);
    }
  };

  const text = { color: colors.text.primary };
  const muted = { color: colors.text.muted };
  const chosen = { borderColor: colors.primary };
  const canEdit = !!(settings && settings.can_edit);
  const cur = settings || {};

  const box = (on, label, onPress, key, hint) => (
    <Pressable key={key} onPress={onPress} disabled={!canEdit || saving}
      accessibilityRole="checkbox" accessibilityState={{ checked: on, disabled: !canEdit }}
      style={styles.pmRow}>
      <View style={[styles.box, on && chosen]}>{on ? <Check size={14} color={text.color} /> : null}</View>
      <View style={styles.grow}>
        <Text style={[styles.line, text]}>{label}</Text>
        {hint ? <Text style={[styles.hint, muted]}>{hint}</Text> : null}
      </View>
    </Pressable>
  );

  const act = (r, kind, Icon, label, fn) => (
    <Pressable key={kind} onPress={() => fn(r)} hitSlop={8} disabled={busy === `${kind}-${r.id}`}
      accessibilityRole="button" accessibilityLabel={label} style={styles.act}>
      {busy === `${kind}-${r.id}`
        ? <ActivityIndicator size="small" />
        : <Icon size={16} color={text.color} />}
      <Text style={[styles.actText, text]}>{label}</Text>
    </Pressable>
  );

  return (
    <View style={styles.flex}>
      <AnimatedBackground />
      <SafeAreaView style={styles.flex} edges={['top']}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={12} accessibilityLabel="Back">
            <ArrowLeft size={22} color={text.color} />
          </Pressable>
          <HeaderBrand />
        </View>
        <ScrollView contentContainerStyle={styles.body}>
          <Text style={[styles.title, text]}>Reports</Text>
          <Text style={[styles.sub, muted]}>
            A progress report of the job for a period — work by sub, actual work from the daily logs,
            photos, site activity, DOB/DOT, open items, what's next — the same report sent in WhatsApp.
          </Text>

          <GlassCard style={styles.card}>
            <Text style={[styles.section, text]}>Generate now</Text>
            <View style={styles.chips}>
              {PRESETS.map((c) => (
                <Pressable key={c.key} onPress={() => setPreset(c.key)}
                  accessibilityRole="radio" accessibilityState={{ selected: preset === c.key }}
                  style={[styles.chip, preset === c.key && chosen]}>
                  <Text style={[styles.chipText, text]}>{c.label}</Text>
                </Pressable>
              ))}
            </View>
            {preset === 'custom' && (
              <View style={[styles.chips, styles.gap]}>
                <DateInput value={start} onChange={setStart} placeholderTextColor={muted.color}
                  palette={{ error: colors.status.error, hint: colors.text.muted }}
                  style={styles.dateField} accessibilityLabel="From date"
                  fieldStyle={[styles.input, text, { borderColor: colors.glass.border }]} />
                <DateInput value={end} onChange={setEnd} placeholderTextColor={muted.color}
                  palette={{ error: colors.status.error, hint: colors.text.muted }}
                  style={styles.dateField} accessibilityLabel="To date"
                  fieldStyle={[styles.input, text, { borderColor: colors.glass.border }]} />
              </View>
            )}
            <View style={styles.buttons}>
              <GlassButton title={making ? 'Making…' : 'Generate'} onPress={generate} disabled={making} />
            </View>
          </GlassCard>

          {settings && (
            <GlassCard style={styles.card}>
              <Text style={[styles.section, text]}>Send automatically</Text>
              <Text style={[styles.line, muted]}>{cur.summary}</Text>
              {!canEdit && <Text style={[styles.hint, muted]}>An admin sets this.</Text>}
              <Text style={[styles.label, muted]}>Reports</Text>
              {KINDS.map((k) => box((cur.schedules || []).includes(k.key), k.label,
                () => save({ ...cur, schedules: toggled(cur.schedules, k.key) }), `k-${k.key}`,
                k.key === 'daily' && cur.daily
                  ? `${k.hint} (${timeLabel(cur.daily.send_time)} ET`
                    + (cur.daily.email_list
                      ? `; also emailed to ${cur.daily.email_list} address`
                        + `${cur.daily.email_list === 1 ? '' : 'es'})` : ')')
                  : k.hint))}
              {canEdit && cur.daily && Array.isArray(cur.daily.emails) && (
                <View style={styles.daily}>
                  <Text style={[styles.label, muted]}>Daily report — time (New York)</Text>
                  <View style={styles.chips}>
                    {SEND_TIMES.map((t) => (
                      <Pressable key={t} onPress={() => saveDaily({ send_time: t })}
                        disabled={savingDaily} accessibilityRole="radio"
                        accessibilityState={{ selected: cur.daily.send_time === t }}
                        style={[styles.chip, cur.daily.send_time === t && chosen]}>
                        <Text style={[styles.chipText, text]}>{timeLabel(t)}</Text>
                      </Pressable>
                    ))}
                  </View>
                  <Text style={[styles.label, muted]}>Daily report — also email to</Text>
                  {cur.daily.emails.length === 0 && (
                    <Text style={[styles.hint, muted]}>No extra addresses.</Text>
                  )}
                  {cur.daily.emails.map((email) => (
                    <View key={email} style={styles.pmRow}>
                      <Mail size={16} color={muted.color} />
                      <Text style={[styles.line, text, styles.grow]}>{email}</Text>
                      <Pressable onPress={() => removeDailyEmail(email)} disabled={savingDaily}
                        hitSlop={8} accessibilityRole="button" accessibilityLabel={`Remove ${email}`}>
                        <Trash2 size={16} color={colors.status.error} />
                      </Pressable>
                    </View>
                  ))}
                  <View style={[styles.chips, styles.gap]}>
                    <TextInput value={newEmail} onChangeText={setNewEmail}
                      placeholder="email@example.com" placeholderTextColor={muted.color}
                      keyboardType="email-address" autoCapitalize="none" autoCorrect={false}
                      onSubmitEditing={addDailyEmail} editable={!savingDaily}
                      accessibilityLabel="Email address for the daily report"
                      style={[styles.input, styles.grow, text, { borderColor: colors.glass.border }]} />
                    <Pressable onPress={addDailyEmail} disabled={savingDaily} hitSlop={8}
                      accessibilityRole="button" accessibilityLabel="Add email" style={styles.act}>
                      <Plus size={16} color={text.color} />
                      <Text style={[styles.actText, text]}>Add</Text>
                    </Pressable>
                  </View>
                </View>
              )}
              <Text style={[styles.label, muted]}>Send to</Text>
              {(cur.people || []).length === 0 && (
                <Text style={[styles.line, muted]}>No admins or PMs on this job.</Text>
              )}
              {(cur.people || []).map((p) => box((cur.recipient_ids || []).includes(p.id),
                `${p.name || 'Someone'} · ${p.role === 'admin' ? 'Admin' : 'PM'}`,
                () => save({ ...cur, recipient_ids: toggled(cur.recipient_ids, p.id) }), `p-${p.id}`,
                [!p.whatsapp && 'no WhatsApp', !p.email && 'no email'].filter(Boolean).join(' · ')))}
              <Text style={[styles.label, muted]}>How</Text>
              {box(!!(cur.delivery || {}).whatsapp, 'WhatsApp (the PDF in a DM)',
                () => save({ ...cur, delivery: { ...cur.delivery, whatsapp: !(cur.delivery || {}).whatsapp } }),
                'd-wa')}
              {box(!!(cur.delivery || {}).email, 'Email (the PDF attached)',
                () => save({ ...cur, delivery: { ...cur.delivery, email: !(cur.delivery || {}).email } }),
                'd-email')}
            </GlassCard>
          )}

          <Text style={[styles.section, text, styles.gap]}>Reports</Text>
          {reports === null && <ActivityIndicator style={styles.spinner} />}
          {reports !== null && reports.length === 0 && (
            <GlassCard style={styles.card}>
              <Text style={[styles.line, muted]}>No reports yet.</Text>
            </GlassCard>
          )}
          {(reports || []).map((r) => (
            <GlassCard key={r.id} style={styles.card}>
              <View style={styles.rowHead}>
                <FileText size={16} color={muted.color} />
                <Text style={[styles.line, text, styles.grow]}>
                  {r.period || periodLabel(r.start, r.end) || r.title}
                </Text>
              </View>
              <Text style={[styles.meta, muted]}>
                {[whoLine(r), madeLabel(r.created_at)].filter(Boolean).join(' · ')}
              </Text>
              {(r.summary || []).map((s, i) => (
                <Text key={i} style={[styles.summary, text]}>{s}</Text>
              ))}
              {(r.has_pdf || r.link) ? (
                <View style={styles.acts}>
                  {act(r, 'open', ExternalLink, 'Open', open)}
                  {act(r, 'dl', Download, 'Download', download)}
                  {act(r, 'share', Share2, 'Share', share)}
                </View>
              ) : <Text style={[styles.hint, muted]}>No PDF — it could not be made.</Text>}
            </GlassCard>
          ))}
        </ScrollView>
      </SafeAreaView>
    </View>
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
  section: { fontWeight: '700', marginBottom: spacing.sm },
  label: { fontSize: 12, fontWeight: '700', textTransform: 'uppercase', marginTop: spacing.md,
           marginBottom: spacing.xs },
  gap: { marginTop: spacing.sm },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  chip: { paddingVertical: spacing.xs, paddingHorizontal: spacing.md, borderRadius: 999,
          borderWidth: 1, borderColor: 'rgba(148,163,184,0.4)' },
  chipText: { fontSize: 14, fontWeight: '600' },
  dateField: { flex: 1, minWidth: 140 },
  input: { minWidth: 140, borderWidth: 1, borderRadius: borderRadius.md,
           paddingHorizontal: spacing.sm, paddingVertical: 6 },
  hint: { fontSize: 12 },
  buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.md },
  pmRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.xs },
  box: { width: 20, height: 20, borderRadius: 4, borderWidth: 1, borderColor: 'rgba(148,163,184,0.6)',
         alignItems: 'center', justifyContent: 'center' },
  daily: { marginTop: spacing.xs },
  rowHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  grow: { flex: 1 },
  line: { fontSize: 15, lineHeight: 21 },
  meta: { fontSize: 12, marginTop: 2, marginBottom: spacing.xs },
  summary: { fontSize: 13, lineHeight: 19 },
  acts: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md, marginTop: spacing.sm },
  act: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 4 },
  actText: { fontSize: 14, fontWeight: '600' },
});
