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
  Briefcase,
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
 * Per-project subcontractor roster editor.
 *
 * Each entry pairs a trade (HVAC, Electrical, etc.) with the specific
 * company doing that trade on this project. Workers pick one combined
 * entry from the NFC check-in dropdown — both their `trade` and
 * `company` fields get populated from it. No free-text.
 */

const TRADE_SUGGESTIONS = [
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
  const [assignments, setAssignments] = useState([]); // [{trade, company}]
  const [newTrade, setNewTrade] = useState('');
  const [newCompany, setNewCompany] = useState('');
  const [showSuggest, setShowSuggest] = useState(false);
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
      const rows = Array.isArray(data.trade_assignments)
        ? data.trade_assignments
        : [];
      setAssignments(
        rows
          .filter(
            (r) => r && typeof r === 'object' && r.trade && r.company
          )
          .map((r) => ({
            trade: String(r.trade).trim(),
            company: String(r.company).trim(),
          }))
      );
      setDirty(false);
    } catch (err) {
      console.error('Failed to fetch project:', err);
      toast.error('Error', 'Could not load project');
    } finally {
      setLoading(false);
    }
  };

  const addAssignment = () => {
    const t = newTrade.trim();
    const c = newCompany.trim();
    if (!t || !c) {
      toast.warning('Required', 'Enter both trade and company');
      return;
    }
    const dup = assignments.some(
      (a) =>
        a.trade.toLowerCase() === t.toLowerCase() &&
        a.company.toLowerCase() === c.toLowerCase()
    );
    if (dup) {
      toast.info('Already added', `${t} — ${c} is already in the list`);
      return;
    }
    setAssignments([...assignments, { trade: t, company: c }]);
    setDirty(true);
    setNewTrade('');
    setNewCompany('');
  };

  const removeAssignment = (idx) => {
    setAssignments(assignments.filter((_, i) => i !== idx));
    setDirty(true);
  };

  const pickSuggestion = (trade) => {
    setNewTrade(trade);
    setShowSuggest(false);
  };

  const save = async () => {
    setSaving(true);
    try {
      const cleaned = assignments
        .map((a) => ({
          trade: String(a.trade || '').trim(),
          company: String(a.company || '').trim(),
        }))
        .filter((a) => a.trade && a.company);
      await projectsAPI.update(projectId, { trade_assignments: cleaned });
      toast.success('Saved', 'Subcontractor roster updated');
      setDirty(false);
    } catch (err) {
      console.error('Failed to save:', err);
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
              Only administrators can edit a project's subcontractor roster.
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
              <Text style={s.infoTitle}>Subcontractor roster</Text>
              <Text style={s.infoDesc}>
                Pair each trade with the specific company doing that trade on
                this project (e.g. HVAC → Air Star, Framing → ODD). Workers
                tapping the NFC tag will pick one entry from the dropdown;
                both their trade and company auto-fill. Custom entries are
                rejected.
              </Text>
            </View>
          </GlassCard>

          <GlassCard style={s.card}>
            <Text style={s.sectionLabel}>ADD AN ASSIGNMENT</Text>

            <View style={s.addGroup}>
              <View style={s.addField}>
                <View style={s.addLabelRow}>
                  <HardHat size={14} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.addLabel}>TRADE</Text>
                </View>
                <TextInput
                  style={s.input}
                  value={newTrade}
                  onChangeText={setNewTrade}
                  placeholder="e.g. HVAC / Mechanical"
                  placeholderTextColor={colors.text.subtle}
                  onFocus={() => setShowSuggest(true)}
                  autoCapitalize="words"
                />
                {showSuggest && (
                  <View style={s.suggestBox}>
                    <ScrollView
                      style={{ maxHeight: 180 }}
                      keyboardShouldPersistTaps="handled"
                    >
                      {TRADE_SUGGESTIONS.filter(
                        (t) =>
                          !newTrade ||
                          t.toLowerCase().includes(newTrade.toLowerCase())
                      ).map((t) => (
                        <Pressable
                          key={t}
                          style={({ pressed }) => [
                            s.suggestItem,
                            pressed && { opacity: 0.7 },
                          ]}
                          onPress={() => pickSuggestion(t)}
                        >
                          <Text style={s.suggestItemText}>{t}</Text>
                        </Pressable>
                      ))}
                    </ScrollView>
                  </View>
                )}
              </View>

              <View style={s.addField}>
                <View style={s.addLabelRow}>
                  <Briefcase size={14} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.addLabel}>COMPANY</Text>
                </View>
                <TextInput
                  style={s.input}
                  value={newCompany}
                  onChangeText={setNewCompany}
                  placeholder="e.g. Air Star"
                  placeholderTextColor={colors.text.subtle}
                  onSubmitEditing={addAssignment}
                  returnKeyType="done"
                  autoCapitalize="words"
                />
              </View>
            </View>

            <Pressable
              style={({ pressed }) => [
                s.addBtn,
                pressed && { opacity: 0.8 },
              ]}
              onPress={addAssignment}
            >
              <Plus size={18} strokeWidth={2} color="#fff" />
              <Text style={s.addBtnText}>Add Assignment</Text>
            </Pressable>
          </GlassCard>

          <GlassCard style={s.card}>
            <Text style={s.sectionLabel}>
              ROSTER ({assignments.length})
            </Text>

            {assignments.length === 0 ? (
              <View style={s.emptyState}>
                <Text style={s.emptyText}>No subcontractors added yet.</Text>
                <Text style={s.emptySubtext}>
                  Workers will not be able to check in until at least one
                  trade/company pair is configured.
                </Text>
              </View>
            ) : (
              <View style={s.rosterList}>
                {assignments.map((a, idx) => (
                  <View key={`${a.trade}|${a.company}|${idx}`} style={s.rosterRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={s.rosterTrade}>{a.trade}</Text>
                      <Text style={s.rosterCompany}>{a.company}</Text>
                    </View>
                    <Pressable
                      onPress={() => removeAssignment(idx)}
                      style={s.rosterRemove}
                      hitSlop={10}
                    >
                      <X size={18} strokeWidth={2} color={colors.text.muted} />
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
    addGroup: {
      gap: spacing.md,
      marginBottom: spacing.md,
    },
    addField: {
      gap: spacing.xs,
    },
    addLabelRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
    },
    addLabel: {
      ...typography.label,
      fontSize: 11,
      color: colors.text.muted,
    },
    input: {
      backgroundColor: 'rgba(255, 255, 255, 0.05)',
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.md,
      color: colors.text.primary,
      fontSize: 15,
    },
    suggestBox: {
      marginTop: spacing.xs,
      backgroundColor: isDark ? '#1a1f2e' : '#ffffff',
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
      overflow: 'hidden',
    },
    suggestItem: {
      paddingVertical: spacing.sm + 2,
      paddingHorizontal: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: colors.border?.subtle || 'rgba(255,255,255,0.05)',
    },
    suggestItemText: {
      fontSize: 14,
      color: colors.text.primary,
    },
    addBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
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
    rosterList: {
      gap: spacing.sm,
    },
    rosterRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
      backgroundColor: 'rgba(255,255,255,0.04)',
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      padding: spacing.md,
    },
    rosterTrade: {
      fontSize: 15,
      fontWeight: '500',
      color: colors.text.primary,
    },
    rosterCompany: {
      fontSize: 13,
      color: colors.text.muted,
      marginTop: 2,
    },
    rosterRemove: {
      padding: spacing.xs,
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
