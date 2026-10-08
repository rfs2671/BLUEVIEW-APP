import React, { useCallback, useRef, useState, useEffect } from 'react';
import { View, Text, StyleSheet, Pressable, Linking } from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { MessageCircle, UserPlus, ChevronRight } from 'lucide-react-native';
import { GlassCard } from './GlassCard';
import { whatsappAPI } from '../utils/api';
import { whatsappCardView } from '../utils/whatsappConnect';
import { spacing, borderRadius } from '../styles/theme';
import { semantic } from '../styles/semanticColors';
import { useTheme } from '../context/ThemeContext';

// WhatsApp brand color — intentional, not a token.
const WHATSAPP_GREEN = '#25D366';

/**
 * THE ONE WHATSAPP CARD on Integrations: Connected status, the Levelog
 * number, Save to Contacts, and two buttons — nothing else.
 *
 *   Project groups      → app/whatsapp/groups.jsx (Admins and PMs)
 *   Personal assistant  → app/whatsapp/assistant.jsx (when the assistant
 *                         is for this person)
 *
 * Save to Contacts opens WhatsApp with "contact" typed to the Levelog number;
 * the bot answers with its contact card (backend lib/wa_contact.py).
 *
 * What it SAYS comes from utils/whatsappConnect.js (pure, tested). This file
 * only fetches and draws.
 */
export default function WhatsAppCard({ isAdmin = false }) {
  const { colors } = useTheme();
  const s = buildStyles(colors);
  const router = useRouter();
  const [me, setMe] = useState(null);
  const [status, setStatus] = useState(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const data = await whatsappAPI.getMe();
      if (mounted.current) setMe(data);
    } catch (e) { /* keep the last reading */ }
    try {
      const st = await whatsappAPI.getStatus();
      if (mounted.current) setStatus(st);
    } catch (e) { /* keep the last reading */ }
  }, []);

  useFocusEffect(useCallback(() => { refresh(); }, [refresh]));

  const view = whatsappCardView({ me, status, isAdmin });
  if (!view.visible) return null;
  const { header, groupsButton, assistantButton } = view;

  const Chip = ({ c }) => (c ? (
    <View style={[s.chip, c.tone === 'ok' && s.chipOk, c.tone === 'warn' && s.chipWarn]}>
      <View style={[s.dot, c.tone === 'ok' && s.dotOk, c.tone === 'warn' && s.dotWarn]} />
      <Text style={[s.chipText, c.tone === 'ok' && s.chipTextOk, c.tone === 'warn' && s.chipTextWarn]}>
        {c.label}
      </Text>
    </View>
  ) : null);

  const NavButton = ({ b }) => (
    <Pressable
      onPress={() => router.push(b.path)}
      accessibilityRole="button"
      style={({ pressed }) => [s.navButton, pressed && s.pressed]}
    >
      <Text style={s.navButtonText}>{b.label}</Text>
      <View style={s.navRight}>
        <Chip c={b.chip} />
        <ChevronRight size={18} color={colors.text.muted} />
      </View>
    </Pressable>
  );

  return (
    <GlassCard style={s.card}>
      <View style={s.headerRow}>
        <View style={s.icon}>
          <MessageCircle size={26} strokeWidth={1.5} color={WHATSAPP_GREEN} />
        </View>
        <Text style={s.title}>WhatsApp</Text>
        <Chip c={header.chip} />
      </View>
      {header.number ? (
        <View style={s.numberRow}>
          <Text style={s.numberText}>
            Levelog number: <Text style={s.numberValue}>{header.number}</Text>
          </Text>
          {header.contactUrl ? (
            <Pressable
              onPress={() => Linking.openURL(header.contactUrl)}
              accessibilityRole="button"
              accessibilityHint="Opens WhatsApp; Levelog Assistant replies with its contact card"
              style={({ pressed }) => [s.smallButton, pressed && s.pressed]}
            >
              <UserPlus size={16} strokeWidth={2} color={colors.text.primary} />
              <Text style={s.smallButtonText}>Save to Contacts</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
      <View style={s.buttons}>
        <NavButton b={groupsButton} />
        {assistantButton ? <NavButton b={assistantButton} /> : null}
      </View>
    </GlassCard>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    card: { marginBottom: spacing.xl },
    headerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
      marginBottom: spacing.sm,
    },
    icon: {
      width: 44,
      height: 44,
      borderRadius: borderRadius.lg,
      backgroundColor: 'rgba(37, 211, 102, 0.1)', /* brand: WhatsApp - intentional, not a token */
      alignItems: 'center',
      justifyContent: 'center',
    },
    title: { flex: 1, fontSize: 20, fontWeight: '600', color: colors.text.primary },
    numberRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: spacing.sm,
      marginBottom: spacing.sm,
    },
    numberText: { fontSize: 14, color: colors.text.muted },
    numberValue: { color: colors.text.primary, fontWeight: '600' },
    buttons: {
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
      marginTop: spacing.sm,
      paddingTop: spacing.sm,
      gap: spacing.sm,
    },
    navButton: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: spacing.sm,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      paddingVertical: spacing.md,
      paddingHorizontal: spacing.lg,
      minHeight: 56,
    },
    navButtonText: { fontSize: 16, fontWeight: '600', color: colors.text.primary },
    navRight: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
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
    smallButton: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: colors.glass.border,
      paddingVertical: spacing.xs,
      paddingHorizontal: spacing.md,
      minHeight: 44,
    },
    smallButtonText: { fontSize: 14, fontWeight: '500', color: colors.text.primary },
    pressed: { opacity: 0.85 },
  });
}
