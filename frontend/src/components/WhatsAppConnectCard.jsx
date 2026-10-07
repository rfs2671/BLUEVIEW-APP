import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Linking,
  AppState,
} from 'react-native';
import { useFocusEffect } from 'expo-router';
import { MessageCircle, CheckCircle, AlertTriangle, XCircle } from 'lucide-react-native';
import { GlassCard } from './GlassCard';
import { whatsappAPI } from '../utils/api';
import {
  whatsappConnectView, WA_POLL_MS, WA_POLL_MAX_MS, WA_POLLING_STATES,
} from '../utils/whatsappConnect';
import { spacing, borderRadius } from '../styles/theme';
import { semantic } from '../styles/semanticColors';
import { useTheme } from '../context/ThemeContext';

// WhatsApp brand color — intentional, not a token (matches integrations.jsx).
const WHATSAPP_GREEN = '#25D366';

/**
 * YOUR WHATSAPP — the personal opt-in, for company Admins and PMs.
 *
 * Not the company integration above it (which links GROUPS). This is one
 * person's direct-message updates: the button opens their own WhatsApp with
 * START typed to the Blueview number, and the opt-in is recorded only when
 * that message ARRIVES from the phone on their record.
 *
 * WHY IT POLLS. The START happens in another app. While this screen is open
 * and a START may be on its way, GET /whatsapp/me is read every few seconds,
 * so the card flips to Connected without the user reloading. It also re-reads
 * when the screen regains focus and when the app returns to the foreground —
 * which is exactly the moment the user comes back from WhatsApp. Polling stops
 * when connected, when the screen loses focus, and after WA_POLL_MAX_MS idle.
 *
 * Renders nothing for anyone the server calls not eligible.
 */
export default function WhatsAppConnectCard() {
  const { colors } = useTheme();
  const s = buildStyles(colors);
  const [me, setMe] = useState(null);
  const [focused, setFocused] = useState(true);
  const pollStartedAt = useRef(Date.now());
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const data = await whatsappAPI.getMe();
      if (mounted.current) setMe(data);
    } catch (e) {
      // Keep the last reading: a dropped poll is not a state change.
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  // Read on focus; stop polling on blur.
  useFocusEffect(
    useCallback(() => {
      setFocused(true);
      pollStartedAt.current = Date.now();
      refresh();
      return () => setFocused(false);
    }, [refresh]),
  );

  // Back from WhatsApp: re-read at once.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'active') {
        pollStartedAt.current = Date.now();
        refresh();
      }
    });
    return () => sub && sub.remove && sub.remove();
  }, [refresh]);

  const state = me && me.state;
  // Poll while a START may be on its way — and while there is no reading at
  // all, so a first request that failed is retried rather than leaving the
  // card hidden until the screen is left and re-entered.
  const shouldPoll = !me || WA_POLLING_STATES.has(state);
  useEffect(() => {
    if (!focused || !shouldPoll) return undefined;
    const id = setInterval(() => {
      if (Date.now() - pollStartedAt.current > WA_POLL_MAX_MS) return;
      refresh();
    }, WA_POLL_MS);
    return () => clearInterval(id);
  }, [focused, shouldPoll, refresh]);

  const view = whatsappConnectView(me);
  if (!view.visible) return null;

  const onConnect = () => {
    pollStartedAt.current = Date.now();
    Linking.openURL(view.button.url);
  };

  const badge = view.tone === 'ok'
    ? { Icon: CheckCircle, color: semantic.verified, box: s.badgeOk, text: s.badgeTextOk }
    : view.tone === 'warn'
      ? { Icon: AlertTriangle, color: semantic.attention, box: s.badgeWarn, text: s.badgeTextWarn }
      : { Icon: XCircle, color: colors.text.muted, box: null, text: null };
  const { Icon } = badge;

  return (
    <GlassCard style={s.card}>
      <View style={s.header}>
        <View style={s.icon}>
          <MessageCircle size={28} strokeWidth={1.5} color={WHATSAPP_GREEN} />
        </View>
        <View style={s.info}>
          <Text style={s.name}>Your WhatsApp</Text>
          <Text style={s.desc}>Project updates sent to your own WhatsApp.</Text>
        </View>
      </View>
      <View style={[s.badge, badge.box]}>
        <Icon size={14} strokeWidth={2} color={badge.color} />
        <Text style={[s.badgeText, badge.text]}>{view.status}</Text>
      </View>
      <Text style={s.line}>{view.line}</Text>
      {view.button ? (
        <Pressable
          onPress={onConnect}
          accessibilityRole="button"
          style={({ pressed }) => [s.button, pressed && s.buttonPressed]}
        >
          <MessageCircle size={20} strokeWidth={2} color="#fff" />
          <Text style={s.buttonText}>{view.button.label}</Text>
        </Pressable>
      ) : null}
    </GlassCard>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    card: { marginBottom: spacing.xl },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
      marginBottom: spacing.md,
    },
    icon: {
      width: 56,
      height: 56,
      borderRadius: borderRadius.lg,
      backgroundColor: 'rgba(37, 211, 102, 0.1)', /* brand: WhatsApp - intentional, not a token */
      alignItems: 'center',
      justifyContent: 'center',
    },
    info: { flex: 1 },
    name: {
      fontSize: 20,
      fontWeight: '600',
      color: colors.text.primary,
      marginBottom: 2,
    },
    desc: { fontSize: 14, color: colors.text.muted },
    badge: {
      flexDirection: 'row',
      alignSelf: 'flex-start',
      alignItems: 'center',
      gap: spacing.xs,
      paddingHorizontal: spacing.sm,
      paddingVertical: spacing.xs,
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: colors.glass.border,
      marginBottom: spacing.sm,
    },
    badgeOk: {
      backgroundColor: semantic.verifiedBg,
      borderColor: semantic.verifiedBorder,
    },
    badgeWarn: {
      backgroundColor: semantic.attentionBg,
      borderColor: semantic.attentionBorder,
    },
    badgeText: { fontSize: 12, fontWeight: '500', color: colors.text.muted },
    badgeTextOk: { color: semantic.verified },
    badgeTextWarn: { color: semantic.attention },
    line: {
      fontSize: 14,
      color: colors.text.primary,
      marginBottom: spacing.md,
    },
    button: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: spacing.sm,
      backgroundColor: WHATSAPP_GREEN,
      borderRadius: borderRadius.lg,
      paddingVertical: spacing.md + 4,
      paddingHorizontal: spacing.xl,
      minHeight: 48,
    },
    buttonPressed: { opacity: 0.85 },
    buttonText: { fontSize: 16, fontWeight: '600', color: '#fff' },
  });
}
