/**
 * COMPANY SETTINGS (Integrations → WhatsApp → Company settings, Admins):
 * company-wide switches, saved on tap (audited on the server). Copy and
 * state: src/utils/whatsappCompany.js.
 */

import React, { useCallback, useMemo, useState } from 'react';
import { View, Text, StyleSheet, Switch, ActivityIndicator } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { GlassCard } from '../GlassCard';
import { useToast } from '../Toast';
import { whatsappAPI } from '../../utils/api';
import { companyView } from '../../utils/whatsappCompany';
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
    </GlassCard>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    card: { marginBottom: spacing.xl },
    row: { flexDirection: 'row', alignItems: 'center', minHeight: 44, paddingVertical: spacing.sm },
    label: { color: colors.text.primary, fontSize: 15, fontWeight: '600' },
    note: { color: colors.text.muted, fontSize: 13, marginTop: 2 },
  });
}
