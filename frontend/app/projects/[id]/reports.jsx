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
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft, FileText, Download, Check } from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import { useToast } from '../../../src/components/Toast';
import { projectReportsAPI } from '../../../src/utils/api';
import {
  RANGE_CHOICES, SCHEDULE_OPTIONS, periodLabel, sourceLabel, pdfName, scheduleBody, scheduleLabel,
} from '../../../src/utils/projectReports';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';
import { useAuth, isCompanyAdmin } from '../../../src/context/AuthContext';
import HeaderBrand from '../../../src/components/HeaderBrand';

// Project → Reports: generate a PDF report for a period, list the ones made
// (in the app, asked for in WhatsApp, or sent on the schedule), download them.
// Admins set the schedule here: off / every 2 weeks / monthly, sent by
// WhatsApp to the company's admins and the PMs chosen below.
export default function ProjectReportsScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { colors } = useTheme();
  const { user } = useAuth();
  const toast = useToast();
  const isAdmin = isCompanyAdmin(user);
  const [reports, setReports] = useState(null);
  const [settings, setSettings] = useState(null);     // { schedule, pm_ids, pms }
  const [range, setRange] = useState(RANGE_CHOICES[0].key);
  const [making, setMaking] = useState(false);
  const [downloading, setDownloading] = useState(null);
  const [saving, setSaving] = useState(false);

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
    setMaking(true);
    try {
      const made = await projectReportsAPI.create(projectId, range);
      setReports((list) => [made, ...(list || []).filter((r) => r.id !== made.id)]);
      toast?.success?.('Report ready', periodLabel(made.start, made.end));
    } catch (e) {
      toast?.error?.('No report', 'Could not make the report. Try again.');
    } finally {
      setMaking(false);
    }
  };

  const download = async (r) => {
    if (Platform.OS !== 'web') {
      // The 30-day no-login link opens in the phone's PDF viewer.
      if (r.link) {
        Linking.openURL(r.link);
      } else {
        toast?.error?.('Link expired', 'Generate the report again for a new link.');
      }
      return;
    }
    setDownloading(r.id);
    try {
      const blob = await projectReportsAPI.pdf(r.id);
      const url = window.URL.createObjectURL(blob);
      const a = window.document.createElement('a');
      a.href = url;
      a.download = pdfName(r);
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      toast?.error?.('Not downloaded', 'Try again.');
    } finally {
      setDownloading(null);
    }
  };

  const saveSchedule = async (next) => {
    const body = scheduleBody(next.schedule, next.pm_ids);
    setSaving(true);
    try {
      const saved = await projectReportsAPI.saveSettings(projectId, body);
      setSettings((s) => ({ ...(s || {}), ...saved }));
    } catch (e) {
      toast?.error?.('Not saved', 'Try again.');
    } finally {
      setSaving(false);
    }
  };

  const togglePm = (id) => {
    const cur = new Set((settings?.pm_ids) || []);
    if (cur.has(id)) cur.delete(id); else cur.add(id);
    saveSchedule({ schedule: settings?.schedule, pm_ids: Array.from(cur) });
  };

  const text = { color: colors.text.primary };
  const muted = { color: colors.text.muted };
  const chosen = { borderColor: colors.primary };

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
            A PDF of the job for a period: manpower, subs, DOB/DOT, upcoming, commitments, punch,
            daily logs and safety. Every number comes from Levelog's records.
          </Text>

          <GlassCard style={styles.card}>
            <Text style={[styles.section, text]}>New report</Text>
            <View style={styles.chips}>
              {RANGE_CHOICES.map((c) => (
                <Pressable key={c.key} onPress={() => setRange(c.key)}
                  accessibilityRole="radio" accessibilityState={{ selected: range === c.key }}
                  style={[styles.chip, range === c.key && chosen]}>
                  <Text style={[styles.chipText, text]}>{c.label}</Text>
                </Pressable>
              ))}
            </View>
            <View style={styles.buttons}>
              <GlassButton title={making ? 'Making…' : 'Generate'} onPress={generate} disabled={making} />
            </View>
          </GlassCard>

          {settings && (
            <GlassCard style={styles.card}>
              <Text style={[styles.section, text]}>Send automatically</Text>
              {isAdmin ? (
                <>
                  <View style={styles.chips}>
                    {SCHEDULE_OPTIONS.map((o) => (
                      <Pressable key={o.key} disabled={saving}
                        onPress={() => saveSchedule({ schedule: o.key, pm_ids: settings.pm_ids })}
                        accessibilityRole="radio" accessibilityState={{ selected: settings.schedule === o.key }}
                        style={[styles.chip, settings.schedule === o.key && chosen]}>
                        <Text style={[styles.chipText, text]}>{o.label}</Text>
                        {o.hint ? <Text style={[styles.hint, muted]}>{o.hint}</Text> : null}
                      </Pressable>
                    ))}
                  </View>
                  {settings.schedule !== 'off' && (
                    <>
                      <Text style={[styles.line, muted, styles.gap]}>
                        Sent by WhatsApp to the company's admins, and to these PMs:
                      </Text>
                      {(settings.pms || []).length === 0 && (
                        <Text style={[styles.line, muted]}>No PMs on this job.</Text>
                      )}
                      {(settings.pms || []).map((p) => {
                        const on = (settings.pm_ids || []).includes(p.id);
                        return (
                          <Pressable key={p.id} onPress={() => togglePm(p.id)} disabled={saving}
                            accessibilityRole="checkbox" accessibilityState={{ checked: on }}
                            style={styles.pmRow}>
                            <View style={[styles.box, on && chosen]}>
                              {on ? <Check size={14} color={text.color} /> : null}
                            </View>
                            <Text style={[styles.line, text]}>{p.name || 'PM'}</Text>
                          </Pressable>
                        );
                      })}
                    </>
                  )}
                </>
              ) : (
                <Text style={[styles.line, muted]}>
                  {scheduleLabel(settings.schedule)}. An admin sets this.
                </Text>
              )}
            </GlassCard>
          )}

          <Text style={[styles.section, text, styles.gap]}>Made</Text>
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
                <Text style={[styles.line, text, styles.grow]}>{periodLabel(r.start, r.end) || r.title}</Text>
                {(r.has_pdf || r.link) ? (
                  <Pressable onPress={() => download(r)} hitSlop={10} disabled={downloading === r.id}
                    accessibilityRole="button" accessibilityLabel="Download PDF">
                    {downloading === r.id
                      ? <ActivityIndicator size="small" />
                      : <Download size={18} color={text.color} />}
                  </Pressable>
                ) : null}
              </View>
              <Text style={[styles.meta, muted]}>{sourceLabel(r.source)}</Text>
              {(r.summary || []).map((s, i) => (
                <Text key={i} style={[styles.summary, text]}>{s}</Text>
              ))}
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
  gap: { marginTop: spacing.sm },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  chip: { paddingVertical: spacing.xs, paddingHorizontal: spacing.md, borderRadius: 999,
          borderWidth: 1, borderColor: 'rgba(148,163,184,0.4)' },
  chipText: { fontSize: 14, fontWeight: '600' },
  hint: { fontSize: 11 },
  buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.md },
  pmRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.xs },
  box: { width: 20, height: 20, borderRadius: 4, borderWidth: 1, borderColor: 'rgba(148,163,184,0.6)',
         alignItems: 'center', justifyContent: 'center' },
  rowHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  grow: { flex: 1 },
  line: { fontSize: 15, lineHeight: 21 },
  meta: { fontSize: 12, marginTop: 2, marginBottom: spacing.xs },
  summary: { fontSize: 13, lineHeight: 19 },
});
