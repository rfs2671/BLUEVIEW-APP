/**
 * Project → WhatsApp → Would chase (beta). Admins only.
 *
 * Shadow mode: each nudge sub chasing WOULD have sent (nothing was sent):
 * when, to whom, the item(s), the exact message text, and why it fired.
 * Correct / Wrong per entry; precision above the list, overall and per slot.
 *
 * Copy: src/utils/whatsappChase.js.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from 'react-native';
import { GlassCard } from '../GlassCard';
import { useToast } from '../Toast';
import { useTheme } from '../../context/ThemeContext';
import { whatsappAPI } from '../../utils/api';
import { spacing } from '../../styles/theme';
import {
  CHASE_TITLE, CHASE_NOTE, CHASE_OFF_NOTE, CHASE_VERDICTS, headLine, ownerLine,
  reasonLine, precisionLines, emptyText,
} from '../../utils/whatsappChase';

export default function ChaseCard({ projectId }) {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const toast = useToast();
  const [data, setData] = useState(null);
  const [state, setState] = useState('loading'); // loading | ok | error
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    try {
      setData(await whatsappAPI.getChase(projectId));
      setState('ok');
    } catch (e) {
      setState('error');
    }
  }, [projectId]);

  useEffect(() => { if (projectId) load(); }, [projectId, load]);

  const review = async (entryId, verdict) => {
    setBusy(entryId);
    try {
      await whatsappAPI.reviewChase(projectId, entryId, verdict);
      await load();
    } catch (e) {
      toast.error('Not saved', 'That could not be saved. Try again.');
    } finally {
      setBusy(null);
    }
  };

  const entries = (data && data.entries) || [];
  const lines = precisionLines(data && data.precision);
  return (
    <>
      <Text style={s.heading}>{CHASE_TITLE}</Text>
      <GlassCard style={s.card}>
        <Text style={s.muted}>{CHASE_NOTE}</Text>
        {data && data.disabled ? <Text style={s.muted}>{CHASE_OFF_NOTE}</Text> : null}
        {state === 'loading' ? (
          <ActivityIndicator color={colors.text.muted} style={{ marginTop: spacing.sm }} />
        ) : state === 'error' ? (
          <Pressable onPress={load}>
            <Text style={s.muted}>This list could not be loaded. Tap to try again.</Text>
          </Pressable>
        ) : (
          <>
            {lines.length ? (
              <View style={s.stats}>
                {lines.map((l) => <Text key={l} style={s.statLine}>{l}</Text>)}
              </View>
            ) : null}
            {entries.length === 0 ? (
              <Text style={[s.muted, { marginTop: spacing.sm }]}>{emptyText(data && data.total)}</Text>
            ) : entries.map((e) => (
              <View key={e.id} style={s.item}>
                <Text style={s.type}>{headLine(e)}</Text>
                {ownerLine(e) ? <Text style={s.muted}>{ownerLine(e)}</Text> : null}
                <View style={s.message}>
                  <Text style={s.messageText}>{e.text}</Text>
                </View>
                {reasonLine(e) ? <Text style={s.muted}>{reasonLine(e)}</Text> : null}
                <View style={s.buttons}>
                  {busy === e.id ? <ActivityIndicator size="small" color={colors.text.muted} />
                    : CHASE_VERDICTS.map((v) => (
                      <Pressable
                        key={v.verdict}
                        onPress={() => review(e.id, v.verdict)}
                        disabled={!!busy}
                        style={[s.button, e.verdict === v.verdict && s.buttonActive]}
                        accessibilityRole="button"
                        accessibilityLabel={`${v.label}: ${headLine(e)}`}
                      >
                        <Text style={s.buttonText}>{v.label}</Text>
                      </Pressable>
                    ))}
                </View>
              </View>
            ))}
          </>
        )}
      </GlassCard>
    </>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    heading: {
      fontSize: 13, fontWeight: '600', color: colors.text.muted, letterSpacing: 0.6,
      textTransform: 'uppercase', marginTop: spacing.lg, marginBottom: spacing.sm,
    },
    card: { padding: spacing.md },
    muted: { color: colors.text.muted, fontSize: 13, marginTop: 4 },
    stats: {
      marginTop: spacing.sm, paddingTop: spacing.sm,
      borderTopWidth: 1, borderTopColor: colors.glass.border,
    },
    statLine: { color: colors.text.secondary, fontSize: 13 },
    item: {
      marginTop: spacing.sm, paddingTop: spacing.sm,
      borderTopWidth: 1, borderTopColor: colors.glass.border,
    },
    type: { color: colors.text.muted, fontSize: 12, fontWeight: '600' },
    message: {
      marginTop: spacing.xs, padding: spacing.sm, borderRadius: 8,
      borderWidth: 1, borderColor: colors.glass.border,
    },
    messageText: { color: colors.text.primary, fontSize: 14 },
    buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginTop: spacing.sm },
    button: {
      paddingVertical: 6, paddingHorizontal: 12, borderRadius: 8,
      borderWidth: 1, borderColor: colors.glass.border,
    },
    buttonActive: { borderColor: colors.primary, backgroundColor: colors.primary + '20' },
    buttonText: { color: colors.text.primary, fontSize: 13, fontWeight: '600' },
  });
}
