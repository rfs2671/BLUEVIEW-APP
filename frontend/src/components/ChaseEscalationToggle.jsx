/**
 * "Gets chase escalation DMs" — one switch, for an admin or a PM.
 *
 * Admins get them by default, PMs don't (src/utils/roleVocabulary.js
 * `getsChaseEscalation`, the server's gets_chase_escalation). Only an admin
 * changes it (PUT /admin/users/{id}/chase-escalation, audited). Saves on tap.
 */

import React, { useMemo, useState } from 'react';
import { View, Text, StyleSheet, Switch } from 'react-native';
import { useTheme } from '../context/ThemeContext';
import { useToast } from './Toast';
import { adminUsersAPI } from '../utils/api';
import { spacing } from '../styles/theme';
import { getsChaseEscalation, CHASE_ESCALATION_LABEL, CHASE_ESCALATION_NOTE } from '../utils/roleVocabulary';

export default function ChaseEscalationToggle({ userRow, onSaved }) {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const toast = useToast();
  const [on, setOn] = useState(() => getsChaseEscalation(userRow));
  const [saving, setSaving] = useState(false);
  const id = userRow && (userRow.id || userRow._id);

  const change = async (value) => {
    setSaving(true);
    const before = on;
    setOn(value);
    try {
      await adminUsersAPI.setChaseEscalation(id, value);
      if (onSaved) onSaved(value);
    } catch (e) {
      setOn(before);
      const detail = e?.response?.data?.detail;
      toast.error('Not saved', typeof detail === 'string' ? detail : 'That could not be saved. Try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={s.row}>
      <View style={{ flex: 1, marginRight: spacing.sm }}>
        <Text style={s.label}>{CHASE_ESCALATION_LABEL}</Text>
        <Text style={s.note}>{CHASE_ESCALATION_NOTE}</Text>
      </View>
      <Switch
        testID="chase-escalation-switch"
        value={on}
        disabled={saving || !id}
        onValueChange={change}
        accessibilityLabel={CHASE_ESCALATION_LABEL}
        trackColor={{ false: colors.glass.border, true: colors.primary }}
        thumbColor={colors.white}
      />
    </View>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    row: { flexDirection: 'row', alignItems: 'center', marginTop: spacing.md, minHeight: 44 },
    label: { color: colors.text.primary, fontSize: 15, fontWeight: '600' },
    note: { color: colors.text.muted, fontSize: 13, marginTop: 2 },
  });
}
