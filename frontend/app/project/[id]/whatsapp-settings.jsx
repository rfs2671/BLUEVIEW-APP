/**
 * Project → WhatsApp settings (admins only).
 *
 * The GC group — the one WhatsApp group Levelog posts DOB alerts into — and
 * the two alerts it posts there. Only settings for features that are live;
 * the copy for each state is in src/utils/whatsappSettings.js.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ScrollView, Switch, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { ArrowLeft, Check } from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import HeaderBrand from '../../../src/components/HeaderBrand';
import { useAuth, isCompanyAdmin } from '../../../src/context/AuthContext';
import { useTheme } from '../../../src/context/ThemeContext';
import { useToast, ToastHost } from '../../../src/components/Toast';
import { whatsappAPI } from '../../../src/utils/api';
import { whatsappSettingsView } from '../../../src/utils/whatsappSettings';
import { spacing } from '../../../src/styles/theme';

export default function WhatsAppSettingsScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const { colors } = useTheme();
  const styles = useMemo(() => buildStyles(colors), [colors]);
  const toast = useToast();
  const isAdmin = isCompanyAdmin(user);
  const [data, setData] = useState(null);
  const [state, setState] = useState('loading'); // loading | ok | error
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    if (authLoading) return;
    if (isAuthenticated === false) {
      const t = setTimeout(() => router.replace('/login'), 0);
      return () => clearTimeout(t);
    }
  }, [isAuthenticated, authLoading]);

  const load = useCallback(async () => {
    try {
      setData(await whatsappAPI.getProjectSettings(projectId));
      setState('ok');
    } catch (e) {
      setState('error');
    }
  }, [projectId]);

  useEffect(() => {
    if (isAuthenticated && isAdmin && projectId) load();
  }, [isAuthenticated, isAdmin, projectId, load]);

  const pick = async (groupId) => {
    setBusy(groupId);
    try {
      await whatsappAPI.setGcGroup(projectId, groupId);
      setPicking(false);
      // The PUT answers with the stored settings, not this screen's view.
      await load();
    } catch (e) {
      toast.error('Not saved', 'That group could not be set. Try again.');
    } finally {
      setBusy(null);
    }
  };

  const toggle = async (key, value) => {
    setBusy(key);
    try {
      setData(await whatsappAPI.setProjectAlerts(projectId, { [key]: value }));
    } catch (e) {
      toast.error('Not saved', 'The setting could not be changed. Try again.');
    } finally {
      setBusy(null);
    }
  };

  if (authLoading || !isAuthenticated) return null;
  const view = whatsappSettingsView(data);

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
        <View style={styles.headerBar}>
          <Pressable onPress={() => router.back()} style={styles.backBtn}
            accessibilityLabel="Go back" accessibilityRole="button">
            <ArrowLeft size={20} color={colors.text.primary} />
          </Pressable>
          <HeaderBrand />
        </View>
        <ScrollView contentContainerStyle={styles.body}>
          <Text style={styles.title}>WhatsApp settings</Text>
          {!isAdmin ? (
            <Text style={styles.muted}>Only company admins can change WhatsApp settings.</Text>
          ) : state === 'loading' ? (
            <ActivityIndicator color={colors.text.muted} />
          ) : state === 'error' || !view ? (
            <Pressable onPress={load}>
              <Text style={styles.muted}>WhatsApp settings could not be loaded. Tap to try again.</Text>
            </Pressable>
          ) : (
            <>
              <View style={styles.card}>
                <Text style={styles.label}>GC group</Text>
                {view.gc.name ? <Text style={styles.value}>{view.gc.name}</Text> : null}
                <Text style={styles.muted}>{view.gc.line}</Text>
                {view.gc.action && !picking ? (
                  <Pressable onPress={() => setPicking(true)} style={styles.button}
                    accessibilityRole="button">
                    <Text style={styles.buttonText}>{view.gc.action}</Text>
                  </Pressable>
                ) : null}
                {picking ? view.choices.map((c) => (
                  <Pressable key={c.id} onPress={() => pick(c.id)} disabled={!!busy}
                    style={styles.choice} accessibilityRole="button">
                    <Text style={styles.value}>{c.name}</Text>
                    {busy === c.id ? <ActivityIndicator size="small" color={colors.text.muted} />
                      : c.current ? <Check size={16} color="#25D366" /> : null}
                  </Pressable>
                )) : null}
                {picking ? (
                  <Pressable onPress={() => setPicking(false)} style={styles.choice}>
                    <Text style={styles.muted}>Cancel</Text>
                  </Pressable>
                ) : null}
              </View>
              {view.switches.length ? (
                <View style={styles.card}>
                  <Text style={styles.label}>Alerts in the GC group</Text>
                  {view.switches.map((s) => (
                    <View key={s.key} style={styles.switchRow}>
                      <View style={{ flex: 1, marginRight: spacing.sm }}>
                        <Text style={styles.value}>{s.label}</Text>
                        <Text style={styles.muted}>{s.line}</Text>
                      </View>
                      <Switch value={s.value} disabled={!!busy}
                        onValueChange={(v) => toggle(s.key, v)}
                        accessibilityLabel={s.label} />
                    </View>
                  ))}
                  <Text style={styles.muted}>{view.hoursLine}</Text>
                </View>
              ) : null}
            </>
          )}
        </ScrollView>
        <ToastHost />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    safe: { flex: 1, backgroundColor: 'transparent' },
    headerBar: {
      flexDirection: 'row', alignItems: 'center',
      paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
      backgroundColor: colors.glass.background,
      borderBottomWidth: 1, borderBottomColor: colors.glass.border,
    },
    backBtn: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center',
      borderRadius: 18, marginRight: spacing.sm },
    body: { padding: spacing.md, paddingBottom: spacing.xl * 2 },
    title: { color: colors.text.primary, fontSize: 20, fontWeight: '600', marginBottom: spacing.md },
    card: {
      backgroundColor: colors.glass.background, borderColor: colors.glass.border,
      borderWidth: 1, borderRadius: 12, padding: spacing.md, marginBottom: spacing.md,
    },
    label: { color: colors.text.muted, fontSize: 12, fontWeight: '600',
      textTransform: 'uppercase', marginBottom: spacing.xs },
    value: { color: colors.text.primary, fontSize: 15 },
    muted: { color: colors.text.muted, fontSize: 13, marginTop: 4 },
    button: { alignSelf: 'flex-start', marginTop: spacing.sm, paddingVertical: 8,
      paddingHorizontal: 14, borderRadius: 8, borderWidth: 1, borderColor: colors.glass.border },
    buttonText: { color: colors.text.primary, fontSize: 14, fontWeight: '600' },
    choice: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      paddingVertical: 10, borderTopWidth: 1, borderTopColor: colors.glass.border },
    switchRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: spacing.sm },
  });
}
