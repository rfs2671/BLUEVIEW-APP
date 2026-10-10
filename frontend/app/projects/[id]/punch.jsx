import React, { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  Image,
  ActivityIndicator,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft, Camera } from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import { useToast } from '../../../src/components/Toast';
import { punchAPI } from '../../../src/utils/api';
import { useAuth, isCompanyAdmin } from '../../../src/context/AuthContext';
import {
  statusLabel, floorLabel, filterChips, whereLine, whoLine, itemWords, historyLine,
  emptyText, ADMIN_STATUSES,
} from '../../../src/utils/punchList';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';
import HeaderBrand from '../../../src/components/HeaderBrand';

const when = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
};

// Project → Punch list: the items from walkthroughs on this job (each one a
// photo and the walker's words, typed or spoken), by floor, trade and
// status. Tap an item for its photo and its history. Admins can set the
// status (the chase follows); everything else happens in WhatsApp.
export default function ProjectPunchScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { colors } = useTheme();
  const toast = useToast();
  const { user } = useAuth();
  const isAdmin = isCompanyAdmin(user);
  const [data, setData] = useState(null);
  const [filters, setFilters] = useState({ floor: '', trade: '', status: '' });
  const [open, setOpen] = useState(null);        // pid shown in full
  const [photos, setPhotos] = useState({});      // pid -> url | 'none'
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    try {
      setData(await punchAPI.list(projectId, filters));
    } catch (e) {
      setData({ items: [], floors: [], trades: [], statuses: [], error: true });
    }
  }, [projectId, filters]);

  useEffect(() => { load(); }, [load]);

  const expand = async (it) => {
    const next = open === it.pid ? null : it.pid;
    setOpen(next);
    if (next && it.has_photo && !photos[it.pid]) {
      try {
        const { url } = await punchAPI.photo(projectId, it.pid);
        setPhotos((p) => ({ ...p, [it.pid]: url || 'none' }));
      } catch (e) {
        setPhotos((p) => ({ ...p, [it.pid]: 'none' }));
      }
    }
  };

  const setStatus = async (it, status) => {
    setBusy(it.pid);
    try {
      const saved = await punchAPI.edit(projectId, it.pid, { status });
      setData((d) => ({ ...d, items: d.items.map((x) => (x.pid === saved.pid ? saved : x)) }));
    } catch (e) {
      toast?.error?.('Not saved', 'Try again.');
    } finally {
      setBusy(null);
    }
  };

  const text = { color: colors.text.primary };
  const muted = { color: colors.text.muted };
  const items = (data && data.items) || [];
  const filtered = !!(filters.floor || filters.trade || filters.status);

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
          <Text style={[styles.title, text]}>Punch list</Text>
          <Text style={[styles.sub, muted]}>
            From walkthroughs in WhatsApp: each item is a photo and the walker's own words.
          </Text>

          {data && (
            <>
              {chipRow('status', filterChips(data.statuses, statusLabel))}
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
              <Pressable onPress={() => expand(it)} accessibilityRole="button"
                         accessibilityLabel={`${it.pid}, ${statusLabel(it.status)}`}>
                <View style={styles.row}>
                  <Text style={[styles.pid, text]}>{it.pid}</Text>
                  {it.has_photo && <Camera size={14} color={muted.color} />}
                  <Text style={[styles.status, muted]}>{statusLabel(it.status)}</Text>
                </View>
                <Text style={[styles.line, text]}>{itemWords(it)}</Text>
                <Text style={[styles.small, muted]}>{whereLine(it)}</Text>
                <Text style={[styles.small, muted]}>{whoLine(it)}</Text>
              </Pressable>

              {open === it.pid && (
                <View style={styles.more}>
                  {photos[it.pid] && photos[it.pid] !== 'none' ? (
                    <Image source={{ uri: photos[it.pid] }} style={styles.photo} resizeMode="cover"
                           accessibilityLabel={`Photo of ${it.pid}`} />
                  ) : it.has_photo && !photos[it.pid] ? (
                    <ActivityIndicator style={styles.spinner} />
                  ) : null}
                  {it.completion && it.completion.quote ? (
                    <Text style={[styles.small, muted]}>
                      {`Done, said: “${it.completion.quote}”`}
                    </Text>
                  ) : null}
                  {(it.history || []).map((h, i) => (
                    <Text key={`${h.at}-${i}`} style={[styles.small, muted]}>{historyLine(h, when)}</Text>
                  ))}
                  {isAdmin && (
                    <View style={styles.buttons}>
                      {busy === it.pid ? <ActivityIndicator size="small" /> : ADMIN_STATUSES.map((st) => (
                        <Pressable
                          key={st}
                          onPress={() => setStatus(it, st)}
                          disabled={!!busy || it.status === st}
                          style={[styles.chip, { borderColor: colors.glass.border },
                                  it.status === st && { borderColor: colors.primary }]}
                          accessibilityRole="button"
                        >
                          <Text style={[styles.chipText, text]}>{statusLabel(st)}</Text>
                        </Pressable>
                      ))}
                    </View>
                  )}
                </View>
              )}
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
  more: { marginTop: spacing.sm },
  photo: { width: '100%', height: 220, borderRadius: 8, marginBottom: spacing.sm },
  buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginTop: spacing.sm },
});
