/**
 * Project → WhatsApp → Attention (beta). Admins only.
 *
 * Shadow mode: what the assistant would flag from the project's group chats,
 * for review. Nothing here was posted anywhere. Each item: type, the exact
 * words from the chat, owner (when one was named), due (as said), and
 * Correct / Wrong / Dismiss. Under each, its timeline: every change a later
 * message made (rescheduled, done, cancelled, possibly done, a part done, a
 * flag) with the exact words, each marked Correct / Wrong on its own. Above
 * the list, precision per type and per kind of change. Open, or done /
 * cancelled.
 *
 * Copy: src/utils/whatsappAttention.js.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from 'react-native';
import { GlassCard } from '../GlassCard';
import { useToast } from '../Toast';
import { useTheme } from '../../context/ThemeContext';
import { whatsappAPI } from '../../utils/api';
import { quoteText, reviewNote } from '../../utils/sourceMessage';
import SourceSheet from './SourceSheet';
import { spacing } from '../../styles/theme';
import {
  ATTENTION_TITLE, ATTENTION_NOTE, VERDICTS, typeLabel, ownerLine, dueLine,
  statusLine, precisionLines, emptyText, LISTS, STATE_VERDICTS, eventLine, linkLine,
  reviewable, statePrecisionLines,
} from '../../utils/whatsappAttention';

export default function AttentionCard({ projectId }) {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const toast = useToast();
  const [data, setData] = useState(null);
  const [state, setState] = useState('loading'); // loading | ok | error
  const [busy, setBusy] = useState(null);
  const [list, setList] = useState('open');
  const [source, setSource] = useState(null);   // { rowId, reason } — the sheet

  const load = useCallback(async () => {
    try {
      setData(await whatsappAPI.getAttention(projectId, list));
      setState('ok');
    } catch (e) {
      setState('error');
    }
  }, [projectId, list]);

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

  const reviewChange = async (itemId, changeId, verdict) => {
    setBusy(changeId);
    try {
      await whatsappAPI.reviewAttentionChange(projectId, itemId, changeId, verdict);
      await load();
    } catch (e) {
      toast.error('Not saved', 'That could not be saved. Try again.');
    } finally {
      setBusy(null);
    }
  };

  const items = (data && data.items) || [];
  const lines = precisionLines(data && data.precision)
    .concat(statePrecisionLines(data && data.state_precision));
  return (
    <>
      <Text style={s.heading}>{ATTENTION_TITLE}</Text>
      <GlassCard style={s.card}>
        <Text style={s.muted}>{ATTENTION_NOTE}</Text>
        <View style={s.buttons}>
          {LISTS.map((l) => (
            <Pressable
              key={l.status}
              onPress={() => { setState('loading'); setList(l.status); }}
              style={[s.button, list === l.status && s.buttonActive]}
              accessibilityRole="tab"
              accessibilityState={{ selected: list === l.status }}
            >
              <Text style={s.buttonText}>{l.label}</Text>
            </Pressable>
          ))}
        </View>
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
                <Pressable disabled={!it.message_row_id}
                  onPress={() => setSource({ rowId: it.message_row_id, reason: it.review_reason })}
                  accessibilityRole="button" accessibilityLabel="Show the original message">
                  <Text style={s.quote}>{quoteText(it.quote, it.voice)}</Text>
                </Pressable>
                {reviewNote(null, it.review_reason)
                  ? <Text style={s.muted}>{reviewNote(null, it.review_reason)}</Text> : null}
                {it.summary ? <Text style={s.muted}>{it.summary}</Text> : null}
                {[ownerLine(it), dueLine(it), statusLine(it)].filter(Boolean).map((l) => (
                  <Text key={l} style={s.muted}>{l}</Text>
                ))}
                {(it.history || []).length > 1 ? (
                  <View style={s.timeline}>
                    {it.history.map((e) => (
                      <View key={e.id || e.kind} style={s.event}>
                        <Text style={s.eventLine}>{eventLine(e)}</Text>
                        {e.kind !== 'created' && e.quote ? (
                          <Pressable disabled={!e.message_row_id}
                            onPress={() => setSource({ rowId: e.message_row_id })}
                            accessibilityRole="button" accessibilityLabel="Show the original message">
                            <Text style={s.eventQuote}>
                              {quoteText(e.quote, e.evidence_kind === 'voice')}
                            </Text>
                          </Pressable>
                        ) : null}
                        {e.kind !== 'created' && linkLine(e) ? (
                          <Text style={s.muted}>{linkLine(e)}</Text>
                        ) : null}
                        {reviewable(e) ? (
                          <View style={s.buttons}>
                            {busy === e.id
                              ? <ActivityIndicator size="small" color={colors.text.muted} />
                              : STATE_VERDICTS.map((v) => (
                                <Pressable
                                  key={v.verdict}
                                  onPress={() => reviewChange(it.id, e.id, v.verdict)}
                                  disabled={!!busy}
                                  style={[s.button, e.verdict === v.verdict && s.buttonActive]}
                                  accessibilityRole="button"
                                  accessibilityLabel={`${v.label}: ${eventLine(e)}`}
                                >
                                  <Text style={s.buttonText}>{v.label}</Text>
                                </Pressable>
                              ))}
                          </View>
                        ) : null}
                      </View>
                    ))}
                  </View>
                ) : null}
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
      {source ? (
        <SourceSheet projectId={projectId} rowId={source.rowId} reason={source.reason}
          onClose={() => setSource(null)} />
      ) : null}
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
    buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginTop: spacing.sm },
    timeline: {
      marginTop: spacing.sm, paddingLeft: spacing.sm,
      borderLeftWidth: 2, borderLeftColor: colors.glass.border,
    },
    event: { marginTop: spacing.xs },
    eventLine: { color: colors.text.secondary, fontSize: 13, fontWeight: '600' },
    eventQuote: { color: colors.text.primary, fontSize: 14, marginTop: 2 },
    button: {
      paddingVertical: 6, paddingHorizontal: 12, borderRadius: 8,
      borderWidth: 1, borderColor: colors.glass.border,
    },
    buttonActive: { borderColor: colors.primary, backgroundColor: colors.primary + '20' },
    buttonText: { color: colors.text.primary, fontSize: 13, fontWeight: '600' },
  });
}
