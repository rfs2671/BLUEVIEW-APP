/**
 * THE ORIGINAL MESSAGE, one tap from any quote: the words as said (a voice
 * note's transcript in its own language), who and when, and for a voice note
 * its language, how sure the transcription was, the English, and Play.
 * Play opens the short-lived audio link in the phone's player.
 *
 * Errors are shown in the sheet itself: a toast cannot paint above a native
 * Modal (toastInsideModals.test.cjs).
 */
import React, { useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, Modal, Pressable, ActivityIndicator, Linking } from 'react-native';
import { GlassCard } from '../GlassCard';
import GlassButton from '../GlassButton';
import { useTheme } from '../../context/ThemeContext';
import { whatsappAPI } from '../../utils/api';
import { spacing } from '../../styles/theme';
import { withAlpha } from '../../styles/semanticColors';
import {
  englishLine, headLine, reviewNote, voiceLine,
} from '../../utils/sourceMessage';

export default function SourceSheet({ projectId, rowId, reason, onClose }) {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const [src, setSrc] = useState(null);
  const [state, setState] = useState('loading');   // loading | ok | error

  useEffect(() => {
    let live = true;
    if (!rowId) return undefined;
    setState('loading');
    whatsappAPI.getSource(projectId, rowId)
      .then((d) => { if (live) { setSrc(d); setState('ok'); } })
      .catch(() => { if (live) setState('error'); });
    return () => { live = false; };
  }, [projectId, rowId]);

  const v = src && src.voice;
  const note = reviewNote(v, reason);
  const english = englishLine(v, src && src.text);

  return (
    <Modal visible={!!rowId} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={s.backdrop} onPress={onClose} accessibilityLabel="Close">
        <Pressable onPress={() => {}}>
          <GlassCard variant="modal" style={s.card}>
            <Text style={s.title}>Original message</Text>
            {state === 'loading' ? (
              <ActivityIndicator color={colors.text.muted} style={{ marginTop: spacing.sm }} />
            ) : state === 'error' ? (
              <Text style={s.muted}>Could not load it. Try again.</Text>
            ) : (
              <>
                {headLine(src) ? <Text style={s.muted}>{headLine(src)}</Text> : null}
                <Text style={s.words}>{src.text}</Text>
                {v ? <Text style={s.muted}>{voiceLine(v)}</Text> : null}
                {english ? <Text style={s.muted}>{english}</Text> : null}
                {note ? <Text style={s.flag}>{note}</Text> : null}
                {v && v.audio_url ? (
                  <View style={s.buttons}>
                    <GlassButton title="Play audio" onPress={() => Linking.openURL(v.audio_url)} />
                  </View>
                ) : null}
              </>
            )}
            <View style={s.buttons}>
              <GlassButton title="Close" onPress={onClose} />
            </View>
          </GlassCard>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    backdrop: { flex: 1, justifyContent: 'center', padding: spacing.lg,
                backgroundColor: withAlpha('#000000', 0.6) },
    card: { padding: spacing.lg },
    title: { fontSize: 16, fontWeight: '700', color: colors.text.primary, marginBottom: spacing.xs },
    words: { fontSize: 15, lineHeight: 21, color: colors.text.primary, marginVertical: spacing.sm },
    muted: { fontSize: 13, color: colors.text.muted, marginTop: 2 },
    flag: { fontSize: 13, color: colors.text.primary, marginTop: spacing.sm, fontWeight: '600' },
    buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.md },
  });
}
