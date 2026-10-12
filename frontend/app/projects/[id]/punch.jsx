import React, { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  Image,
  ActivityIndicator,
  Modal,
  useWindowDimensions,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft, Camera, X } from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import { useToast } from '../../../src/components/Toast';
import { punchAPI } from '../../../src/utils/api';
import {
  statusLabel, floorLabel, filterChips, whereLine, whoLine, itemWords, historyLine,
  emptyText, mentionLine, statusChips, assigneeChips, itemActions, photoList,
  DUE_CHOICES, STATUS_EXPLAINER,
} from '../../../src/utils/punchList';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';
import HeaderBrand from '../../../src/components/HeaderBrand';

const when = (iso) => {
  const d = new Date(iso);
  // New York, whatever the device's zone (the server sends UTC-marked times).
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('en-US', {
    timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
};

// Project → Punch list: the items from walkthroughs on this job (each one a
// photo and the walker's words, typed or spoken), by status, assignee, floor
// and trade. Tap an item for its detail: its photos full screen, its
// history, and -- for an admin or PM, as in WhatsApp -- close, reopen,
// reassign, change the due (the chase follows).
//
// LAYOUT (live 588, Oct 12, Android production: the top half was empty and
// the header sat mid-screen): AnimatedBackground is a flex:1 container that
// holds the screen. Rendered as a sibling of the SafeAreaView it took half
// the height. Everything goes INSIDE it, as on the project screen.
export default function ProjectPunchScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { colors } = useTheme();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [filters, setFilters] = useState({ floor: '', trade: '', status: '', assignee: '' });
  const [detail, setDetail] = useState(null);     // the item shown in full

  const load = useCallback(async () => {
    try {
      setData(await punchAPI.list(projectId, filters));
    } catch (e) {
      setData({ items: [], floors: [], trades: [], statuses: [], assignees: [], error: true });
    }
  }, [projectId, filters]);

  useEffect(() => { load(); }, [load]);

  const saved = (item) => {
    setDetail(item);
    load();
  };

  const text = { color: colors.text.primary };
  const muted = { color: colors.text.muted };
  const items = (data && data.items) || [];
  const filtered = !!(filters.floor || filters.trade || filters.status || filters.assignee);

  const chipRow = (key, chips) => (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chips}>
      {chips.map((c) => (
        <Pressable
          key={c.value || 'all'}
          onPress={() => setFilters((f) => ({ ...f, [key]: c.value }))}
          style={[styles.chip, { borderColor: colors.glass.border },
                  filters[key] === c.value && { borderColor: colors.primary }]}
          accessibilityRole="button"
          accessibilityState={{ selected: filters[key] === c.value }}
        >
          <Text style={[styles.chipText, text]}>{c.label}</Text>
        </Pressable>
      ))}
    </ScrollView>
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
        <ScrollView style={styles.flex} contentContainerStyle={styles.body}>
          <Text style={[styles.title, text]}>Punch list</Text>
          <Text style={[styles.sub, muted]}>
            From walkthroughs in WhatsApp: each item is a photo and the walker's own words.
          </Text>

          {data && !data.error && (
            <>
              {chipRow('status', statusChips(data.statuses, data.counts))}
              <Text style={[styles.explain, muted]}>{STATUS_EXPLAINER}</Text>
              {data.assignees && data.assignees.length > 1
                && chipRow('assignee', assigneeChips(data.assignees))}
              {data.floors && data.floors.length > 1 && chipRow('floor', filterChips(data.floors, floorLabel))}
              {data.trades && data.trades.length > 1 && chipRow('trade', filterChips(data.trades))}
            </>
          )}

          {data === null && <ActivityIndicator style={styles.spinner} />}
          {data && data.error && (
            <Pressable onPress={load}>
              <Text style={[styles.line, muted]}>The punch list could not be loaded. Tap to try again.</Text>
            </Pressable>
          )}
          {data && !data.error && items.length === 0 && (
            <GlassCard style={styles.card}>
              <Text style={[styles.line, muted]}>{emptyText(filtered)}</Text>
            </GlassCard>
          )}

          {items.map((it) => (
            <GlassCard key={it.pid} style={styles.card}>
              <Pressable onPress={() => setDetail(it)} accessibilityRole="button"
                         accessibilityLabel={`${it.pid}, ${statusLabel(it.status)}. Open details`}>
                <View style={styles.row}>
                  <Text style={[styles.pid, text]}>{it.pid}</Text>
                  {it.has_photo && <Camera size={14} color={muted.color} />}
                  <Text style={[styles.status, muted]}>{statusLabel(it.status)}</Text>
                </View>
                <Text style={[styles.line, text]}>{itemWords(it)}</Text>
                <Text style={[styles.small, muted]}>{whereLine(it)}</Text>
                <Text style={[styles.small, muted]}>{whoLine(it)}</Text>
                {mentionLine(it) ? <Text style={[styles.small, muted]}>{mentionLine(it)}</Text> : null}
              </Pressable>
            </GlassCard>
          ))}
        </ScrollView>
      </SafeAreaView>

      {detail && (
        <PunchDetail
          projectId={projectId}
          item={detail}
          canAct={!!(data && data.can_act)}
          onClose={() => setDetail(null)}
          onSaved={saved}
          toast={toast}
        />
      )}
    </AnimatedBackground>
  );
}

// The item in full: its photos (tap one: full screen), what was said, where,
// who and when it is due, its history, and the admin / PM actions.
function PunchDetail({ projectId, item, canAct, onClose, onSaved, toast }) {
  const { colors } = useTheme();
  const { width, height } = useWindowDimensions();
  const [urls, setUrls] = useState({});            // which -> url | 'none'
  const [full, setFull] = useState(null);          // which shown full screen
  const [mode, setMode] = useState(null);          // 'reassign' | 'due'
  const [people, setPeople] = useState(null);
  const [busy, setBusy] = useState(false);
  const photos = photoList(item);
  const text = { color: colors.text.primary };
  const muted = { color: colors.text.muted };

  useEffect(() => {
    let live = true;
    photos.forEach(async (p) => {
      try {
        const { url } = await punchAPI.photo(projectId, item.pid, p.which);
        if (live) setUrls((u) => ({ ...u, [p.which]: url || 'none' }));
      } catch (e) {
        if (live) setUrls((u) => ({ ...u, [p.which]: 'none' }));
      }
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, item.pid, item.photos]);

  const act = async (patch) => {
    setBusy(true);
    try {
      onSaved(await punchAPI.edit(projectId, item.pid, patch));
      setMode(null);
    } catch (e) {
      const why = e && e.response && e.response.data && e.response.data.detail;
      toast?.error?.('Not saved', typeof why === 'string' ? why : 'Try again.');
    } finally {
      setBusy(false);
    }
  };

  const openReassign = async () => {
    setMode('reassign');
    if (!people) {
      try {
        setPeople((await punchAPI.people(projectId)).people || []);
      } catch (e) {
        setPeople([]);
      }
    }
  };

  const button = (key, label, onPress, selected) => (
    <Pressable key={key} onPress={onPress} disabled={busy}
               style={[styles.chip, { borderColor: selected ? colors.primary : colors.glass.border }]}
               accessibilityRole="button">
      <Text style={[styles.chipText, text]}>{label}</Text>
    </Pressable>
  );

  return (
    <Modal visible animationType="slide" onRequestClose={onClose}>
      <AnimatedBackground>
        <SafeAreaView style={styles.flex} edges={['top', 'bottom']}>
          <View style={styles.header}>
            <Pressable onPress={onClose} hitSlop={12} accessibilityLabel="Close details">
              <ArrowLeft size={22} color={text.color} />
            </Pressable>
            <Text style={[styles.pid, text]}>{item.pid}</Text>
            <Text style={[styles.status, muted]}>{statusLabel(item.status)}</Text>
          </View>
          <ScrollView style={styles.flex} contentContainerStyle={styles.body}>
            {photos.length > 0 && (
              <ScrollView horizontal pagingEnabled showsHorizontalScrollIndicator={false}
                          style={styles.photoStrip}>
                {photos.map((p) => (
                  <Pressable key={p.which} onPress={() => urls[p.which] && urls[p.which] !== 'none' && setFull(p.which)}
                             accessibilityRole="imagebutton" accessibilityLabel={`${p.label}, full screen`}
                             style={{ width: width - spacing.lg * 2 }}>
                    {urls[p.which] && urls[p.which] !== 'none' ? (
                      <Image source={{ uri: urls[p.which] }} style={styles.photo} resizeMode="contain" />
                    ) : urls[p.which] === 'none' ? (
                      <Text style={[styles.small, muted]}>The photo is not available.</Text>
                    ) : <ActivityIndicator style={styles.spinner} />}
                    <Text style={[styles.small, muted]}>{p.label}</Text>
                  </Pressable>
                ))}
              </ScrollView>
            )}

            <Text style={[styles.line, text]}>{itemWords(item)}</Text>
            <Text style={[styles.small, muted]}>{whereLine(item)}</Text>
            <Text style={[styles.small, muted]}>{whoLine(item)}</Text>
            {item.completion && item.completion.quote ? (
              <Text style={[styles.small, muted]}>{`Done, said: “${item.completion.quote}”`}</Text>
            ) : null}

            {canAct && (
              <View style={styles.buttons}>
                {busy ? <ActivityIndicator size="small" /> : itemActions(item, canAct).map((a) => (
                  button(a.key, a.label, () => (a.patch ? act(a.patch)
                    : a.key === 'reassign' ? openReassign() : setMode(mode === 'due' ? null : 'due')),
                  mode === a.key)
                ))}
              </View>
            )}
            {canAct && mode === 'due' && (
              <View style={styles.buttons}>
                {DUE_CHOICES.map((d) => button(d.words, d.label, () => act({ due: d.words })))}
              </View>
            )}
            {canAct && mode === 'reassign' && (
              <View style={styles.more}>
                {people === null ? <ActivityIndicator size="small" /> : people.length === 0 ? (
                  <Text style={[styles.small, muted]}>No one to give it to: add people in Project → WhatsApp → People.</Text>
                ) : people.map((p) => (
                  <Pressable key={p.key} onPress={() => act({ assignee: p.key })} disabled={busy}
                             style={[styles.person, { borderColor: colors.glass.border }]}
                             accessibilityRole="button">
                    <Text style={[styles.line, text]}>{p.name}</Text>
                    <Text style={[styles.small, muted]}>
                      {[p.company, p.on_job ? '' : 'not on this job'].filter(Boolean).join(' · ')}
                    </Text>
                  </Pressable>
                ))}
              </View>
            )}

            <Text style={[styles.section, text]}>History</Text>
            {(item.history || []).map((h, i) => (
              <Text key={`${h.at}-${i}`} style={[styles.small, muted]}>{historyLine(h, when)}</Text>
            ))}
          </ScrollView>
        </SafeAreaView>

        {full && (
          <Modal visible transparent animationType="fade" onRequestClose={() => setFull(null)}>
            <View style={styles.fullBack}>
              <Image source={{ uri: urls[full] }} style={{ width, height: height * 0.85 }}
                     resizeMode="contain" accessibilityLabel={`Photo of ${item.pid}`} />
              <Pressable onPress={() => setFull(null)} hitSlop={16} style={styles.fullClose}
                         accessibilityLabel="Close photo">
                <X size={28} color="#fff" />
              </Pressable>
            </View>
          </Modal>
        )}
      </AnimatedBackground>
    </Modal>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', gap: spacing.md,
            paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  body: { padding: spacing.lg, paddingBottom: spacing.xl * 2 },
  title: { ...(typography?.h2 || { fontSize: 22, fontWeight: '700' }) },
  sub: { marginTop: spacing.xs, marginBottom: spacing.md },
  explain: { fontSize: 12, marginBottom: spacing.sm },
  chips: { marginBottom: spacing.sm, flexGrow: 0 },
  chip: { paddingVertical: 6, paddingHorizontal: 12, borderRadius: 8, borderWidth: 1,
          marginRight: spacing.xs },
  chipText: { fontSize: 13, fontWeight: '600' },
  card: { padding: spacing.md, marginBottom: spacing.md, borderRadius: borderRadius.lg },
  spinner: { marginVertical: spacing.md },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  pid: { fontWeight: '700', fontSize: 15 },
  status: { marginLeft: 'auto', fontSize: 12, fontWeight: '600' },
  line: { fontSize: 15, lineHeight: 21, marginTop: 2 },
  small: { fontSize: 12, marginTop: 2 },
  section: { fontWeight: '700', fontSize: 14, marginTop: spacing.lg, marginBottom: spacing.xs },
  more: { marginTop: spacing.sm },
  photoStrip: { flexGrow: 0, marginBottom: spacing.md },
  photo: { width: '100%', height: 300, borderRadius: 8 },
  buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginTop: spacing.sm },
  person: { borderWidth: 1, borderRadius: 8, padding: spacing.sm, marginBottom: spacing.xs },
  fullBack: { flex: 1, backgroundColor: 'rgba(0,0,0,0.95)', alignItems: 'center', justifyContent: 'center' },
  fullClose: { position: 'absolute', top: 48, right: 20 },
});
