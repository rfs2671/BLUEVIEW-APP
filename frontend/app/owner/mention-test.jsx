import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ShieldAlert, Send } from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import OwnerNav from '../../src/components/OwnerNav';
import OfflineNotice from '../../src/components/OfflineNotice';
import { useToast } from '../../src/components/Toast';
import { useAuth, isPlatformOperator } from '../../src/context/AuthContext';
import { useTheme } from '../../src/context/ThemeContext';
import { ownerAPI } from '../../src/utils/api';
import { settleFetch, isOfflineError } from '../../src/utils/offlineState';
import {
  MENTION_TEST_NOTE, mentionPersonLine, mentionResult, serverMessage,
} from '../../src/utils/ownerPortal';
import { spacing, borderRadius } from '../../src/styles/theme';
import { semantic } from '../../src/styles/semanticColors';

/**
 * OWNER PORTAL → TEST MENTION. Pick a linked WhatsApp group and someone who
 * has written in it; Send posts "@<name> test" there with a real mention, so
 * you can see their phone notify. Nothing is posted when no number can be
 * found for them. Platform operator only (the server answers 404 to anyone
 * else).
 */
export default function OwnerMentionTestScreen() {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const router = useRouter();
  const toast = useToast();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const isOperator = isPlatformOperator(user);
  const [groups, setGroups] = useState([]);
  const [state, setState] = useState('loading');
  const [group, setGroup] = useState(null);
  const [people, setPeople] = useState(null);
  const [peopleState, setPeopleState] = useState('loading');
  // The group whose people are being loaded: a slower answer for a group
  // no longer selected is dropped.
  const pickedRef = useRef(null);
  const [person, setPerson] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState('');

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [authLoading, isAuthenticated]);

  const load = useCallback(async () => {
    if (!isOperator) return;
    const res = await settleFetch(() => ownerAPI.mentionTestGroups());
    setState(res.status);
    if (res.status === 'ok') setGroups(res.data?.groups || []);
  }, [isOperator]);

  useEffect(() => { load(); }, [load]);

  const pickGroup = async (g) => {
    pickedRef.current = g.key;
    setGroup(g);
    setPerson(null);
    setPeople(null);
    setPeopleState('loading');
    setResult('');
    const res = await settleFetch(() => ownerAPI.mentionTestPeople(g.key));
    if (pickedRef.current !== g.key) return;
    setPeopleState(res.status);
    setPeople(res.status === 'ok' ? (res.data?.people || []) : []);
  };

  const send = async () => {
    if (!group || !person) return;
    setBusy(true);
    setResult('');
    try {
      const res = await ownerAPI.sendMentionTest(group.key, person.key);
      setResult(mentionResult(res));
      if (res.sent) toast.success('Test mention posted', res.text);
    } catch (e) {
      setResult(isOfflineError(e) ? 'This needs a connection. Nothing was posted.' : serverMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (!authLoading && isAuthenticated && !isOperator) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <OwnerNav />
          <GlassCard style={s.card}>
            <ShieldAlert size={28} strokeWidth={1.5} color={semantic.attention} />
            <Text style={s.line}>Platform operator access required.</Text>
          </GlassCard>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <OwnerNav title="Test mention" />
        <ScrollView style={s.scroll} contentContainerStyle={s.content}>
          <Text style={s.note}>{MENTION_TEST_NOTE}</Text>

          <Text style={s.label}>Group</Text>
          {state === 'loading' ? (
            <ActivityIndicator size="small" color={colors.text.secondary} />
          ) : state !== 'ok' ? (
            <OfflineNotice mode={state} detail="Linked groups could not be loaded." />
          ) : groups.length === 0 ? (
            <Text style={s.line}>No linked groups.</Text>
          ) : groups.map((g) => (
            <Pressable key={g.key} onPress={() => pickGroup(g)}
              accessibilityRole="radio" accessibilityState={{ selected: group?.key === g.key }}
              style={({ pressed }) => [s.choice, group?.key === g.key && s.choiceOn, pressed && s.pressed]}>
              <Text style={s.name}>{g.name}</Text>
              <Text style={s.meta}>
                {[g.company, g.project, g.bot_on ? '' : 'bot off in this group'].filter(Boolean).join(' · ')}
              </Text>
            </Pressable>
          ))}

          {group ? (
            <>
              <Text style={s.label}>Who to mention</Text>
              {people === null ? (
                <ActivityIndicator size="small" color={colors.text.secondary} />
              ) : peopleState !== 'ok' ? (
                <OfflineNotice mode={peopleState} detail="Who has written in this group could not be loaded." />
              ) : people.length === 0 ? (
                <Text style={s.line}>Nobody has written in this group yet.</Text>
              ) : people.map((p) => (
                <Pressable key={p.key} onPress={() => { setPerson(p); setResult(''); }}
                  accessibilityRole="radio" accessibilityState={{ selected: person?.key === p.key }}
                  style={({ pressed }) => [s.choice, person?.key === p.key && s.choiceOn, pressed && s.pressed]}>
                  <Text style={s.name}>{mentionPersonLine(p)}</Text>
                </Pressable>
              ))}
            </>
          ) : null}

          {group && person ? (
            <Pressable onPress={send} disabled={busy} accessibilityRole="button"
              style={({ pressed }) => [s.send, busy && s.disabled, pressed && s.pressed]}>
              {busy ? <ActivityIndicator size="small" color={colors.text.primary} />
                : <Send size={16} strokeWidth={1.75} color={colors.text.primary} />}
              <Text style={s.sendText}>{`Send "@${person.name} test" to ${group.name}`}</Text>
            </Pressable>
          ) : null}
          {result ? <Text style={s.line}>{result}</Text> : null}
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    container: { flex: 1 },
    scroll: { flex: 1 },
    content: { padding: spacing.lg, paddingBottom: 120, gap: spacing.sm },
    card: { padding: spacing.lg, alignItems: 'center', gap: spacing.sm, margin: spacing.lg },
    note: { fontSize: 13, color: colors.text.secondary, lineHeight: 18 },
    label: {
      fontSize: 12, fontWeight: '700', letterSpacing: 1, color: colors.text.muted,
      textTransform: 'uppercase', marginTop: spacing.md,
    },
    line: { fontSize: 14, color: colors.text.primary, lineHeight: 20 },
    choice: {
      padding: spacing.md, borderRadius: borderRadius.lg,
      borderWidth: 1, borderColor: colors.glass.border, gap: 2,
    },
    choiceOn: { borderColor: colors.text.secondary, backgroundColor: colors.glass.background },
    name: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
    meta: { fontSize: 13, color: colors.text.secondary },
    send: {
      flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 44, marginTop: spacing.md,
      paddingHorizontal: spacing.md, borderRadius: borderRadius.lg,
      borderWidth: 1, borderColor: colors.text.secondary,
    },
    sendText: { fontSize: 14, fontWeight: '600', color: colors.text.primary, flexShrink: 1 },
    disabled: { opacity: 0.55 },
    pressed: { opacity: 0.7 },
  });
}
