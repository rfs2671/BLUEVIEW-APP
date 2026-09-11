/**
 * TELLS A MAN ONCE THAT A DAILY LOG ON HIS DEVICE WAS NEVER FILED.
 *
 * The two legacy daily-log editors are retired. They wrote drafts to this
 * device and promised they would sync on reconnect; `draftSync` refuses those
 * types outright, so they never did. The bytes are still here -- the refusal
 * never cleared the pending key -- but the record was never filed, and the
 * screen that could show it is gone.
 *
 * There is no server-side trace of one of these, so this is the only place the
 * question can be asked. It is asked once per draft and then never again.
 *
 * HEADLESS UNTIL IT HAS SOMETHING TO SAY, and mounted beside SiteManifestSync
 * and AdminPlanPrefetch for the same reason they are: it must run after auth
 * settles and must not be tied to any one screen, least of all the two that
 * were removed.
 *
 * The wording and the selection rule live in utils/unfiledDailyLogs.js, pure,
 * so both are tested without a renderer.
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  Modal, Pressable, ScrollView, StyleSheet, Text, View,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useRouter } from 'expo-router';

import { getPendingKeys, readDraft } from '../utils/logbookDrafts';
import { readCachedProjectList } from '../utils/projectCache';
import {
  DISMISSED_KEY, draftLines, noticeText, unfiledDrafts,
} from '../utils/unfiledDailyLogs';
import { useTheme } from '../context/ThemeContext';
import { colors, borderRadius, spacing, touchTarget } from '../styles/theme';

async function readDismissed() {
  try {
    const raw = await AsyncStorage.getItem(DISMISSED_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (_e) {
    return [];
  }
}

async function addDismissed(key) {
  try {
    const list = await readDismissed();
    if (!list.includes(key)) {
      list.push(key);
      await AsyncStorage.setItem(DISMISSED_KEY, JSON.stringify(list));
    }
  } catch (_e) {
    // A dismissal that cannot be stored means he is told again next launch.
    // Annoying, and strictly better than losing the notice entirely.
  }
}

export default function UnfiledDailyLogNotice() {
  const router = useRouter();
  const { isDark } = useTheme();
  const [draft, setDraft] = useState(null);      // {key, projectId, date}
  const [projectName, setProjectName] = useState('');
  const [lines, setLines] = useState(null);      // null until "Read" is tapped

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [pending, dismissed] = await Promise.all([
          getPendingKeys(), readDismissed(),
        ]);
        const found = unfiledDrafts(pending, dismissed);
        if (cancelled || found.length === 0) return;
        const first = found[0];
        let name = '';
        try {
          const projects = await readCachedProjectList();
          const p = (projects || []).find(
            (x) => String(x.id || x._id) === String(first.projectId));
          name = (p && (p.name || p.address)) || '';
        } catch (_e) { /* the copy has a fallback for an unknown project */ }
        if (cancelled) return;
        setProjectName(name);
        setDraft(first);
      } catch (_e) {
        // NEVER BLOCK A LAUNCH. This is a courtesy to a man who may have
        // nothing pending at all; a failure here must not be his first screen.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const dismiss = useCallback(async () => {
    if (draft) await addDismissed(draft.key);
    setDraft(null);
    setLines(null);
  }, [draft]);

  const onRead = useCallback(async () => {
    if (!draft) return;
    try {
      const d = await readDraft(draft.key);
      setLines(draftLines(d));
    } catch (_e) {
      setLines([]);
    }
  }, [draft]);

  const onOpenLogBooks = useCallback(async () => {
    await dismiss();
    try { router.push('/logbooks'); } catch (_e) { /* no route: stay put */ }
  }, [dismiss, router]);

  if (!draft) return null;

  const text = noticeText({ projectName, date: draft.date });
  const bg = isDark ? '#0f172a' : '#ffffff';
  const fg = isDark ? '#e2e8f0' : '#0A1929';
  const quiet = isDark ? '#94a3b8' : '#475569';

  return (
    <Modal transparent animationType="fade" visible onRequestClose={dismiss}>
      <View style={s.scrim}>
        <View style={[s.card, { backgroundColor: bg }]}>
          <Text style={[s.title, { color: fg }]}>{text.title}</Text>
          <Text style={[s.body, { color: quiet }]}>{text.body}</Text>

          {lines !== null && (
            <ScrollView style={s.readout} contentContainerStyle={s.readoutInner}>
              {lines.length === 0 ? (
                <Text style={[s.body, { color: quiet }]}>
                  This draft is on the device but its contents could not be
                  read. Nothing has been deleted.
                </Text>
              ) : lines.map(([k, v]) => (
                <View key={k} style={s.row}>
                  <Text style={[s.rowKey, { color: quiet }]}>{k}</Text>
                  <Text style={[s.rowVal, { color: fg }]}>{v}</Text>
                </View>
              ))}
            </ScrollView>
          )}

          {/* FIRST, AND NOT OPTIONAL. Without it, "enter it in Log Books" is
              an instruction he cannot follow. */}
          {lines === null && (
            <Pressable style={[s.btn, s.primary]} onPress={onRead}>
              <Text style={s.primaryText}>{text.actions[0]}</Text>
            </Pressable>
          )}
          <Pressable style={[s.btn, s.secondary]} onPress={onOpenLogBooks}>
            <Text style={[s.secondaryText, { color: fg }]}>
              {text.actions[1]}
            </Text>
          </Pressable>
          <Pressable style={[s.btn, s.quiet]} onPress={dismiss}>
            <Text style={[s.quietText, { color: quiet }]}>
              {text.actions[2]}
            </Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  scrim: {
    flex: 1, backgroundColor: 'rgba(0,0,0,0.55)',
    alignItems: 'center', justifyContent: 'center', padding: spacing.lg,
  },
  card: {
    width: '100%', maxWidth: 460, borderRadius: borderRadius.lg,
    padding: spacing.lg,
  },
  title: { fontSize: 18, fontWeight: '700', marginBottom: spacing.sm },
  body: { fontSize: 14, lineHeight: 21 },
  readout: { maxHeight: 240, marginTop: spacing.md },
  readoutInner: { paddingBottom: spacing.sm },
  row: { flexDirection: 'row', paddingVertical: 4, gap: spacing.sm },
  rowKey: { fontSize: 12, width: 132 },
  rowVal: { fontSize: 13, flex: 1, fontWeight: '500' },
  btn: {
    minHeight: touchTarget.min, borderRadius: borderRadius.md,
    alignItems: 'center', justifyContent: 'center', marginTop: spacing.sm,
  },
  primary: { backgroundColor: colors.primary || '#0A1929' },
  primaryText: { color: '#ffffff', fontSize: 15, fontWeight: '700' },
  secondary: { borderWidth: 1, borderColor: '#cbd5e1' },
  secondaryText: { fontSize: 15, fontWeight: '600' },
  quiet: {},
  quietText: { fontSize: 14, fontWeight: '500' },
});
