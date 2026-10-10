import React, { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft, CalendarClock, X, Pencil } from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import { useToast } from '../../../src/components/Toast';
import { upcomingAPI } from '../../../src/utils/api';
import {
  byDay, eventLine, evidenceLine, movedLine, cleanEdit,
} from '../../../src/utils/upcoming';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';
import HeaderBrand from '../../../src/components/HeaderBrand';
import DateInput from '../../../src/components/DateInput';

// Project → Upcoming: hearings and permit expirations from the city's
// records, and the dated events said in the job's WhatsApp group ("from
// chat", with the words they came from; one tap to dismiss, or correct the
// day). Nothing here posts anywhere. The person's private calendar feed is
// in Integrations → WhatsApp → Personal assistant (CalendarFeedCard).
export default function ProjectUpcomingScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { colors } = useTheme();
  const toast = useToast();
  const [events, setEvents] = useState(null);
  const [editing, setEditing] = useState(null);   // { id, date, time }
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await upcomingAPI.list(projectId);
      setEvents(data.events || []);
    } catch (e) {
      setEvents([]);
      toast?.error?.('Upcoming', 'Could not load. Try again.');
    }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const dismiss = async (e) => {
    setBusy(e.id);
    try {
      await upcomingAPI.dismiss(projectId, e.id);
      setEvents((list) => (list || []).filter((x) => x.id !== e.id));
    } catch (err) {
      toast?.error?.('Not dismissed', 'Try again.');
    } finally {
      setBusy(null);
    }
  };

  const saveEdit = async () => {
    const { patch, error } = cleanEdit(editing || {});
    if (error) {
      toast?.error?.('Edit', error);
      return;
    }
    setBusy(editing.id);
    try {
      const saved = await upcomingAPI.edit(projectId, editing.id, patch);
      setEvents((list) => (list || []).map((x) => (x.id === saved.id ? saved : x)));
      setEditing(null);
    } catch (err) {
      toast?.error?.('Not saved', 'Try again.');
    } finally {
      setBusy(null);
    }
  };

  const text = { color: colors.text.primary };
  const muted = { color: colors.text.muted };
  const days = byDay(events);

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
          <Text style={[styles.title, text]}>Upcoming</Text>
          <Text style={[styles.sub, muted]}>
            Hearings and permit expirations from city records, and dated events from the job's
            WhatsApp group.
          </Text>

          {events === null && <ActivityIndicator style={styles.spinner} />}
          {events !== null && days.length === 0 && (
            <GlassCard style={styles.card}>
              <Text style={[styles.line, muted]}>Nothing coming up.</Text>
            </GlassCard>
          )}

          {days.map((d) => (
            <GlassCard key={d.date} style={styles.card}>
              <Text style={[styles.section, text]}>{d.label}</Text>
              {d.events.map((e) => (
                <View key={e.id} style={styles.event}>
                  <View style={styles.eventHead}>
                    <CalendarClock size={14} color={muted.color} />
                    <Text style={[styles.line, text, styles.grow]}>{eventLine(e)}</Text>
                    {e.can_edit && (
                      <Pressable
                        onPress={() => setEditing({ id: e.id, date: e.date, time: e.time || '' })}
                        hitSlop={10}
                        accessibilityLabel="Edit"
                      >
                        <Pencil size={16} color={muted.color} />
                      </Pressable>
                    )}
                    {e.can_dismiss && (
                      <Pressable onPress={() => dismiss(e)} hitSlop={10} disabled={busy === e.id}
                                 accessibilityLabel="Dismiss">
                        <X size={18} color={muted.color} />
                      </Pressable>
                    )}
                  </View>
                  <Text style={[styles.chip, muted]}>
                    {[e.chip, e.agency, movedLine(e)].filter(Boolean).join(' · ')}
                  </Text>
                  {!!evidenceLine(e) && (
                    <Text style={[styles.quote, muted]}>{evidenceLine(e)}</Text>
                  )}
                  {!!e.detail && <Text style={[styles.chip, muted]}>{e.detail}</Text>}
                  {editing && editing.id === e.id && (
                    <View style={styles.editRow}>
                      <DateInput
                        value={editing.date}
                        onChange={(v) => setEditing({ ...editing, date: v })}
                        placeholder="MM/DD/YYYY"
                        placeholderTextColor={muted.color}
                        palette={{ error: colors.status.error, hint: colors.text.muted }}
                        fieldStyle={[styles.input, text]}
                        accessibilityLabel="Date"
                      />
                      <TextInput
                        value={editing.time}
                        onChangeText={(v) => setEditing({ ...editing, time: v })}
                        placeholder="HH:MM"
                        placeholderTextColor={muted.color}
                        style={[styles.input, text]}
                        accessibilityLabel="Time"
                      />
                      <GlassButton title="Save" onPress={saveEdit} disabled={busy === e.id} />
                      <GlassButton title="Cancel" onPress={() => setEditing(null)} />
                    </View>
                  )}
                </View>
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
  event: { marginBottom: spacing.md },
  eventHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  grow: { flex: 1 },
  line: { fontSize: 15, lineHeight: 21 },
  quote: { fontStyle: 'italic', marginTop: 2 },
  chip: { fontSize: 12, marginTop: 2 },
  editRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.sm,
             alignItems: 'center' },
  input: { minWidth: 110, paddingVertical: spacing.xs, paddingHorizontal: spacing.sm,
           borderWidth: 1, borderColor: 'rgba(148,163,184,0.4)', borderRadius: 8, fontSize: 15 },
  buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.sm },
});
