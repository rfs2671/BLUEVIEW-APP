import React, { useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, TextInput } from 'react-native';
import { X } from 'lucide-react-native';
import { useToast } from './Toast';
import { useTheme } from '../context/ThemeContext';
import { ownerAPI } from '../utils/api';
import { isOfflineError } from '../utils/offlineState';
import { serverMessage } from '../utils/ownerPortal';
import { correctionRequest, correctionView } from '../utils/answerCorrections';
import { spacing, borderRadius } from '../styles/theme';
import { semantic } from '../styles/semanticColors';

/**
 * "MARK WRONG" on one logged answer (owner portal: the review queue's item
 * and the Answers screen). The correct answer is required, the note
 * optional; each save is a NEW correction on the server (append-only, and
 * audited), so the earlier ones stay listed. Operator only: the server's
 * /api/owner routes are 404 to anyone else. Nothing is sent to anyone.
 */
export default function MarkWrongForm({ answerId, corrections, onSaved }) {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const toast = useToast();
  const [correct, setCorrect] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [list, setList] = useState(Array.isArray(corrections) ? corrections : []);

  useEffect(() => {
    setList(Array.isArray(corrections) ? corrections : []);
    setCorrect(''); setNote(''); setError('');
  }, [answerId, corrections]);

  const save = async () => {
    const req = correctionRequest(correct, note);
    if (req.error) { setError(req.error); return; }
    setError('');
    setBusy(true);
    try {
      const res = await ownerAPI.answerCorrect(answerId, req.body);
      if (Array.isArray(res?.corrections)) setList(res.corrections);
      setCorrect(''); setNote('');
      toast.success('Marked wrong', 'The correction was saved.');
      if (onSaved) onSaved(res);
    } catch (e) {
      setError(isOfflineError(e)
        ? 'Saving needs a connection. Nothing was saved.' : serverMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const views = list.map(correctionView).reverse();

  return (
    <View style={s.wrap}>
      {views.length ? (
        <>
          <Text style={s.section}>
            {views.length > 1 ? `CORRECTIONS (${views.length})` : 'CORRECTION'}
          </Text>
          {views.map((c, i) => (
            <View key={c.key} style={[s.row, i > 0 && s.old]}>
              <Text style={s.correct}>{c.correct}{i === 0 ? '' : ' (earlier)'}</Text>
              {c.note ? <Text style={s.meta}>Note: {c.note}</Text> : null}
              <Text style={s.meta}>{c.when}</Text>
            </View>
          ))}
        </>
      ) : null}
      <Text style={s.section}>MARK WRONG: CORRECT ANSWER (REQUIRED)</Text>
      <TextInput
        value={correct}
        onChangeText={(t) => { setCorrect(t); setError(''); }}
        placeholder="What the answer should have said"
        placeholderTextColor={colors.text.subtle}
        style={s.input}
        multiline
        accessibilityLabel="Correct answer"
      />
      <Text style={s.section}>NOTE (OPTIONAL)</Text>
      <TextInput
        value={note}
        onChangeText={(t) => { setNote(t); setError(''); }}
        placeholder="Why, or where you checked"
        placeholderTextColor={colors.text.subtle}
        style={[s.input, s.noteInput]}
        multiline
        accessibilityLabel="Note"
      />
      {error ? <Text style={s.error}>{error}</Text> : null}
      <Pressable onPress={save} disabled={busy} accessibilityRole="button"
        accessibilityLabel="Mark wrong"
        style={({ pressed }) => [s.btn, pressed && s.pressed]}>
        {busy
          ? <ActivityIndicator size="small" color={colors.text.primary} />
          : <X size={15} strokeWidth={1.75} color={semantic.attention} />}
        <Text style={s.btnText}>Mark wrong</Text>
      </Pressable>
    </View>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    wrap: { marginTop: spacing.md, gap: spacing.xs },
    section: {
      fontSize: 11, fontWeight: '700', letterSpacing: 1, color: colors.text.muted,
      marginTop: spacing.sm,
    },
    row: { gap: 2 },
    old: { opacity: 0.7, marginTop: spacing.xs },
    correct: { fontSize: 15, fontWeight: '600', color: colors.text.primary, lineHeight: 20 },
    meta: { fontSize: 13, color: colors.text.secondary, lineHeight: 18 },
    input: {
      minHeight: 72, borderWidth: 1, borderColor: colors.glass.border,
      borderRadius: borderRadius.lg, padding: spacing.sm,
      color: colors.text.primary, fontSize: 15, textAlignVertical: 'top',
    },
    noteInput: { minHeight: 52 },
    error: { fontSize: 13, color: semantic.attention, lineHeight: 18 },
    btn: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
      minHeight: 44, borderRadius: borderRadius.lg, borderWidth: 1,
      borderColor: semantic.attention,
    },
    btnText: { fontSize: 14, fontWeight: '600', color: colors.text.primary },
    pressed: { opacity: 0.8 },
  });
}
