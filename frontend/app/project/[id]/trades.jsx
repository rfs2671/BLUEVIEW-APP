import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  TextInput,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  HardHat,
  Plus,
  X,
  Save,
  RotateCw,
  ShieldAlert,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import { projectsAPI } from '../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';
import HeaderBrand from '../../../src/components/HeaderBrand';

/**
 * Per-project trade dropdown editor.
 *
 * Workers checking in via NFC pick a trade from this list — no custom
 * input allowed. If the list is empty on the backend, the check-in page
 * falls back to a default set of common construction trades.
 */

const SUGGESTED_TRADES = [
  'General Labor',
  'Carpenter',
  'Electrician',
  'Plumber',
  'HVAC / Mechanical',
  'Ironworker',
  'Mason',
  'Concrete / Cement',
  'Roofer',
  'Painter',
  'Sheet Metal',
  'Operating Engineer',
  'Demolition',
  'Fire Protection / Sprinkler',
  'Drywall / Plasterer',
  'Glazier',
  'Insulator',
  'Foreman / Supervisor',
  'Surveyor',
  'Safety',
];

export default function ProjectTradesScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [project, setProject] = useState(null);
  const [trades, setTrades] = useState([]);
  const [newTrade, setNewTrade] = useState('');
  const [dirty, setDirty] = useState(false);

  const isAdmin = user?.role === 'admin';

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated && projectId) {
      fetchProject();
    }
  }, [isAuthenticated, projectId]);

  const fetchProject = async () => {
    setLoading(true);
    try {
      const data = await projectsAPI.getById(projectId);
      setProject(data);
      setTrades(Array.isArray(data.allowed_trades) ? data.allowed_trades : []);
      setDirty(false);
    } catch (err) {
      console.error('Failed to fetch project:', err);
      toast.error('Error', 'Could not load project');
    } finally {
      setLoading(false);
    }
  };

  const addTrade = (label) => {
    const trimmed = String(label || '').trim();
    if (!trimmed) return;
    if (trades.some((t) => t.toLowerCase() === trimmed.toLowerCase())) {
      toast.info('Already added', `${trimmed} is already in the list`);
      return;
    }
    setTrades([...trades, trimmed]);
    setDirty(true);
    setNewTrade('');
  };

  const removeTrade = (label) => {
    setTrades(trades.filter((t) => t !== label));
    setDirty(true);
  };

  const loadSuggestions = () => {
    // Replace the current list with the default set. Admin can still
    // tweak after.
    const existing = new Set(trades.map((t) => t.toLowerCase()));
    const additions = SUGGESTED_TRADES.filter(
      (t) => !existing.has(t.toLowerCase())
    );
    if (additions.length === 0) {
      toast.info('Already added', 'All suggested trades are already in the list');
      return;
    }
    setTrades([...trades, ...additions]);
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const cleaned = trades
        .map((t) => String(t).trim())
        .filter(Boolean);
      await projectsAPI.update(projectId, { allowed_trades: cleaned });
      toast.success('Saved', 'Trade list updated');
      setDirty(false);
    } catch (err) {
      console.error('Failed to save trades:', err);
      toast.error('Error', err.response?.data?.detail || 'Could not save');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container}>
          <View style={s.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  if (!isAdmin) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container}>
          <View style={s.header}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.back()}
            />
            <HeaderBrand />
          </View>
          <GlassCard style={s.accessDeniedCard}>
            <ShieldAlert size={56} strokeWidth={1} color={colors.status.error} />
            <Text style={s.accessDeniedTitle}>Admin Access Required</Text>
            <Text style={s.accessDeniedDesc}>
              Only administrators can edit a project's trade dropdown.
            </Text>
          </GlassCard>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.back()}
            />
            <HeaderBrand />
          </View>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        >
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>PROJECT SETTINGS</Text>
            <Text style={s.titleText}>Check-in Trades</Text>
            {project?.name && (
              <Text style={s.subtitleText}>{project.name}</Text>
            )}
          </View>

          <GlassCard style={s.infoCard}>
            <HardHat size={24} strokeWidth={1.5} color={colors.text.primary} />
            <View style={s.infoTextWrap}>
              <Text style={s.infoTitle}>What is this?</Text>
              <Text style={s.infoDesc}>
                Workers who tap the NFC check-in tag for this project must
                pick their trade from this dropdown. Custom trades are not
                allowed. Leave the list empty to fall back to a default set
                of common construction trades.
              </Text>
            </View>
          </GlassCard>

          <GlassCard style={s.card}>
            <Text style={s.sectionLabel}>ADD A TRADE</Text>
            <View style={s.addRow}>
              <TextInput
                style={s.input}
                value={newTrade}
                onChangeText={setNewTrade}
                placeholder="e.g. Crane Operator"
                placeholderTextColor={colors.text.subtle}
                onSubmitEditing={() => addTrade(newTrade)}
                returnKeyType="done"
                autoCapitalize="words"
              />
              <Pressable
                style={({ pressed }) => [
                  s.addBtn,
                  pressed && { opacity: 0.8 },
                ]}
                onPress={() => addTrade(newTrade)}
              >
                <Plus size={18} strokeWidth={2} color="#fff" />
                <Text style={s.addBtnText}>Add</Text>
              </Pressable>
            </View>

            <Pressable onPress={loadSuggestions} style={s.suggestLink}>
              <RotateCw size={14} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.suggestLinkText}>Load suggested trades</Text>
            </Pressable>
          </GlassCard>

          <GlassCard style={s.card}>
            <Text style={s.sectionLabel}>
              CURRENT LIST ({trades.length})
            </Text>

            {trades.length === 0 ? (
              <View style={s.emptyState}>
                <Text style={s.emptyText}>No trades configured yet.</Text>
                <Text style={s.emptySubtext}>
                  The check-in page will show a default list of common
                  construction trades until you add one here.
                </Text>
              </View>
            ) : (
              <View style={s.chipList}>
                {trades.map((t) => (
                  <View key={t} style={s.chip}>
                    <Text style={s.chipText}>{t}</Text>
                    <Pressable
                      onPress={() => removeTrade(t)}
                      style={s.chipRemove}
                      hitSlop={8}
                    >
                      <X size={14} strokeWidth={2} color={colors.text.muted} />
                    </Pressable>
                  </View>
                ))}
              </View>
            )}
          </GlassCard>

          <GlassButton
            title={saving ? 'Saving…' : dirty ? 'Save Changes' : 'Saved'}
            icon={
              !saving && dirty ? (
                <Save size={18} strokeWidth={1.5} color={colors.text.primary} />
              ) : null
            }
            onPress={save}
            loading={saving}
            disabled={saving || !dirty}
            style={s.saveBtn}
          />
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: { flex: 1 },
    loadingContainer: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
    },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: 'rgba(255, 255, 255, 0.08)',
    },
    headerLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
    },
    scrollView: { flex: 1 },
    scrollContent: {
      padding: spacing.lg,
      paddingBottom: 120,
    },
    titleSection: { marginBottom: spacing.xl },
    titleLabel: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.sm,
    },
    titleText: {
      fontSize: 38,
      fontWeight: '200',
      color: colors.text.primary,
      letterSpacing: -1,
    },
    subtitleText: {
      fontSize: 14,
      color: colors.text.muted,
      marginTop: spacing.xs,
    },
    infoCard: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: spacing.md,
      padding: spacing.lg,
      marginBottom: spacing.lg,
    },
    infoTextWrap: { flex: 1 },
    infoTitle: {
      fontSize: 15,
      fontWeight: '500',
      color: colors.text.primary,
      marginBottom: spacing.xs,
    },
    infoDesc: {
      fontSize: 13,
      color: colors.text.muted,
      lineHeight: 20,
    },
    card: {
      padding: spacing.lg,
      marginBottom: spacing.lg,
    },
    sectionLabel: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.md,
    },
    addRow: {
      flexDirection: 'row',
      gap: spacing.sm,
      alignItems: 'center',
    },
    input: {
      flex: 1,
      backgroundColor: 'rgba(255, 255, 255, 0.05)',
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.md,
      color: colors.text.primary,
      fontSize: 15,
    },
    addBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      backgroundColor: '#3b82f6',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderRadius: borderRadius.lg,
    },
    addBtnText: {
      color: '#fff',
      fontSize: 14,
      fontWeight: '600',
    },
    suggestLink: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      marginTop: spacing.md,
      alignSelf: 'flex-start',
    },
    suggestLinkText: {
      fontSize: 13,
      color: colors.text.muted,
      textDecorationLine: 'underline',
    },
    emptyState: {
      paddingVertical: spacing.lg,
      alignItems: 'center',
      gap: spacing.xs,
    },
    emptyText: {
      fontSize: 14,
      color: colors.text.muted,
    },
    emptySubtext: {
      fontSize: 12,
      color: colors.text.subtle,
      textAlign: 'center',
      maxWidth: 320,
    },
    chipList: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: spacing.sm,
    },
    chip: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      backgroundColor: 'rgba(255, 255, 255, 0.06)',
      borderWidth: 1,
      borderColor: colors.glass.border,
      paddingLeft: spacing.md,
      paddingRight: spacing.sm,
      paddingVertical: spacing.xs + 2,
      borderRadius: borderRadius.full,
    },
    chipText: {
      fontSize: 13,
      color: colors.text.primary,
    },
    chipRemove: {
      padding: 2,
    },
    saveBtn: {
      marginTop: spacing.md,
    },
    accessDeniedCard: {
      alignItems: 'center',
      paddingVertical: spacing.xxl,
      gap: spacing.md,
      margin: spacing.lg,
    },
    accessDeniedTitle: {
      fontSize: 22,
      fontWeight: '500',
      color: colors.text.primary,
      marginTop: spacing.md,
    },
    accessDeniedDesc: {
      fontSize: 14,
      color: colors.text.muted,
      textAlign: 'center',
      maxWidth: 300,
      lineHeight: 22,
    },
  });
}
