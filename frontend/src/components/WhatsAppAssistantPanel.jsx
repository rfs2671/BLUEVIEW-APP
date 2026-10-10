import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, Pressable, Linking, AppState, ActivityIndicator, Switch,
} from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ChevronDown, Check } from 'lucide-react-native';
import { GlassCard } from './GlassCard';
import { useToast } from './Toast';
import { whatsappAPI } from '../utils/api';
import { isOfflineError } from '../utils/offlineState';
import {
  alertsView, needsFreshLink, WA_POLL_MS, WA_POLL_MAX_MS, WA_POLLING_STATES,
} from '../utils/whatsappConnect';
import { BRIEF_OPTIONS, briefRow } from '../utils/whatsappBrief';
import { spacing, borderRadius } from '../styles/theme';
import { semantic } from '../styles/semanticColors';
import { useTheme } from '../context/ThemeContext';

// WhatsApp brand color — intentional, not a token.
const WHATSAPP_GREEN = '#25D366';

/**
 * PERSONAL ASSISTANT (Integrations → WhatsApp → Personal assistant): this
 * person's own Levelog Assistant — on/off, morning brief time, weekends.
 *
 * What it SAYS comes from utils/whatsappConnect.js and whatsappBrief.js
 * (pure, tested). This file only fetches and draws.
 *
 * LIVE REFRESH. Turning the assistant on happens in another app (WhatsApp).
 * While this screen is open and a START may be on its way — or there is no
 * reading yet — GET /whatsapp/me is read every few seconds, and again on
 * focus and when the app returns to the foreground, so "Off" flips to "On"
 * in place.
 */
export default function WhatsAppAssistantPanel() {
  const { colors } = useTheme();
  const s = buildStyles(colors);
  const toast = useToast();
  const [me, setMe] = useState(null);
  const [focused, setFocused] = useState(true);
  const [busy, setBusy] = useState(null); // 'brief' | null
  // The single-use, 15-minute "Turn on Levelog Assistant" link. Fetched BEFORE
  // the tap, so the tap opens WhatsApp at once: a browser blocks a window
  // opened after waiting on the network.
  const [link, setLink] = useState(null);
  const [briefOpen, setBriefOpen] = useState(false);
  const pollStartedAt = useRef(Date.now());
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const refreshMe = useCallback(async () => {
    try {
      const data = await whatsappAPI.getMe();
      if (mounted.current) setMe(data);
    } catch (e) {
      // Keep the last reading: a dropped poll is not a state change.
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      setFocused(true);
      pollStartedAt.current = Date.now();
      refreshMe();
      return () => setFocused(false);
    }, [refreshMe]),
  );

  // Back from WhatsApp: re-read at once.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'active') {
        pollStartedAt.current = Date.now();
        refreshMe();
      }
    });
    return () => sub && sub.remove && sub.remove();
  }, [refreshMe]);

  const state = me && me.state;
  const shouldPoll = !me || WA_POLLING_STATES.has(state);
  const canTurnOn = !!(me && me.connect_url);

  const refreshLink = useCallback(async () => {
    try {
      const data = await whatsappAPI.connectLink();
      if (mounted.current && data && data.url) setLink(data);
    } catch (e) {
      // Fall back to the plain START link the server already sent.
    }
  }, []);

  // A fresh link whenever the assistant can be turned on and the one held is
  // missing or about to expire.
  useEffect(() => {
    if (!focused || !canTurnOn) return undefined;
    if (needsFreshLink(link)) refreshLink();
    const id = setInterval(() => {
      if (needsFreshLink(link)) refreshLink();
    }, 30 * 1000);
    return () => clearInterval(id);
  }, [focused, canTurnOn, link, refreshLink]);
  useEffect(() => {
    if (!focused || !shouldPoll) return undefined;
    const id = setInterval(() => {
      if (Date.now() - pollStartedAt.current > WA_POLL_MAX_MS) return;
      refreshMe();
    }, WA_POLL_MS);
    return () => clearInterval(id);
  }, [focused, shouldPoll, refreshMe]);

  const alerts = alertsView(me, link && link.url);
  const brief = briefRow(me);

  const openWhatsApp = (url) => {
    pollStartedAt.current = Date.now();
    // The link is kept: until the START arrives the code is unused and
    // still good, and fetching a new one here would race the send.
    Linking.openURL(url);
  };

  const saveBrief = async (patch) => {
    setBusy('brief');
    try {
      const saved = await whatsappAPI.setBrief(patch);
      if (mounted.current) setMe((m) => (m ? { ...m, brief: saved } : m));
      setBriefOpen(false);
    } catch (error) {
      toast.error('Not saved', isOfflineError(error)
        ? 'Reconnect to change the morning brief.'
        : 'The morning brief could not be changed. Try again.');
    } finally {
      setBusy(null);
    }
  };

  const Chip = ({ c }) => (c ? (
    <View style={[s.chip, c.tone === 'ok' && s.chipOk, c.tone === 'warn' && s.chipWarn]}>
      <View style={[s.dot, c.tone === 'ok' && s.dotOk, c.tone === 'warn' && s.dotWarn]} />
      <Text style={[s.chipText, c.tone === 'ok' && s.chipTextOk, c.tone === 'warn' && s.chipTextWarn]}>
        {c.label}
      </Text>
    </View>
  ) : null);

  if (!me) {
    return (
      <GlassCard style={s.card}>
        <ActivityIndicator size="small" color={colors.text.primary} />
      </GlassCard>
    );
  }
  if (!alerts) {
    return (
      <GlassCard style={s.card}>
        <Text style={s.line}>Levelog Assistant is for admins and project managers.</Text>
      </GlassCard>
    );
  }

  return (
    <GlassCard style={s.card}>
      <View style={s.sectionHead}>
        <Text style={s.sectionTitle}>Levelog Assistant</Text>
        <Chip c={alerts.chip} />
      </View>
      <Text style={s.line}>{alerts.line}</Text>
      {alerts.button ? (
        <Pressable
          onPress={() => openWhatsApp(alerts.button.url)}
          accessibilityRole="button"
          style={({ pressed }) => [
            alerts.button.quiet ? s.quietButton : s.greenButton,
            pressed && s.pressed,
          ]}
        >
          <Text style={alerts.button.quiet ? s.quietButtonText : s.greenButtonText}>
            {alerts.button.label}
          </Text>
        </Pressable>
      ) : null}
      {brief ? (
        <View style={s.briefBox}>
          <Pressable
            onPress={() => setBriefOpen((o) => !o)}
            disabled={busy === 'brief'}
            accessibilityRole="button"
            style={({ pressed }) => [s.briefRow, pressed && s.pressed]}
          >
            <Text style={s.briefLabel}>{brief.label}</Text>
            {busy === 'brief'
              ? <ActivityIndicator size="small" color={colors.text.muted} />
              : <ChevronDown size={16} color={colors.text.muted} />}
          </Pressable>
          {briefOpen ? BRIEF_OPTIONS.map((o) => (
            <Pressable
              key={o.value}
              onPress={() => saveBrief({ brief_time: o.value })}
              disabled={busy === 'brief'}
              accessibilityRole="button"
              style={({ pressed }) => [s.briefOption, pressed && s.pressed]}
            >
              <Text style={s.line}>{o.label}</Text>
              {me.brief.brief_time === o.value
                ? <Check size={16} color={WHATSAPP_GREEN} /> : null}
            </Pressable>
          )) : null}
          <Text style={s.line}>{brief.line}</Text>
          <View style={s.briefRow}>
            <Text style={s.line}>Also on weekends</Text>
            <Switch
              value={brief.weekend}
              disabled={busy === 'brief' || brief.weekendDisabled}
              onValueChange={(v) => saveBrief({ brief_weekend: v })}
              accessibilityLabel="Morning brief on Saturday and Sunday"
              trackColor={{ false: colors.glass.border, true: WHATSAPP_GREEN }}
            />
          </View>
          <View style={s.briefRow}>
            <Text style={s.line}>The evening before: what's on tomorrow</Text>
            <Switch
              value={me.brief.upcoming_reminders !== false}
              disabled={busy === 'brief'}
              onValueChange={(v) => saveBrief({ upcoming_reminders: v })}
              accessibilityLabel="A message at 5pm with tomorrow's inspections, deliveries and hearings"
              trackColor={{ false: colors.glass.border, true: WHATSAPP_GREEN }}
            />
          </View>
        </View>
      ) : null}
    </GlassCard>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    card: { marginBottom: spacing.xl },
    sectionHead: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: spacing.xs,
    },
    sectionTitle: { fontSize: 16, fontWeight: '600', color: colors.text.primary },
    line: { fontSize: 14, color: colors.text.muted, marginBottom: spacing.md },
    briefBox: { marginTop: spacing.md },
    briefRow: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      paddingVertical: spacing.xs,
    },
    briefLabel: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
    briefOption: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      paddingVertical: spacing.xs, paddingLeft: spacing.md,
    },
    chip: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      paddingHorizontal: spacing.sm,
      paddingVertical: spacing.xs,
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: colors.glass.background,
    },
    chipOk: { backgroundColor: semantic.verifiedBg, borderColor: semantic.verifiedBorder },
    chipWarn: { backgroundColor: semantic.attentionBg, borderColor: semantic.attentionBorder },
    dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.text.muted },
    dotOk: { backgroundColor: semantic.verified },
    dotWarn: { backgroundColor: semantic.attention },
    chipText: { fontSize: 12, fontWeight: '500', color: colors.text.muted },
    chipTextOk: { color: semantic.verified },
    chipTextWarn: { color: semantic.attention },
    greenButton: {
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: WHATSAPP_GREEN,
      borderRadius: borderRadius.lg,
      paddingVertical: spacing.md,
      paddingHorizontal: spacing.xl,
      minHeight: 48,
    },
    greenButtonText: { fontSize: 16, fontWeight: '600', color: '#fff' },
    quietButton: {
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      paddingVertical: spacing.md,
      paddingHorizontal: spacing.xl,
      minHeight: 48,
    },
    quietButtonText: { fontSize: 16, fontWeight: '600', color: colors.text.primary },
    pressed: { opacity: 0.85 },
  });
}
