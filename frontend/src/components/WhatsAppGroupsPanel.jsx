import React, { useCallback, useRef, useState, useEffect } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { ChevronRight } from 'lucide-react-native';
import { GlassCard } from './GlassCard';
import { useToast } from './Toast';
import { whatsappAPI } from '../utils/api';
import { isOfflineError } from '../utils/offlineState';
import { groupsView, projectWhatsAppPath } from '../utils/whatsappConnect';
import { spacing, borderRadius } from '../styles/theme';
import { semantic } from '../styles/semanticColors';
import { useTheme } from '../context/ThemeContext';

// WhatsApp brand color — intentional, not a token.
const WHATSAPP_GREEN = '#25D366';

/**
 * PROJECT GROUPS (Integrations → WhatsApp → Project groups): every group the
 * Levelog number is in — its WhatsApp name, the job's address, and what it
 * is to that job. A row opens that project's WhatsApp tab (the same page as
 * Projects → job → WhatsApp), where admins set the alert switches; a PM
 * sees it read-only there.
 *
 * `canLink` (owner, admin, CP): groups not linked yet appear with a Link
 * button, and WhatsApp can be turned on for the company. A PM sees only the
 * linked groups of their own projects (the server decides that).
 */
export default function WhatsAppGroupsPanel({ canLink = false }) {
  const { colors } = useTheme();
  const s = buildStyles(colors);
  const router = useRouter();
  const toast = useToast();
  const [status, setStatus] = useState(null);
  const [groupList, setGroupList] = useState(null);
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const st = await whatsappAPI.getStatus();
      if (mounted.current) setStatus(st);
      if (st && st.company_active) {
        const res = await whatsappAPI.getCompanyGroups();
        const rows = (res && Array.isArray(res.groups)) ? res.groups : [];
        if (mounted.current) setGroupList(rows);
      }
    } catch (e) {
      // Leave the last reading in place.
    }
  }, []);

  useFocusEffect(useCallback(() => { refresh(); }, [refresh]));

  const activate = async () => {
    setBusy(true);
    try {
      await whatsappAPI.activate();
      await refresh();
      toast.success('WhatsApp is on', 'You can now link job groups.');
    } catch (error) {
      if (isOfflineError(error)) {
        toast.error('Offline', 'Turning on WhatsApp needs a connection. Nothing changed.');
      } else {
        toast.error('Could not turn on WhatsApp', error?.response?.data?.detail || 'Please try again.');
      }
    } finally {
      setBusy(false);
    }
  };

  const view = groupsView({ status, groups: groupList, canLink });

  const Chip = ({ c }) => (c ? (
    <View style={[s.chip, c.tone === 'ok' && s.chipOk, c.tone === 'warn' && s.chipWarn]}>
      <View style={[s.dot, c.tone === 'ok' && s.dotOk, c.tone === 'warn' && s.dotWarn]} />
      <Text style={[s.chipText, c.tone === 'ok' && s.chipTextOk, c.tone === 'warn' && s.chipTextWarn]}>
        {c.label}
      </Text>
    </View>
  ) : null);

  if (!view) {
    return (
      <GlassCard style={s.card}>
        <ActivityIndicator size="small" color={colors.text.primary} />
      </GlassCard>
    );
  }

  return (
    <GlassCard style={s.card}>
      {view.line ? <Text style={s.line}>{view.line}</Text> : null}
      {view.rows.map((g) => {
        // A PM (no linking) reads the project tab view-only.
        const path = projectWhatsAppPath(g.projectId, { readOnly: !canLink });
        const body = (
          <>
            <View style={s.groupText}>
              <Text style={s.groupName}>{g.name}</Text>
              <Text style={[s.groupPlace, !path && s.groupPlaceMuted]}>{g.place}</Text>
              {g.chip ? <View style={s.groupChip}><Chip c={g.chip} /></View> : null}
            </View>
            {path ? <ChevronRight size={18} color={colors.text.muted} /> : null}
            {g.link ? (
              <Pressable
                onPress={() => router.push('/admin/whatsapp-groups')}
                accessibilityRole="button"
                accessibilityLabel={`Link ${g.name} to a job`}
                style={({ pressed }) => [s.smallButton, pressed && s.pressed]}
              >
                <Text style={s.smallButtonText}>Link</Text>
              </Pressable>
            ) : null}
          </>
        );
        return path ? (
          <Pressable
            key={g.key}
            onPress={() => router.push(path)}
            accessibilityRole="button"
            accessibilityLabel={`${g.name}, ${g.place}`}
            style={({ pressed }) => [s.groupRow, pressed && s.pressed]}
          >
            {body}
          </Pressable>
        ) : (
          <View key={g.key} style={s.groupRow}>{body}</View>
        );
      })}
      {view.action ? (
        <Pressable
          onPress={activate}
          disabled={busy}
          accessibilityRole="button"
          style={({ pressed }) => [s.greenButton, pressed && s.pressed]}
        >
          {busy
            ? <ActivityIndicator size="small" color="#fff" />
            : <Text style={s.greenButtonText}>{view.action.label}</Text>}
        </Pressable>
      ) : null}
    </GlassCard>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    card: { marginBottom: spacing.xl },
    line: { fontSize: 14, color: colors.text.muted, marginBottom: spacing.md },
    groupRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: spacing.sm,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
      minHeight: 56,
    },
    groupText: { flex: 1, minWidth: 0 },
    groupName: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
    groupPlace: { fontSize: 13, color: colors.text.primary, marginTop: 2 },
    groupPlaceMuted: { color: colors.text.muted },
    groupChip: { flexDirection: 'row', marginTop: spacing.xs },
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
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: colors.glass.border,
      paddingVertical: spacing.xs,
      paddingHorizontal: spacing.md,
      minHeight: 44,
    },
    smallButtonText: { fontSize: 14, fontWeight: '500', color: colors.text.primary },
    greenButton: {
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: WHATSAPP_GREEN,
      borderRadius: borderRadius.lg,
      paddingVertical: spacing.md,
      paddingHorizontal: spacing.xl,
      minHeight: 48,
      marginTop: spacing.md,
    },
    greenButtonText: { fontSize: 16, fontWeight: '600', color: '#fff' },
    pressed: { opacity: 0.85 },
  });
}
