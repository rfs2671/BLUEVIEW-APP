/**
 * Project → WhatsApp → Attention (beta). Admins only.
 *
 * Shadow mode: what the assistant would flag from the project's group chats,
 * for review. Nothing here was posted anywhere. Each item: type, the exact
 * words from the chat, owner (when one was named), due (as said), and
 * Correct / Wrong / Dismiss. Above the list, precision per type.
 *
 * Copy: src/utils/whatsappAttention.js.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from 'react-native';
import { GlassCard } from '../GlassCard';
import { useToast } from '../Toast';
import { useTheme } from '../../context/ThemeContext';
import { whatsappAPI } from '../../utils/api';
import { spacing } from '../../styles/theme';
import {
  ATTENTION_TITLE, ATTENTION_NOTE, VERDICTS, typeLabel, ownerLine, dueLine,
  statusLine, precisionLines, emptyText,
} from '../../utils/whatsappAttention';

export default function AttentionCard({ projectId }) {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const toast = useToast();
  const [data, setData] = useState(null);
  const [state, setState] = useState('loading'); // loading | ok | error
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    try {
      setData(await whatsappAPI.getAttention(projectId));
      setState('ok');
    } catch (e) {
      setState('error');
    }
  }, [projectId]);

  useEffect(() => { if (projectId) load(); }, [projectId, load]);

  const review = async (itemId, verdict) => {
    setBusy(itemId);
    try {
      await whatsappAPI.reviewAttention(projectId, itemId, verdict);
      await load();
    } catch (e) {
      toast.error('Not saved', 'That could not be saved. Try again.');
    } finally {
      setBusy(null);
    }
  };

  const items = (data && data.items) || [];
  const lines = precisionLines(data && data.precision);
  return (
    <>
      <Text style={s.heading}>{ATTENTION_TITLE}</Text>
      <GlassCard style={s.card}>
        <Text style={s.muted}>{ATTENTION_NOTE}</Text>
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
            {items.length === 0 ? (
              <Text style={[s.muted, { marginTop: spacing.sm }]}>{emptyText(data && data.total)}</Text>
            ) : items.map((it) => (
              <View key={it.id} style={s.item}>
                <Text style={s.type}>
                  {typeLabel(it.type)}{it.importance === 'high' ? ' · High' : ''}
                  {it.group_name ? ` · ${it.group_name}` : ''}
                </Text>
                <Text style={s.quote}>“{it.quote}”</Text>
                {it.summary ? <Text style={s.muted}>{it.summary}</Text> : null}
                {[ownerLine(it), dueLine(it), statusLine(it)].filter(Boolean).map((l) => (
                  <Text key={l} style={s.muted}>{l}</Text>
                ))}
                <View style={s.buttons}>
                  {busy === it.id ? <ActivityIndicator size="small" color={colors.text.muted} />
                    : VERDICTS.map((v) => (
                      <Pressable
                        key={v.verdict}
                        onPress={() => review(it.id, v.verdict)}
                        disabled={!!busy}
                        style={[s.button, it.verdict === v.verdict && s.buttonActive]}
                        accessibilityRole="button"
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
    quote: { color: colors.text.primary, fontSize: 15, marginTop: 2 },
    buttons: { flexDirection: 'row', gap: spacing.xs, marginTop: spacing.sm },
    button: {
      paddingVertical: 6, paddingHorizontal: 12, borderRadius: 8,
      borderWidth: 1, borderColor: colors.glass.border,
    },
    buttonActive: { borderColor: colors.primary, backgroundColor: colors.primary + '20' },
    buttonText: { color: colors.text.primary, fontSize: 13, fontWeight: '600' },
  });
}
