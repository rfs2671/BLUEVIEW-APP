/**
 * Project → WhatsApp → Levelog Assistant (admins only).
 *
 *   GC group: <name>  [Change]
 *   New DOB violations → GC group           on / off
 *   Permit expiry reminders → GC group      on / off
 *   Send alerts: Anytime / Work hours (7 AM–7 PM) / Custom hours
 *
 * Copy and state for each case: src/utils/whatsappSettings.js.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, Pressable, Switch, ActivityIndicator } from 'react-native';
import { Check } from 'lucide-react-native';
import { GlassCard } from '../GlassCard';
import { useToast } from '../Toast';
import { useTheme } from '../../context/ThemeContext';
import { whatsappAPI } from '../../utils/api';
import { spacing, borderRadius } from '../../styles/theme';
import { TimePickerRow } from './GroupConfigPanel';
import {
  assistantView, SEND_WINDOW_OPTIONS, sendWindowLine, cleanSendWindow,
} from '../../utils/whatsappSettings';

// Every half hour, midnight to 11:30 PM, for custom hours.
const ALL_DAY = Array.from({ length: 48 }, (_, i) =>
  `${String(Math.floor(i / 2)).padStart(2, '0')}:${i % 2 ? '30' : '00'}`);

export default function LevelogAssistantCard({ projectId }) {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const toast = useToast();
  const [data, setData] = useState(null);
  const [state, setState] = useState('loading'); // loading | ok | error
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(null);
  const [custom, setCustom] = useState(null); // draft {start, end} while editing

  const load = useCallback(async () => {
    try {
      setData(await whatsappAPI.getProjectSettings(projectId));
      setState('ok');
    } catch (e) {
      setState('error');
    }
  }, [projectId]);

  useEffect(() => { if (projectId) load(); }, [projectId, load]);

  const pick = async (groupId) => {
    setBusy(groupId);
    try {
      await whatsappAPI.setGcGroup(projectId, groupId);
      setPicking(false);
      await load();
    } catch (e) {
      toast.error('Not saved', 'That group could not be set. Try again.');
    } finally {
      setBusy(null);
    }
  };

  const patch = async (key, body) => {
    setBusy(key);
    try {
      setData(await whatsappAPI.setProjectAlerts(projectId, body));
      return true;
    } catch (e) {
      toast.error('Not saved', 'The setting could not be changed. Try again.');
      return false;
    } finally {
      setBusy(null);
    }
  };

  const chooseMode = async (mode) => {
    if (mode === 'custom') {
      const w = (data && data.send_window) || {};
      setCustom({ start: w.start || '07:00', end: w.end || '19:00' });
      return;
    }
    setCustom(null);
    await patch('send_window', { send_window: { mode } });
  };

  const saveCustom = async () => {
    const w = cleanSendWindow({ mode: 'custom', ...custom });
    if (!w) {
      toast.error('Pick two different times', 'Start and end must be different.');
      return;
    }
    if (await patch('send_window', { send_window: w })) setCustom(null);
  };

  const view = assistantView(data);
  return (
    <>
      <Text style={s.heading}>Levelog Assistant</Text>
      <GlassCard style={s.card}>
        {state === 'loading' ? (
          <ActivityIndicator color={colors.text.muted} />
        ) : state === 'error' || !view ? (
          <Pressable onPress={load}>
            <Text style={s.muted}>These settings could not be loaded. Tap to try again.</Text>
          </Pressable>
        ) : (
          <>
            {/* GC group */}
            <View style={s.row}>
              <View style={{ flex: 1 }}>
                <Text style={s.label}>GC group</Text>
                <Text style={s.value}>{view.gc.name || 'Not picked'}</Text>
              </View>
              {view.gc.action && !picking ? (
                <Pressable onPress={() => setPicking(true)} style={s.button} accessibilityRole="button">
                  <Text style={s.buttonText}>{view.gc.action}</Text>
                </Pressable>
              ) : null}
            </View>
            {view.gc.line ? <Text style={s.muted}>{view.gc.line}</Text> : null}
            {picking ? (
              <>
                {view.choices.map((c) => (
                  <Pressable key={c.id} onPress={() => pick(c.id)} disabled={!!busy} style={s.choice}>
                    <Text style={s.value}>{c.name}</Text>
                    {busy === c.id ? <ActivityIndicator size="small" color={colors.text.muted} />
                      : c.current ? <Check size={16} color="#25D366" /> : null}
                  </Pressable>
                ))}
                <Pressable onPress={() => setPicking(false)} style={s.choice}>
                  <Text style={s.muted}>Cancel</Text>
                </Pressable>
              </>
            ) : null}

            {/* The two alerts */}
            {view.switches.map((sw) => (
              <View key={sw.key} style={s.switchRow}>
                <View style={{ flex: 1, marginRight: spacing.sm }}>
                  <Text style={s.value}>{sw.label}</Text>
                  <Text style={s.muted}>{sw.line}</Text>
                </View>
                <Switch
                  value={sw.value}
                  disabled={!!busy}
                  onValueChange={(v) => patch(sw.key, { [sw.key]: v })}
                  accessibilityLabel={sw.label}
                  trackColor={{ false: colors.glass.border, true: colors.primary }}
                  thumbColor={colors.white}
                />
              </View>
            ))}

            {/* When to send */}
            <Text style={[s.label, { marginTop: spacing.md }]}>Send alerts</Text>
            <View style={s.pills}>
              {SEND_WINDOW_OPTIONS.map((o) => {
                const active = custom ? o.mode === 'custom' : view.sendWindow.mode === o.mode;
                return (
                  <Pressable
                    key={o.mode}
                    onPress={() => chooseMode(o.mode)}
                    disabled={!!busy}
                    style={[s.pill, active && s.pillActive]}
                    accessibilityRole="button"
                    accessibilityState={{ selected: active }}
                  >
                    <Text style={[s.pillText, active && s.pillTextActive]}>{o.label}</Text>
                  </Pressable>
                );
              })}
            </View>
            {custom ? (
              <>
                <Text style={s.sub}>Start (Eastern)</Text>
                <TimePickerRow value={custom.start} slots={ALL_DAY} colors={colors}
                  onChange={(v) => setCustom((c) => ({ ...c, start: v }))} />
                <Text style={s.sub}>End (Eastern)</Text>
                <TimePickerRow value={custom.end} slots={ALL_DAY} colors={colors}
                  onChange={(v) => setCustom((c) => ({ ...c, end: v }))} />
                <View style={s.pills}>
                  <Pressable onPress={saveCustom} disabled={!!busy} style={s.button}>
                    <Text style={s.buttonText}>Save hours</Text>
                  </Pressable>
                  <Pressable onPress={() => setCustom(null)} style={s.button}>
                    <Text style={s.muted}>Cancel</Text>
                  </Pressable>
                </View>
              </>
            ) : (
              <Text style={s.muted}>{sendWindowLine(view.sendWindow)}</Text>
            )}
            <Text style={s.muted}>The GC-group question to the main admin follows the same hours.</Text>
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
    row: { flexDirection: 'row', alignItems: 'center' },
    label: { color: colors.text.muted, fontSize: 12, fontWeight: '600' },
    value: { color: colors.text.primary, fontSize: 15 },
    muted: { color: colors.text.muted, fontSize: 13, marginTop: 4 },
    sub: { color: colors.text.muted, fontSize: 11, fontWeight: '600', marginTop: spacing.sm },
    button: {
      paddingVertical: 8, paddingHorizontal: 14, borderRadius: 8,
      borderWidth: 1, borderColor: colors.glass.border,
    },
    buttonText: { color: colors.text.primary, fontSize: 14, fontWeight: '600' },
    choice: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      paddingVertical: 10, borderTopWidth: 1, borderTopColor: colors.glass.border,
    },
    switchRow: {
      flexDirection: 'row', alignItems: 'center', paddingVertical: spacing.sm,
      borderTopWidth: 1, borderTopColor: colors.glass.border, marginTop: spacing.sm,
    },
    pills: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginTop: spacing.xs },
    pill: {
      paddingHorizontal: spacing.md, paddingVertical: spacing.xs + 2,
      borderRadius: borderRadius.full, borderWidth: 1, borderColor: colors.glass.border,
      backgroundColor: colors.glass.background,
    },
    pillActive: { borderColor: colors.primary, backgroundColor: colors.primary + '20' },
    pillText: { fontSize: 12, color: colors.text.secondary },
    pillTextActive: { color: colors.primary, fontWeight: '600' },
  });
}
