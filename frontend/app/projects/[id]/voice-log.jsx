import React, { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
  Linking,
  Image,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft } from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import { useToast } from '../../../src/components/Toast';
import { whatsappAPI } from '../../../src/utils/api';
import { quoteText } from '../../../src/utils/sourceMessage';
import { PLAY_LABEL, NO_AUDIO_TEXT } from '../../../src/utils/whatsappAttention';
import {
  VOICE_LOG_TITLE, VOICE_LOG_NOTE, STATUS_LABELS, STATUS_FILTERS, langLabel, whenLabel,
  headLine, statusLine, producedLines, producedRoute, emptyText, LOAD_MORE, appendPage,
  MEDIA_FILTERS, MEDIA_LABELS, isPhoto, photoHead, photoLines,
} from '../../../src/utils/voiceLog';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';
import HeaderBrand from '../../../src/components/HeaderBrand';

// Project → WhatsApp → Voice & media log (admins): every voice note of the
// job -- when, who, where (group / DM), language and confidence, what was
// said and its English, ▶ Play when the audio is kept, its status, and what
// it produced (an Attention item, an Upcoming event, or nothing) -- and every
// photo posted in its groups: who sent it, their company, the caption and
// what it shows.
export default function VoiceLogScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { colors } = useTheme();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [sender, setSender] = useState('');
  const [lang, setLang] = useState('');
  const [status, setStatus] = useState('');
  const [media, setMedia] = useState('');
  const [busy, setBusy] = useState(null);

  const filters = { sender: sender.trim(), lang, status, media };
  const load = useCallback(async () => {
    try {
      setData(await whatsappAPI.getVoiceLog(projectId, filters));
    } catch (e) {
      setData({ notes: [], facets: {}, error: true });
      toast?.error?.(VOICE_LOG_TITLE, 'Could not load. Try again.');
    }
  }, [projectId, sender, lang, status, media]);

  // The next page: filters keep running past what was read.
  const loadMore = async () => {
    if (!data || !data.next_before) return;
    setBusy('more');
    try {
      const page = await whatsappAPI.getVoiceLog(projectId, filters, data.next_before);
      setData({ ...page, notes: appendPage(data.notes, page),
                facets: (data && data.facets) || page.facets });
    } catch (e) {
      toast?.error?.(VOICE_LOG_TITLE, 'Could not load more. Try again.');
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => { load(); }, [lang, status, media]);   // the name filters on Search

  const play = async (n) => {
    setBusy(n.id);
    try {
      const src = await whatsappAPI.getSource(projectId, n.message_row_id);
      const url = src && src.voice && src.voice.audio_url;
      if (url) await Linking.openURL(url);
      else toast?.error?.('No audio', NO_AUDIO_TEXT);
    } catch (e) {
      toast?.error?.('Not played', 'The audio could not be opened. Try again.');
    } finally {
      setBusy(null);
    }
  };

  const text = { color: colors.text.primary };
  const muted = { color: colors.text.muted };
  const notes = (data && data.notes) || [];
  const langs = ['', ...(((data && data.facets) || {}).langs || [])];

  const chip = (label, on, onPress, key) => (
    <Pressable key={key} onPress={onPress} accessibilityRole="button"
      style={[styles.chipBtn, { borderColor: colors.glass.border },
        on && { backgroundColor: colors.glass.border }]}>
      <Text style={[styles.chipText, text]}>{label}</Text>
    </Pressable>
  );

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.flex} edges={['top']}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={12} accessibilityLabel="Back">
            <ArrowLeft size={22} color={text.color} />
          </Pressable>
          <HeaderBrand />
        </View>
        <ScrollView contentContainerStyle={styles.body}>
          <Text style={[styles.title, text]}>{VOICE_LOG_TITLE}</Text>
          <Text style={[styles.sub, muted]}>{VOICE_LOG_NOTE}</Text>

          <GlassCard style={styles.card}>
            <View style={styles.row}>
              <TextInput
                value={sender}
                onChangeText={setSender}
                onSubmitEditing={load}
                placeholder="Sender name"
                placeholderTextColor={muted.color}
                style={[styles.input, text, { borderColor: colors.glass.border }]}
                accessibilityLabel="Filter by sender"
                returnKeyType="search"
              />
              {chip('Search', false, load, 'search')}
            </View>
            <View style={styles.row}>
              {MEDIA_FILTERS.map((m) => chip(MEDIA_LABELS[m], media === m,
                () => setMedia(m), `media-${m || 'all'}`))}
            </View>
            <View style={styles.row}>
              {STATUS_FILTERS.map((st) => chip(st ? STATUS_LABELS[st] : 'All',
                status === st, () => setStatus(st), `st-${st || 'all'}`))}
            </View>
            <View style={styles.row}>
              {langs.map((l) => chip(l ? langLabel(l) : 'Any language', lang === l,
                () => setLang(l), `lang-${l || 'any'}`))}
            </View>
          </GlassCard>

          {data === null && <ActivityIndicator style={styles.spinner} />}
          {data !== null && notes.length === 0 && (
            <GlassCard style={styles.card}>
              <Text style={[styles.line, muted]}>
                {data.next_before ? 'Nothing yet in what was read.' : emptyText(!!(sender.trim() || lang || status || media))}
              </Text>
            </GlassCard>
          )}

          {notes.map((n) => (isPhoto(n) ? (
            <GlassCard key={`photo-${n.id}`} style={styles.card}>
              <Text style={[styles.when, text]}>{whenLabel(n.at)}</Text>
              <Text style={[styles.line, muted]}>{photoHead(n)}</Text>
              {n.photo_url ? (
                <Pressable onPress={() => Linking.openURL(n.photo_url)} accessibilityRole="imagebutton"
                  accessibilityLabel="Open the photo">
                  <Image source={{ uri: n.photo_url }} style={styles.photo} resizeMode="cover" />
                </Pressable>
              ) : null}
              {photoLines(n).map((l) => (
                <Text key={l.key} style={[l.quote ? styles.quote : styles.line, l.quote ? text : muted]}>
                  {l.quote ? quoteText(l.text, false) : l.text}
                </Text>
              ))}
            </GlassCard>
          ) : (
            <GlassCard key={`${n.where}-${n.id}`} style={styles.card}>
              <Text style={[styles.when, text]}>{whenLabel(n.at)}</Text>
              <Text style={[styles.line, muted]}>{headLine(n)}</Text>
              {n.transcript ? (
                <Text style={[styles.quote, text]}>{quoteText(n.transcript, true)}</Text>
              ) : null}
              {n.english ? <Text style={[styles.line, muted]}>{`English: ${n.english}`}</Text> : null}
              <Text style={[styles.line, muted]}>{statusLine(n)}</Text>
              {producedLines(n).map((p) => (
                <Pressable key={p.key} disabled={!producedRoute(projectId, p)}
                  onPress={() => router.push(producedRoute(projectId, p))}
                  accessibilityRole={producedRoute(projectId, p) ? 'link' : undefined}>
                  <Text style={[styles.line, producedRoute(projectId, p) ? text : muted]}>
                    {p.text}
                  </Text>
                </Pressable>
              ))}
              {n.audio && n.message_row_id ? (
                busy === n.id
                  ? <ActivityIndicator size="small" color={muted.color} style={styles.spinner} />
                  : chip(PLAY_LABEL, false, () => play(n), `play-${n.id}`)
              ) : null}
            </GlassCard>
          )))}

          {data && data.next_before ? (
            busy === 'more'
              ? <ActivityIndicator style={styles.spinner} />
              : chip(LOAD_MORE, false, loadMore, 'more')
          ) : null}
        </ScrollView>
      </SafeAreaView>
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
  spinner: { marginVertical: spacing.sm },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginBottom: spacing.xs,
         alignItems: 'center' },
  input: { flex: 1, minWidth: 140, borderWidth: 1, borderRadius: borderRadius.md,
           paddingHorizontal: spacing.sm, paddingVertical: 6 },
  chipBtn: { borderWidth: 1, borderRadius: borderRadius.md, paddingHorizontal: spacing.sm,
             paddingVertical: 6, alignSelf: 'flex-start' },
  chipText: { fontSize: 13 },
  when: { fontWeight: '700' },
  line: { fontSize: 13, marginTop: 4 },
  quote: { fontSize: 15, marginTop: 4 },
  photo: { width: '100%', aspectRatio: 4 / 3, borderRadius: borderRadius.md, marginTop: spacing.xs },
});
