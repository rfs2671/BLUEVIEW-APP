/**
 * What a person speaks in WhatsApp voice notes: Auto · English · Español ·
 * Yiddish. Set, it is Whisper's language hint for their notes; Auto lets
 * Whisper detect it. One picker for everyone who can send a voice note:
 * unknown senders (People), users (Admin → Users) and workers (their screen).
 * It saves on tap. Kept per company and sender on the server.
 *
 * VoiceLanguagePicker: the chips, for a screen that already has the value.
 * VoiceLanguageSetting: loads and saves it itself (users, workers).
 *
 * Copy: src/utils/whatsappPeople.js (LANGUAGES, LANGUAGE_NOTE).
 */
import React, { useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from 'react-native';
import { useTheme } from '../../context/ThemeContext';
import { useToast } from '../Toast';
import { spacing, borderRadius } from '../../styles/theme';
import { LANGUAGES, LANGUAGE_NOTE, NO_PHONE_LANGUAGE_NOTE } from '../../utils/whatsappPeople';

export function VoiceLanguagePicker({ value, onSelect, disabled = false, label = true }) {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const current = value || 'auto';
  return (
    <View>
      {label ? <Text style={s.label}>Voice note language</Text> : null}
      <View style={s.langs}>
        {LANGUAGES.map((l) => {
          const on = current === l.value;
          return (
            <Pressable key={l.value} onPress={() => onSelect(l.value)} disabled={disabled || on}
              accessibilityRole="radio" accessibilityState={{ selected: on, disabled }}
              accessibilityLabel={`Voice note language: ${l.label}`}
              style={({ pressed }) => [s.lang, on && s.langOn, pressed && s.pressed]}>
              <Text style={s.langText}>{l.label}</Text>
            </Pressable>
          );
        })}
      </View>
      <Text style={s.note}>{LANGUAGE_NOTE}</Text>
    </View>
  );
}

export function VoiceLanguageSetting({ load, save, editable = true }) {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const toast = useToast();
  const [state, setState] = useState({ status: 'loading' });  // loading | ok | error
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let live = true;
    load()
      .then((d) => { if (live) setState({ status: 'ok', ...d }); })
      .catch(() => { if (live) setState({ status: 'error' }); });
    return () => { live = false; };
  }, [load]);

  const select = async (language) => {
    setSaving(true);
    try {
      const d = await save(language);
      setState((st) => ({ ...st, ...d }));
    } catch (e) {
      const detail = e?.response?.data?.detail;
      toast.error('Not saved', typeof detail === 'string' ? detail : 'That could not be saved. Try again.');
    } finally {
      setSaving(false);
    }
  };

  if (state.status === 'loading') {
    return <ActivityIndicator size="small" color={colors.text.muted} style={{ marginTop: spacing.sm }} />;
  }
  if (state.status === 'error') {
    return <Text style={s.note}>The voice note language could not be loaded.</Text>;
  }
  if (!state.has_phone) {
    return (
      <View>
        <Text style={s.label}>Voice note language</Text>
        <Text style={s.note}>{NO_PHONE_LANGUAGE_NOTE}</Text>
      </View>
    );
  }
  return (
    <View>
      <VoiceLanguagePicker value={state.language} onSelect={select}
        disabled={saving || !editable} />
      {saving ? <ActivityIndicator size="small" color={colors.text.muted} /> : null}
    </View>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    label: { color: colors.text.muted, fontSize: 12, fontWeight: '600', marginTop: spacing.sm },
    langs: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginTop: spacing.xs },
    lang: {
      minHeight: 44, paddingHorizontal: spacing.md, justifyContent: 'center',
      borderRadius: borderRadius.md, borderWidth: 1, borderColor: colors.glass.border,
    },
    langOn: { backgroundColor: colors.glass.background, borderColor: colors.primary },
    pressed: { opacity: 0.7 },
    langText: { color: colors.text.primary, fontSize: 15 },
    note: { color: colors.text.muted, fontSize: 13, marginTop: 4 },
  });
}

export default VoiceLanguagePicker;
