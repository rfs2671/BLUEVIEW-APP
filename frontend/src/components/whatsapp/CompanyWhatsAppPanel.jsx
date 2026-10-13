/**
 * COMPANY SETTINGS (Integrations → WhatsApp → Company settings, Admins):
 * company-wide switches, saved on tap (audited on the server). Copy and
 * state: src/utils/whatsappCompany.js.
 */

import React, { useCallback, useMemo, useState } from 'react';
import { View, Text, StyleSheet, Switch, ActivityIndicator, Pressable } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { GlassCard } from '../GlassCard';
import { useToast } from '../Toast';
import { whatsappAPI } from '../../utils/api';
import { companyView, choiceView } from '../../utils/whatsappCompany';
import { useTheme } from '../../context/ThemeContext';
import { spacing } from '../../styles/theme';

export default function CompanyWhatsAppPanel() {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const toast = useToast();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(null);

  useFocusEffect(useCallback(() => {
    let live = true;
    whatsappAPI.getCompanySettings()
      .then((d) => { if (live) setData(d); })
      .catch(() => { if (live) setData({}); });
    return () => { live = false; };
  }, []));

  const change = async (sw, v) => {
    const before = data;
    setBusy(sw.key);
    setData({ ...(data || {}), [sw.key]: v });
    try {
      setData(await whatsappAPI.setCompanySettings({ [sw.key]: v }));
    } catch (e) {
      setData(before);
      const detail = e?.response?.data?.detail;
      toast.error('Not saved', typeof detail === 'string' ? detail : 'That could not be saved. Try again.');
    } finally {
      setBusy(null);
    }
  };

  if (data === null) {
    return <ActivityIndicator style={{ marginTop: spacing.xl }} color={colors.primary} />;
  }
  return (
    <GlassCard style={s.card}>
      {companyView(data).map((sw) => (
        <View key={sw.key} style={s.row}>
          <View style={{ flex: 1, marginRight: spacing.sm }}>
            <Text style={s.label}>{sw.label}</Text>
            <Text style={s.note}>{sw.line}</Text>
          </View>
          <Switch
            testID={`company-switch-${sw.key}`}
            value={sw.value}
            disabled={!!busy}
            onValueChange={(v) => change(sw, v)}
            accessibilityLabel={sw.label}
            trackColor={{ false: colors.glass.border, true: colors.primary }}
            thumbColor={colors.white}
          />
        </View>
      ))}
      {choiceView(data).map((c) => (
        <View key={c.key} style={s.choice}>
          <Text style={s.label}>{c.label}</Text>
          <View style={s.segment} accessibilityRole="radiogroup" accessibilityLabel={c.label}>
            {c.options.map((o) => {
              const on = c.value === o.value;
              return (
                <Pressable
                  key={o.value}
                  testID={`company-choice-${c.key}-${o.value}`}
                  accessibilityRole="radio"
                  accessibilityState={{ selected: on, disabled: !!busy }}
                  disabled={!!busy || on}
                  onPress={() => change(c, o.value)}
                  style={[s.option, on && { backgroundColor: colors.primary, borderColor: colors.primary }]}
                >
                  <Text style={[s.optionText, on && { color: colors.white }]}>{o.label}</Text>
                </Pressable>
              );
            })}
          </View>
          <Text style={s.note}>{c.options.find((o) => o.value === c.value)?.line}</Text>
        </View>
      ))}
    </GlassCard>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    card: { marginBottom: spacing.xl },
    row: { flexDirection: 'row', alignItems: 'center', minHeight: 44, paddingVertical: spacing.sm },
    label: { color: colors.text.primary, fontSize: 15, fontWeight: '600' },
    note: { color: colors.text.muted, fontSize: 13, marginTop: 2 },
    choice: { paddingVertical: spacing.sm },
    segment: { flexDirection: 'row', marginTop: spacing.xs },
    option: {
      flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center',
      borderWidth: 1, borderColor: colors.glass.border, marginRight: 8, borderRadius: 10,
    },
    optionText: { color: colors.text.primary, fontSize: 15, fontWeight: '600' },
  });
}
