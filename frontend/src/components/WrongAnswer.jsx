import React, { useState } from 'react';
import { View, Text, TextInput, Pressable, StyleSheet, ActivityIndicator } from 'react-native';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius } from '../styles/theme';
import { answersAPI } from '../utils/api';
import {
  FLAGGED, SEND_FAILED, NOTE_PLACEHOLDER, NOTE_MAX, disputable, isFlagged, markFlagged,
} from '../utils/answerDispute';

/**
 * "Wrong?" under an assistant answer. One tap opens an optional note and
 * Send; Send (empty is fine) flags the answer and the control becomes
 * "Flagged for review" -- and stays so for that answer this session. Nothing
 * here ever shows a review status, an approve / deny, or a reviewer.
 * An answer with no answer_log_id shows nothing: there is nothing to flag.
 */
export default function WrongAnswer({ answerLogId }) {
  const { colors } = useTheme();
  const [stage, setStage] = useState(() => (isFlagged(answerLogId) ? 'flagged' : 'idle'));
  const [note, setNote] = useState('');
  const [error, setError] = useState(false);

  if (!disputable(answerLogId)) return null;

  const muted = { color: colors.text.muted };
  const text = { color: colors.text.primary };

  if (stage === 'flagged' || isFlagged(answerLogId)) {
    return (
      <View style={styles.row} accessibilityLiveRegion="polite">
        <Text style={[styles.small, muted]} accessibilityRole="text">{FLAGGED}</Text>
      </View>
    );
  }

  if (stage === 'idle') {
    return (
      <View style={styles.row}>
        <Pressable
          onPress={() => setStage('open')}
          hitSlop={8}
          style={styles.tap}
          accessibilityRole="button"
          accessibilityLabel="Wrong? Flag this answer for review"
        >
          <Text style={[styles.small, styles.link, muted]}>Wrong?</Text>
        </Pressable>
      </View>
    );
  }

  const sending = stage === 'sending';
  const send = async () => {
    if (sending) return;
    setError(false);
    setStage('sending');
    try {
      await answersAPI.dispute(answerLogId, note);
      markFlagged(answerLogId);
      setStage('flagged');
    } catch (e) {
      // Keep the box and what they wrote; they can send again.
      setError(true);
      setStage('open');
    }
  };

  return (
    <View style={styles.box}>
      <TextInput
        value={note}
        onChangeText={setNote}
        placeholder={NOTE_PLACEHOLDER}
        placeholderTextColor={muted.color}
        multiline
        maxLength={NOTE_MAX}
        editable={!sending}
        style={[styles.input, text, { borderColor: colors.glass?.border || 'rgba(128,128,128,0.4)' }]}
        accessibilityLabel={NOTE_PLACEHOLDER}
      />
      <View style={styles.actions}>
        {error ? (
          <Text style={[styles.small, { color: colors.error }]} accessibilityRole="alert"
                accessibilityLiveRegion="polite">
            {SEND_FAILED}
          </Text>
        ) : <View />}
        <Pressable
          onPress={send}
          disabled={sending}
          hitSlop={8}
          style={[styles.send, { backgroundColor: colors.primary }, sending && styles.dim]}
          accessibilityRole="button"
          accessibilityLabel="Send: flag this answer for review"
          accessibilityState={{ disabled: sending, busy: sending }}
        >
          {sending
            ? <ActivityIndicator size="small" color={colors.onPrimary} />
            : <Text style={[styles.sendText, { color: colors.onPrimary }]}>Send</Text>}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', marginTop: spacing.xs },
  tap: { minHeight: 44, justifyContent: 'center', paddingRight: spacing.sm },
  small: { fontSize: 13 },
  link: { textDecorationLine: 'underline' },
  box: { marginTop: spacing.sm, width: '100%' },
  input: { minHeight: 64, borderWidth: 1, borderRadius: borderRadius.sm, padding: spacing.sm,
           fontSize: 15, textAlignVertical: 'top' },
  actions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
             gap: spacing.sm, marginTop: spacing.sm },
  send: { minHeight: 44, minWidth: 88, paddingHorizontal: spacing.md, borderRadius: borderRadius.sm,
          alignItems: 'center', justifyContent: 'center' },
  sendText: { fontWeight: '700', fontSize: 15 },
  dim: { opacity: 0.6 },
});
