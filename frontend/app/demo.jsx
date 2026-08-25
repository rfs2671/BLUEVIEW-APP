import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Linking } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Lock, Mail, Building2, ShieldCheck } from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard } from '../src/components/GlassCard';
import GlassButton from '../src/components/GlassButton';
import HeaderBrand from '../src/components/HeaderBrand';
import { useAuth } from '../src/context/AuthContext';
import { useTheme } from '../src/context/ThemeContext';
import { demoAPI } from '../src/utils/api';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import { semantic, withAlpha } from '../src/styles/semanticColors';

// Contact/email only — deliberately NOT a web page that sells or processes
// payment (App Store 3.1.1). Change this address to your activation inbox.
const ACTIVATION_EMAIL = 'activate@blueviewbuilders.com';

export default function DemoScreen() {
  const router = useRouter();
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const { user, isAuthenticated, isPending, isLoading: authLoading, logout } = useAuth();

  const [demo, setDemo] = useState(null);
  const [loading, setLoading] = useState(true);

  // Only pending accounts belong here. Approved → dashboard; logged out → login.
  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated) router.replace('/login');
    else if (!isPending) router.replace('/');
  }, [authLoading, isAuthenticated, isPending]);

  useEffect(() => {
    (async () => {
      try {
        setDemo(await demoAPI.getProject());
      } catch (e) {
        setDemo(null);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const contactToActivate = () => {
    const subject = encodeURIComponent('Activate my Blueview account');
    const body = encodeURIComponent(
      `Please activate full access for my account (${user?.email || ''}).`,
    );
    Linking.openURL(`mailto:${ACTIVATION_EMAIL}?subject=${subject}&body=${body}`);
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <View style={s.header}>
          <HeaderBrand />
          <Pressable onPress={logout} hitSlop={8}><Text style={s.logout}>Log out</Text></Pressable>
        </View>

        <ScrollView style={s.scroll} contentContainerStyle={s.content} showsVerticalScrollIndicator={false}>
          {/* Activation CTA — the primary action for a pending account. */}
          <GlassCard style={s.ctaCard}>
            <View style={s.ctaIcon}><Lock size={22} strokeWidth={1.5} color={semantic.attention} /></View>
            <Text style={s.ctaTitle}>Your account is pending activation</Text>
            <Text style={s.ctaBody}>
              You're viewing a read-only demo. Full access — real projects, DOB
              monitoring, document AI, and reports — unlocks once your account is
              activated.
            </Text>
            <GlassButton
              title="Contact to activate full access"
              icon={<Mail size={18} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={contactToActivate}
              style={s.ctaBtn}
            />
            <Text style={s.ctaEmail}>{ACTIVATION_EMAIL}</Text>
          </GlassCard>

          <Text style={s.sectionLabel}>DEMO PROJECT</Text>

          {loading ? (
            <View style={s.loading}><ActivityIndicator size="small" color={colors.text.primary} /></View>
          ) : !demo ? (
            <GlassCard style={s.card}><Text style={s.muted}>Demo unavailable offline.</Text></GlassCard>
          ) : (
            <>
              <GlassCard style={s.card}>
                <View style={s.projRow}>
                  <Building2 size={20} strokeWidth={1.5} color="#3b82f6" />
                  <View style={{ flex: 1 }}>
                    <Text style={s.projName}>{demo.name}</Text>
                    <Text style={s.projAddr}>{demo.address}</Text>
                  </View>
                </View>
                <View style={s.summaryRow}>
                  {[['Permits', demo.dob_summary?.permits], ['Violations', demo.dob_summary?.violations],
                    ['Complaints', demo.dob_summary?.complaints], ['Inspections', demo.dob_summary?.inspections]]
                    .map(([label, val]) => (
                      <View key={label} style={s.summaryCell}>
                        <Text style={s.summaryVal}>{val ?? 0}</Text>
                        <Text style={s.summaryLabel} numberOfLines={1}>{label}</Text>
                      </View>
                    ))}
                </View>
              </GlassCard>

              <GlassCard style={s.card}>
                <Text style={s.cardLabel}>RECENT ACTIVITY</Text>
                {(demo.recent_activity || []).map((a, i) => (
                  <View key={i} style={s.activityRow}>
                    <Text style={s.activityTitle} numberOfLines={1}>{a.title}</Text>
                    <Text style={s.activityMeta}>{a.status} · {a.date}</Text>
                  </View>
                ))}
              </GlassCard>

              <GlassCard style={s.card}>
                <Text style={s.cardLabel}>SPECIAL INSPECTIONS (SAMPLE)</Text>
                {(demo.special_inspections || []).map((si, i) => (
                  <View key={i} style={s.siRow}>
                    <ShieldCheck size={14} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={s.siText}>{si.inspection_type}</Text>
                    <Text style={s.siStatus}>{si.status}</Text>
                  </View>
                ))}
              </GlassCard>
            </>
          )}
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: { flex: 1 },
    header: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    },
    logout: { color: colors.text.muted, fontSize: 13, fontFamily: typography.medium },
    scroll: { flex: 1 },
    content: { paddingHorizontal: spacing.lg, paddingBottom: 60 },
    ctaCard: { alignItems: 'center', paddingVertical: spacing.xl, marginBottom: spacing.lg },
    ctaIcon: {
      width: 48, height: 48, borderRadius: 24, alignItems: 'center', justifyContent: 'center',
      backgroundColor: withAlpha('#94a3b8', 0.15), marginBottom: spacing.md,
    },
    ctaTitle: { fontSize: 18, fontWeight: '600', color: colors.text.primary, textAlign: 'center', marginBottom: spacing.sm },
    ctaBody: { fontSize: 14, lineHeight: 20, color: colors.text.secondary, textAlign: 'center', maxWidth: 420, marginBottom: spacing.lg },
    ctaBtn: { minWidth: 240 },
    ctaEmail: { fontSize: 12, color: colors.text.muted, marginTop: spacing.sm },
    sectionLabel: { fontSize: 11, letterSpacing: 1.5, color: colors.text.muted, fontFamily: typography.medium, marginBottom: spacing.md },
    loading: { paddingVertical: spacing.xl, alignItems: 'center' },
    card: { padding: spacing.lg, marginBottom: spacing.md },
    muted: { color: colors.text.muted, fontSize: 13 },
    projRow: { flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start', marginBottom: spacing.md },
    projName: { fontSize: 16, fontWeight: '600', color: colors.text.primary },
    projAddr: { fontSize: 13, color: colors.text.muted, marginTop: 2 },
    summaryRow: { flexDirection: 'row', gap: spacing.sm },
    summaryCell: { flex: 1, alignItems: 'center' },
    summaryVal: { fontSize: 22, fontWeight: '300', color: colors.text.primary },
    summaryLabel: { alignSelf: 'stretch', fontSize: 11, textAlign: 'center', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.3 },
    cardLabel: { fontSize: 11, letterSpacing: 1, color: colors.text.muted, fontFamily: typography.medium, marginBottom: spacing.sm },
    activityRow: { paddingVertical: 6, borderTopWidth: 1, borderTopColor: colors.glass.border },
    activityTitle: { fontSize: 14, color: colors.text.primary },
    activityMeta: { fontSize: 12, color: colors.text.muted, marginTop: 2 },
    siRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 5 },
    siText: { flex: 1, fontSize: 13, color: colors.text.secondary },
    siStatus: { fontSize: 11, color: semantic.attention, textTransform: 'uppercase' },
  });
}
