import React, { useState } from 'react';
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
import { ArrowLeft, Search, MessageCircle, FileText, X } from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import { useToast } from '../../../src/components/Toast';
import { memoryAPI } from '../../../src/utils/api';
import {
  cleanQuery, chipText, preview, opensContext, answerState, claimLine, claimSources,
} from '../../../src/utils/projectMemory';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';
import HeaderBrand from '../../../src/components/HeaderBrand';

// Project → Search: the project's WhatsApp messages and filed daily reports.
// Every result carries its source (who · group · when); tap one to see it
// in place (the two messages before and after it). "Answer" asks for a cited
// answer: every quote in it was checked against these sources, or it says it
// cannot find it. Nothing here posts anywhere.
export default function ProjectSearchScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { colors } = useTheme();
  const toast = useToast();
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState(null);
  const [answer, setAnswer] = useState(null);
  const [context, setContext] = useState(null);

  const run = async (withAnswer) => {
    const { query, error } = cleanQuery(q);
    if (error) {
      toast?.error?.('Search', error);
      return;
    }
    setBusy(true);
    // A new search clears the last one's results first: if this request
    // fails, nothing from another query may look like its answer.
    setContext(null);
    setResults(null);
    setAnswer(null);
    try {
      const data = await memoryAPI.search(projectId, query, { answer: withAnswer });
      setResults(data.results || []);
      setAnswer(withAnswer ? answerState(data.answer) : null);
    } catch (e) {
      toast?.error?.('Search failed', 'Try again.');
    } finally {
      setBusy(false);
    }
  };

  const open = async (r) => {
    if (!opensContext(r)) return;
    try {
      setContext({ loading: true, id: r.id });
      setContext({ ...(await memoryAPI.context(projectId, r.id)), id: r.id });
    } catch (e) {
      setContext(null);
      toast?.error?.('Not found', 'That message is no longer kept.');
    }
  };

  const text = { color: colors.text.primary };
  const muted = { color: colors.text.muted };

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
        <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
          <Text style={[styles.title, text]}>Search this project</Text>
          <Text style={[styles.sub, muted]}>
            WhatsApp group messages and daily reports. Every result shows its source.
          </Text>
          <GlassCard style={styles.card}>
            <View style={styles.inputRow}>
              <Search size={18} color={muted.color} />
              <TextInput
                value={q}
                onChangeText={setQ}
                onSubmitEditing={() => run(false)}
                placeholder="who said to change the window?"
                placeholderTextColor={muted.color}
                returnKeyType="search"
                style={[styles.input, text]}
                accessibilityLabel="Search query"
              />
            </View>
            <View style={styles.buttons}>
              <GlassButton title="Search" onPress={() => run(false)} disabled={busy} />
              <GlassButton title="Answer" onPress={() => run(true)} disabled={busy} />
            </View>
          </GlassCard>

          {busy && <ActivityIndicator style={styles.spinner} />}

          {answer && (
            <GlassCard style={styles.card}>
              <Text style={[styles.section, text]}>
                {answer.found ? (answer.timeline ? 'What happened' : 'Answer') : 'Answer'}
              </Text>
              {!answer.found && <Text style={[styles.line, muted]}>{answer.text}</Text>}
              {answer.found && !!answer.lead && (
                <Text style={[styles.line, styles.lead, text]}>{answer.lead}</Text>
              )}
              {answer.found && answer.claims.map((c, i) => (
                <View key={i} style={styles.claim}>
                  <Text style={[styles.line, text]}>{claimLine(c, answer.timeline)}</Text>
                  {claimSources(c).map((s, j) => (
                    <Pressable key={`${i}-${j}`} onPress={() => open(s)}>
                      <Text style={[styles.quote, muted]}>“{s.quote}”</Text>
                      <Text style={[styles.chip, muted]}>{chipText(s)}</Text>
                    </Pressable>
                  ))}
                </View>
              ))}
            </GlassCard>
          )}

          {context && (
            <GlassCard style={styles.card}>
              <View style={styles.ctxHead}>
                <Text style={[styles.section, text]}>
                  {context.kind === 'daily_report' ? `Daily report · ${context.day || ''}` : context.group || 'In context'}
                </Text>
                <Pressable onPress={() => setContext(null)} hitSlop={12} accessibilityLabel="Close">
                  <X size={18} color={muted.color} />
                </Pressable>
              </View>
              {context.loading && <ActivityIndicator />}
              {(context.messages || context.entries || []).map((m) => (
                <View key={m.id} style={[styles.ctxRow, m.hit && styles.hit]}>
                  <Text style={[styles.chip, muted]}>{chipText(m)}</Text>
                  <Text style={[styles.line, text]}>{m.text}</Text>
                </View>
              ))}
            </GlassCard>
          )}

          {results && !busy && (
            <GlassCard style={styles.card}>
              <Text style={[styles.section, text]}>
                {results.length ? `${results.length} results` : 'Nothing found'}
              </Text>
              {results.map((r) => (
                <Pressable key={r.id} onPress={() => open(r)} style={styles.result}
                           accessibilityRole="button">
                  <View style={styles.resultHead}>
                    {r.source === 'daily_report'
                      ? <FileText size={14} color={muted.color} />
                      : <MessageCircle size={14} color={muted.color} />}
                    <Text style={[styles.chip, muted]}>{chipText(r)}</Text>
                  </View>
                  <Text style={[styles.line, text]}>{preview(r.text)}</Text>
                </Pressable>
              ))}
            </GlassCard>
          )}
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
  inputRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  input: { flex: 1, paddingVertical: spacing.sm, fontSize: 16 },
  buttons: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  spinner: { marginVertical: spacing.md },
  section: { fontWeight: '700', marginBottom: spacing.sm },
  claim: { marginBottom: spacing.md },
  lead: { fontWeight: '600', marginBottom: spacing.sm },
  line: { fontSize: 15, lineHeight: 21 },
  quote: { fontStyle: 'italic', marginTop: 2 },
  chip: { fontSize: 12, marginTop: 2 },
  result: { paddingVertical: spacing.sm },
  resultHead: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  ctxHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  ctxRow: { paddingVertical: spacing.xs, paddingHorizontal: spacing.xs, borderRadius: 8 },
  hit: { backgroundColor: 'rgba(99,102,241,0.12)' },
});
