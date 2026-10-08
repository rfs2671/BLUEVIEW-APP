import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Linking,
  AppState,
  ActivityIndicator,
  Switch,
} from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { MessageCircle, UserPlus, ChevronDown, Check } from 'lucide-react-native';
import { GlassCard } from './GlassCard';
import { useToast } from './Toast';
import { whatsappAPI } from '../utils/api';
import { isOfflineError } from '../utils/offlineState';
import {
  whatsappCardView, needsFreshLink, WA_POLL_MS, WA_POLL_MAX_MS, WA_POLLING_STATES,
} from '../utils/whatsappConnect';
import { BRIEF_OPTIONS, briefRow } from '../utils/whatsappBrief';
import { saveLevelogContact } from '../utils/saveContact';
import { spacing, borderRadius } from '../styles/theme';
import { semantic } from '../styles/semanticColors';
import { useTheme } from '../context/ThemeContext';

// WhatsApp brand color — intentional, not a token.
const WHATSAPP_GREEN = '#25D366';

/**
 * THE ONE WHATSAPP CARD on Integrations (replaces the company card and the
 * "Your WhatsApp" card, which showed two icons and two titles for one thing).
 *
 *   header       Levelog number, company setup chip, Save to Contacts
 *   Levelog Assistant  this person's own updates — Admins and PMs
 *   Groups       every group the Levelog number is in — Admins only
 *
 * What it SAYS comes from utils/whatsappConnect.js (pure, tested). This file
 * only fetches and draws.
 *
 * LIVE REFRESH. Turning on Levelog Assistant happens in another app (WhatsApp). While
 * the screen is open and a START may be on its way — or there is no reading
 * yet — GET /whatsapp/me is read every few seconds, and again on focus and
 * when the app returns to the foreground, so "Off" flips to "On" in place.
 */
export default function WhatsAppCard({ isAdmin = false }) {
  const { colors } = useTheme();
  const s = buildStyles(colors);
  const router = useRouter();
  const toast = useToast();
  const [me, setMe] = useState(null);
  const [status, setStatus] = useState(null);
  // /whatsapp/company-groups, or null until it has loaded.
  const [groupList, setGroupList] = useState(null);
  const [focused, setFocused] = useState(true);
  const [busy, setBusy] = useState(null); // 'activate' | 'contact' | null
  // The single-use, 15-minute "Turn on Levelog Assistant" link. Fetched BEFORE the tap,
  // so the tap opens WhatsApp at once: a browser blocks a window opened
  // after waiting on the network.
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

  const refreshCompany = useCallback(async () => {
    try {
      const st = await whatsappAPI.getStatus();
      if (mounted.current) setStatus(st);
      if (isAdmin && st && st.company_active) {
        const res = await whatsappAPI.getCompanyGroups();
        const rows = (res && Array.isArray(res.groups)) ? res.groups : [];
        if (mounted.current) setGroupList(rows);
      }
    } catch (e) {
      // Leave the last reading in place.
    }
  }, [isAdmin]);

  useFocusEffect(
    useCallback(() => {
      setFocused(true);
      pollStartedAt.current = Date.now();
      refreshMe();
      refreshCompany();
      return () => setFocused(false);
    }, [refreshMe, refreshCompany]),
  );

  // Back from WhatsApp: re-read at once.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'active') {
        pollStartedAt.current = Date.now();
        refreshMe();
        refreshCompany();
      }
    });
    return () => sub && sub.remove && sub.remove();
  }, [refreshMe, refreshCompany]);

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

  // A fresh link whenever alerts can be turned on and the one held is
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

  const view = whatsappCardView({
    me, status, groups: groupList, isAdmin, connectUrl: link && link.url,
  });
  if (!view.visible) return null;

  const openWhatsApp = (url) => {
    pollStartedAt.current = Date.now();
    // The link is kept: until the START arrives the code is unused and
    // still good, and fetching a new one here would race the send.
    Linking.openURL(url);
  };

  const activate = async () => {
    setBusy('activate');
    try {
      await whatsappAPI.activate();
      await refreshCompany();
      toast.success('WhatsApp is on', 'You can now link job groups.');
    } catch (error) {
      if (isOfflineError(error)) {
        toast.error('Offline', 'Turning on WhatsApp needs a connection. Nothing changed.');
      } else {
        toast.error('Could not turn on WhatsApp', error?.response?.data?.detail || 'Please try again.');
      }
    } finally {
      setBusy(null);
    }
  };

  const saveBrief = async (patch) => {
    setBusy('brief');
    try {
      const brief = await whatsappAPI.setBrief(patch);
      if (mounted.current) setMe((m) => (m ? { ...m, brief } : m));
      setBriefOpen(false);
    } catch (error) {
      toast.error('Not saved', isOfflineError(error)
        ? 'Reconnect to change the morning brief.'
        : 'The morning brief could not be changed. Try again.');
    } finally {
      setBusy(null);
    }
  };

  const saveContact = async () => {
    setBusy('contact');
    try {
      const how = await saveLevelogContact({
        phone: view.header.number,
        getVCardText: whatsappAPI.getVCardText,
        downloadVCard: whatsappAPI.downloadVCard,
      });
      if (how === 'downloaded') {
        toast.success('Contact downloaded', 'Open the file to add the Levelog number.');
      } else if (how === 'denied_shared') {
        toast.info('Contacts access is off',
          'Allow it in Settings to add the contact directly. Pick Contacts to save the card.');
      }
    } catch (error) {
      if (isOfflineError(error)) {
        toast.error('Offline', 'Reconnect to save the contact.');
      } else {
        toast.error('Could not save contact', error?.response?.data?.detail || 'Please try again.');
      }
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

  const { header, alerts, groups } = view;
  const brief = briefRow(me);

  return (
    <GlassCard style={s.card}>
      {/* Header: one icon, one title, one chip. */}
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
          {header.canSaveContact ? (
            <Pressable
              onPress={saveContact}
              disabled={busy === 'contact'}
              accessibilityRole="button"
              style={({ pressed }) => [s.smallButton, pressed && s.pressed]}
            >
              {busy === 'contact'
                ? <ActivityIndicator size="small" color={colors.text.primary} />
                : (
                  <>
                    <UserPlus size={16} strokeWidth={2} color={colors.text.primary} />
                    <Text style={s.smallButtonText}>Save to Contacts</Text>
                  </>
                )}
            </Pressable>
          ) : null}
        </View>
      ) : null}

      {alerts ? (
        <View style={s.section}>
          <View style={s.sectionHead}>
            <Text style={s.sectionTitle}>Levelog Assistant</Text>
            <Chip c={alerts.chip} />
          </View>
          <Text style={s.line}>{alerts.line}</Text>
          <Text style={s.line}>
            DOB/DOT alert switches are in each project's WhatsApp tab.{' '}
            <Text
              style={s.inlineLink}
              onPress={() => router.push('/projects')}
              accessibilityRole="link"
            >
              Go to projects
            </Text>
          </Text>
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
            </View>
          ) : null}
        </View>
      ) : null}

      {groups ? (
        <View style={s.section}>
          <View style={s.sectionHead}>
            <Text style={s.sectionTitle}>Groups</Text>
          </View>
          {groups.line ? <Text style={s.line}>{groups.line}</Text> : null}
          {groups.rows.map((g) => (
            <View key={g.key} style={s.groupRow}>
              <View style={s.groupText}>
                <Text style={s.groupName}>{g.name}</Text>
                <Text style={[s.groupPlace, g.link && s.groupPlaceMuted]}>{g.place}</Text>
                {g.chip ? (
                  <View style={s.groupChip}><Chip c={g.chip} /></View>
                ) : null}
              </View>
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
            </View>
          ))}
          {groups.action ? (
            <Pressable
              onPress={groups.action.kind === 'activate'
                ? activate
                : () => router.push('/admin/whatsapp-groups')}
              disabled={busy === 'activate'}
              accessibilityRole="button"
              style={({ pressed }) => [s.greenButton, pressed && s.pressed]}
            >
              {busy === 'activate'
                ? <ActivityIndicator size="small" color="#fff" />
                : (
                  <>
                    <Text style={s.greenButtonText}>{groups.action.label}</Text>
                    {groups.action.count ? (
                      <View style={s.badge}>
                        <Text style={s.badgeText}>{groups.action.count}</Text>
                      </View>
                    ) : null}
                  </>
                )}
            </Pressable>
          ) : null}
        </View>
      ) : null}
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
    numberValue: { color: colors.text.primary, fontWeight: '600' },
    section: {
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
      paddingTop: spacing.md,
      marginTop: spacing.md,
    },
    sectionHead: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: spacing.xs,
    },
    sectionTitle: { fontSize: 16, fontWeight: '600', color: colors.text.primary },
    line: { fontSize: 14, color: colors.text.muted, marginBottom: spacing.md },
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
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: spacing.sm,
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
    inlineLink: { color: WHATSAPP_GREEN, fontWeight: '600' },
    groupRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: spacing.sm,
      paddingVertical: spacing.sm,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
    },
    groupText: { flex: 1, minWidth: 0 },
    groupName: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
    groupPlace: { fontSize: 13, color: colors.text.primary, marginTop: 2 },
    groupPlaceMuted: { color: colors.text.muted },
    groupChip: { flexDirection: 'row', marginTop: spacing.xs },
    badge: {
      minWidth: 22,
      height: 22,
      borderRadius: 11,
      paddingHorizontal: 6,
      backgroundColor: '#fff',
      alignItems: 'center',
      justifyContent: 'center',
    },
    badgeText: { fontSize: 12, fontWeight: '700', color: WHATSAPP_GREEN },
    pressed: { opacity: 0.85 },
  });
}
