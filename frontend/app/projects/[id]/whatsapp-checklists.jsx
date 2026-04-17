import React, { useEffect, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  ClipboardList,
  Check,
  ChevronDown,
  ChevronRight,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import { checklistAPI, whatsappAPI } from '../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';
import HeaderBrand from '../../../src/components/HeaderBrand';

const CATEGORY_COLORS = {
  safety: '#ef4444',
  materials: '#f59e0b',
  coordination: '#3b82f6',
  inspection: '#a855f7',
  other: '#6b7280',
};

const PRIORITY_LABELS = {
  high: 'HIGH',
  medium: 'MED',
  low: 'LOW',
};

// ─── Date bucketing helpers (EST-aware) ──────────────────────────────
const toLocal = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d;
};

const esMidnight = (d) => {
  // Convert to EST midnight for bucketing — use Intl for timezone-correct date
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(d);
  const y = parts.find(p => p.type === 'year').value;
  const mo = parts.find(p => p.type === 'month').value;
  const da = parts.find(p => p.type === 'day').value;
  return `${y}-${mo}-${da}`;
};

const bucketLabel = (dayStr) => {
  const todayStr = esMidnight(new Date());
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const yStr = esMidnight(yesterday);
  if (dayStr === todayStr) return 'TODAY';
  if (dayStr === yStr) return 'YESTERDAY';
  // Format as e.g. "Apr 14, 2026"
  const [y, mo, da] = dayStr.split('-');
  const d = new Date(parseInt(y, 10), parseInt(mo, 10) - 1, parseInt(da, 10));
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).toUpperCase();
};

const formatTime = (iso) => {
  const d = toLocal(iso);
  if (!d) return '';
  return d.toLocaleTimeString('en-US', {
    hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'America/New_York',
  });
};

export default function WhatsAppChecklistsScreen() {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [checklists, setChecklists] = useState([]);
  const [groups, setGroups] = useState([]);
  const [expanded, setExpanded] = useState({});

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated && projectId) fetchData();
  }, [isAuthenticated, projectId]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [listRes, groupsRes] = await Promise.all([
        checklistAPI.getForProject(projectId, { limit: 50 }).catch(() => ({ items: [] })),
        whatsappAPI.getGroups(projectId).catch(() => []),
      ]);
      setChecklists(listRes?.items || []);
      setGroups(Array.isArray(groupsRes) ? groupsRes : []);
      // Auto-expand the most recent
      if ((listRes?.items || []).length > 0) {
        const firstId = listRes.items[0].id || listRes.items[0]._id;
        setExpanded({ [firstId]: true });
      }
    } catch (e) {
      console.error('Failed to load checklists:', e);
      toast.error('Error', 'Could not load action items');
    } finally {
      setLoading(false);
    }
  };

  // Group name lookup: group_id -> pretty name
  const groupNameById = useMemo(() => {
    const m = {};
    (groups || []).forEach((g) => {
      m[g.wa_group_id] = g.group_name || g.name || 'WhatsApp Group';
    });
    return m;
  }, [groups]);

  const toggleExpand = (id) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleToggleItem = async (checklistId, itemIndex, currentCompleted) => {
    const newCompleted = !currentCompleted;
    // Optimistic update
    setChecklists((prev) =>
      prev.map((c) => {
        const cid = c.id || c._id;
        if (cid !== checklistId) return c;
        const items = [...(c.items || [])];
        items[itemIndex] = { ...items[itemIndex], completed: newCompleted };
        return { ...c, items };
      }),
    );
    try {
      await checklistAPI.updateItem(checklistId, itemIndex, { completed: newCompleted });
    } catch (e) {
      // Revert on failure
      setChecklists((prev) =>
        prev.map((c) => {
          const cid = c.id || c._id;
          if (cid !== checklistId) return c;
          const items = [...(c.items || [])];
          items[itemIndex] = { ...items[itemIndex], completed: currentCompleted };
          return { ...c, items };
        }),
      );
      toast.error('Error', e?.response?.data?.detail || 'Could not update item');
    }
  };

  // Bucket checklists by EST date
  const bucketed = useMemo(() => {
    const buckets = {};
    (checklists || []).forEach((c) => {
      const d = toLocal(c.generated_at);
      if (!d) return;
      const key = esMidnight(d);
      if (!buckets[key]) buckets[key] = [];
      buckets[key].push(c);
    });
    // Sort buckets desc
    const ordered = Object.keys(buckets).sort().reverse();
    return ordered.map((k) => ({ key: k, label: bucketLabel(k), checklists: buckets[k] }));
  }, [checklists]);

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
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

        <ScrollView style={s.scroll} contentContainerStyle={s.scrollContent} showsVerticalScrollIndicator={false}>
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>WHATSAPP</Text>
            <Text style={s.titleText}>Action Items</Text>
          </View>

          {loading ? (
            <View style={s.loadingBox}>
              <ActivityIndicator size="large" color={colors.text.primary} />
            </View>
          ) : bucketed.length === 0 ? (
            <GlassCard style={s.emptyCard}>
              <ClipboardList size={48} strokeWidth={1} color={colors.text.subtle} />
              <Text style={s.emptyTitle}>No action items yet</Text>
              <Text style={s.emptyDesc}>
                Enable checklist extraction in WhatsApp group settings, or type{' '}
                <Text style={{ fontWeight: '600', color: colors.text.secondary }}>
                  @levelog checklist
                </Text>{' '}
                in a linked group.
              </Text>
            </GlassCard>
          ) : (
            bucketed.map((bucket) => (
              <View key={bucket.key} style={s.bucketWrap}>
                <Text style={s.bucketLabel}>{bucket.label}</Text>
                {bucket.checklists.map((cl) => {
                  const cid = cl.id || cl._id;
                  const isExpanded = !!expanded[cid];
                  const items = cl.items || [];
                  const completedCount = items.filter((it) => it.completed).length;
                  const gname = groupNameById[cl.group_id] || 'WhatsApp Group';
                  return (
                    <GlassCard key={cid} style={s.card}>
                      <Pressable onPress={() => toggleExpand(cid)} style={s.cardHeader}>
                        <View style={{ flex: 1 }}>
                          <Text style={s.groupName} numberOfLines={1}>{gname}</Text>
                          <Text style={s.timeText}>
                            {formatTime(cl.generated_at)} · {items.length} item{items.length !== 1 ? 's' : ''}
                            {completedCount > 0 ? ` · ${completedCount} done` : ''}
                          </Text>
                        </View>
                        {isExpanded
                          ? <ChevronDown size={18} strokeWidth={1.5} color={colors.text.muted} />
                          : <ChevronRight size={18} strokeWidth={1.5} color={colors.text.muted} />}
                      </Pressable>
                      {isExpanded && (
                        <View style={s.itemsWrap}>
                          {items.map((it, idx) => {
                            const catColor = CATEGORY_COLORS[it.category] || CATEGORY_COLORS.other;
                            const prio = PRIORITY_LABELS[it.priority];
                            return (
                              <Pressable
                                key={`${cid}-${idx}`}
                                onPress={() => handleToggleItem(cid, idx, !!it.completed)}
                                style={({ pressed }) => [s.itemRow, pressed && { opacity: 0.7 }]}
                              >
                                <View
                                  style={[
                                    s.checkbox,
                                    it.completed && { backgroundColor: colors.primary, borderColor: colors.primary },
                                  ]}
                                >
                                  {it.completed && <Check size={12} strokeWidth={3} color="#fff" />}
                                </View>
                                <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: catColor }} />
                                <View style={{ flex: 1 }}>
                                  <Text
                                    style={[
                                      s.itemText,
                                      it.completed && { textDecorationLine: 'line-through', color: colors.text.muted },
                                    ]}
                                  >
                                    {it.text}
                                  </Text>
                                  <View style={s.metaRow}>
                                    {prio && (
                                      <Text style={[s.metaPrio, { color: it.priority === 'high' ? '#ef4444' : it.priority === 'medium' ? '#f59e0b' : colors.text.muted }]}>
                                        {prio}
                                      </Text>
                                    )}
                                    {!!it.assigned_to && (
                                      <Text style={s.metaChip}>{it.assigned_to}</Text>
                                    )}
                                    {!!it.due_date && (
                                      <Text style={s.metaChip}>Due: {it.due_date}</Text>
                                    )}
                                  </View>
                                </View>
                              </Pressable>
                            );
                          })}
                        </View>
                      )}
                    </GlassCard>
                  );
                })}
              </View>
            ))
          )}
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const buildStyles = (colors) =>
  StyleSheet.create({
    container: { flex: 1 },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: 'rgba(255,255,255,0.08)',
    },
    headerLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
    },
    scroll: { flex: 1 },
    scrollContent: { padding: spacing.lg, paddingBottom: 120 },
    titleSection: { marginBottom: spacing.lg },
    titleLabel: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.sm,
    },
    titleText: {
      fontSize: 36,
      fontWeight: '200',
      color: colors.text.primary,
      letterSpacing: -0.5,
    },
    loadingBox: { alignItems: 'center', paddingVertical: spacing.xxl },
    emptyCard: {
      alignItems: 'center',
      paddingVertical: spacing.xxl,
      gap: spacing.md,
    },
    emptyTitle: {
      fontSize: 20,
      fontWeight: '500',
      color: colors.text.primary,
    },
    emptyDesc: {
      fontSize: 14,
      color: colors.text.muted,
      textAlign: 'center',
      maxWidth: 320,
      lineHeight: 22,
    },
    bucketWrap: { marginBottom: spacing.lg },
    bucketLabel: {
      fontSize: 11,
      fontWeight: '700',
      color: colors.text.muted,
      letterSpacing: 1,
      marginBottom: spacing.sm,
    },
    card: { padding: 0, marginBottom: spacing.sm },
    cardHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      padding: spacing.md,
      gap: spacing.sm,
    },
    groupName: {
      fontSize: 15,
      fontWeight: '600',
      color: colors.text.primary,
    },
    timeText: {
      fontSize: 12,
      color: colors.text.muted,
      marginTop: 2,
    },
    itemsWrap: {
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
    },
    itemRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: spacing.sm,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.sm,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
    },
    checkbox: {
      width: 22,
      height: 22,
      borderRadius: 11,
      borderWidth: 2,
      borderColor: colors.glass.border,
      alignItems: 'center',
      justifyContent: 'center',
      marginTop: 2,
    },
    itemText: {
      fontSize: 14,
      color: colors.text.primary,
      lineHeight: 20,
    },
    metaRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: spacing.xs,
      marginTop: 4,
      alignItems: 'center',
    },
    metaPrio: {
      fontSize: 10,
      fontWeight: '700',
      letterSpacing: 0.5,
    },
    metaChip: {
      fontSize: 10,
      color: colors.text.muted,
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: colors.glass.border,
      paddingHorizontal: 8,
      paddingVertical: 2,
    },
  });
