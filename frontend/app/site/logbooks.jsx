import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft, ClipboardList, BookOpen, Users, FileText,
  Building2, Calendar, CheckCircle, ChevronRight,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SiteNav from '../../src/components/SiteNav';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

const LOG_TABS = [
  { key: 'daily_jobsite', label: 'Daily Jobsite', icon: ClipboardList, color: '#3b82f6' },
  { key: 'toolbox_talk', label: 'Toolbox Talk', icon: BookOpen, color: '#8b5cf6' },
  { key: 'preshift_signin', label: 'Pre-Shift Sign-In', icon: Users, color: '#f59e0b' },
];

export default function SiteLogbooksViewer() {
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading, siteMode, siteProject } = useAuth();

  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('daily_jobsite');
  const [logsByDate, setLogsByDate] = useState({});
  const [expandedDate, setExpandedDate] = useState(null);

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated) {
      router.replace('/login');
    } else if (!siteMode) {
      router.replace('/');
    }
  }, [isAuthenticated, authLoading, siteMode]);

  useEffect(() => {
    if (isAuthenticated && siteMode && siteProject?.id) {
      fetchLogbooks();
    }
  }, [isAuthenticated, siteMode, siteProject]);

  const fetchLogbooks = async () => {
    setLoading(true);
    try {
      const result = await logbooksAPI.getSubmitted(siteProject.id);
      setLogsByDate(result?.dates || {});
    } catch (e) {
      console.error('Failed to fetch logbooks:', e);
      setLogsByDate({});
    } finally {
      setLoading(false);
    }
  };

  // Filter logs by active tab
  const filteredDates = {};
  for (const [date, logs] of Object.entries(logsByDate)) {
    const matching = logs.filter(l => l.log_type === activeTab);
    if (matching.length > 0) {
      filteredDates[date] = matching;
    }
  }

  const sortedDates = Object.keys(filteredDates).sort((a, b) => b.localeCompare(a));

  const formatDate = (dateStr) => {
    try {
      return new Date(dateStr + 'T12:00:00').toLocaleDateString('en-US', {
        weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
      });
    } catch {
      return dateStr;
    }
  };

  // Render log content based on type
  const renderLogContent = (log) => {
    const data = log.data || {};

    if (log.log_type === 'daily_jobsite') {
      return (
        <View style={styles.logContent}>
          {data.weather && (
            <Text style={styles.logField}>
              <Text style={styles.logFieldLabel}>Weather: </Text>{data.weather} {data.weather_temp || ''}
            </Text>
          )}
          {data.general_description && (
            <Text style={styles.logField}>
              <Text style={styles.logFieldLabel}>Description: </Text>{data.general_description}
            </Text>
          )}
          {(data.activities || []).map((act, i) => (
            <View key={i} style={styles.activityRow}>
              <Text style={styles.activityText}>
                {act.company || 'Unknown'} — {act.num_workers || 0} workers — {act.work_description || 'N/A'}
              </Text>
            </View>
          ))}
          {data.equipment_on_site && (
            <Text style={styles.logField}>
              <Text style={styles.logFieldLabel}>Equipment: </Text>
              {Object.entries(data.equipment_on_site).filter(([_, v]) => v).map(([k]) => k.replace(/_/g, ' ')).join(', ') || 'None'}
            </Text>
          )}
          <Text style={styles.signedBy}>Signed by: {log.cp_name || 'N/A'}</Text>
        </View>
      );
    }

    if (log.log_type === 'toolbox_talk') {
      const topics = data.checked_topics || {};
      const topicList = Object.entries(topics).filter(([_, v]) => v).map(([k]) => k.replace(/_/g, ' '));
      const attendees = data.attendees || [];
      return (
        <View style={styles.logContent}>
          {data.location && (
            <Text style={styles.logField}>
              <Text style={styles.logFieldLabel}>Location: </Text>{data.location}
            </Text>
          )}
          {data.performed_by && (
            <Text style={styles.logField}>
              <Text style={styles.logFieldLabel}>Performed By: </Text>{data.performed_by}
            </Text>
          )}
          <Text style={styles.logField}>
            <Text style={styles.logFieldLabel}>Topics ({topicList.length}): </Text>
            {topicList.join(', ') || 'None'}
          </Text>
          <Text style={styles.logField}>
            <Text style={styles.logFieldLabel}>Attendees: </Text>
            {attendees.length} workers
          </Text>
          {attendees.map((a, i) => (
            <Text key={i} style={styles.attendeeText}>
              • {a.name || 'Unknown'} ({a.company || ''}) {a.signed ? '✓' : '—'}
            </Text>
          ))}
          <Text style={styles.signedBy}>Signed by: {log.cp_name || 'N/A'}</Text>
        </View>
      );
    }

    if (log.log_type === 'preshift_signin') {
      const workers = (data.workers || []).filter(w => w.name?.trim());
      return (
        <View style={styles.logContent}>
          <Text style={styles.logField}>
            <Text style={styles.logFieldLabel}>Workers: </Text>{workers.length}
          </Text>
          {workers.map((w, i) => (
            <View key={i} style={styles.workerRow}>
              <Text style={styles.workerName}>{w.name}</Text>
              <Text style={styles.workerDetail}>{w.company} • OSHA: {w.osha_number || 'N/A'}</Text>
              <Text style={styles.workerDetail}>
                Injury: {w.had_injury || '—'} | PPE: {w.inspected_ppe || '—'}
              </Text>
            </View>
          ))}
          <Text style={styles.signedBy}>Signed by: {log.cp_name || 'N/A'}</Text>
        </View>
      );
    }

    return <Text style={styles.logField}>No data available</Text>;
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* Header */}
        <View style={styles.header}>
          <GlassButton
            variant="icon"
            icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={() => router.push('/site')}
          />
          <View style={{ flex: 1 }}>
            <Text style={styles.headerTitle}>Log Books</Text>
            <Text style={styles.headerSub}>Submitted Records</Text>
          </View>
        </View>

        {/* Tabs */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tabScroll}>
          <View style={styles.tabRow}>
            {LOG_TABS.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.key;
              const count = Object.values(logsByDate)
                .flat()
                .filter(l => l.log_type === tab.key).length;

              return (
                <Pressable
                  key={tab.key}
                  onPress={() => { setActiveTab(tab.key); setExpandedDate(null); }}
                  style={[styles.tab, isActive && { backgroundColor: `${tab.color}20`, borderColor: `${tab.color}50` }]}
                >
                  <Icon size={16} strokeWidth={1.5} color={isActive ? tab.color : colors.text.muted} />
                  <Text style={[styles.tabText, isActive && { color: tab.color }]}>{tab.label}</Text>
                  {count > 0 && (
                    <View style={[styles.tabBadge, { backgroundColor: isActive ? tab.color : colors.text.muted }]}>
                      <Text style={styles.tabBadgeText}>{count}</Text>
                    </View>
                  )}
                </Pressable>
              );
            })}
          </View>
        </ScrollView>

        {/* Content */}
        <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
          {loading ? (
            <View style={styles.loadingCenter}>
              <ActivityIndicator size="large" color={colors.text.primary} />
              <Text style={styles.loadingText}>Loading logbooks...</Text>
            </View>
          ) : sortedDates.length === 0 ? (
            <GlassCard style={styles.emptyCard}>
              <FileText size={40} strokeWidth={1} color={colors.text.muted} />
              <Text style={styles.emptyTitle}>No Submitted Logs</Text>
              <Text style={styles.emptyText}>
                Submitted {LOG_TABS.find(t => t.key === activeTab)?.label || ''} entries will appear here.
              </Text>
            </GlassCard>
          ) : (
            sortedDates.map((date) => {
              const logs = filteredDates[date];
              const isExpanded = expandedDate === date;

              return (
                <View key={date}>
                  <Pressable
                    onPress={() => setExpandedDate(isExpanded ? null : date)}
                    style={styles.dateHeader}
                  >
                    <Calendar size={16} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={styles.dateText}>{formatDate(date)}</Text>
                    <View style={styles.dateBadge}>
                      <CheckCircle size={12} strokeWidth={2} color="#4ade80" />
                      <Text style={styles.dateBadgeText}>{logs.length}</Text>
                    </View>
                    <ChevronRight
                      size={16} strokeWidth={1.5} color={colors.text.muted}
                      style={isExpanded ? { transform: [{ rotate: '90deg' }] } : {}}
                    />
                  </Pressable>

                  {isExpanded && logs.map((log, idx) => (
                    <GlassCard key={log.id || idx} style={styles.logCard}>
                      <View style={styles.logHeader}>
                        <Text style={styles.logType}>
                          {LOG_TABS.find(t => t.key === log.log_type)?.label || log.log_type}
                        </Text>
                        <Text style={styles.logTime}>
                          {log.created_at ? new Date(log.created_at).toLocaleTimeString('en-US', {
                            hour: 'numeric', minute: '2-digit', hour12: true,
                          }) : ''}
                        </Text>
                      </View>
                      {renderLogContent(log)}
                    </GlassCard>
                  ))}
                </View>
              );
            })
          )}
        </ScrollView>

        <SiteNav />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.md,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  headerTitle: { fontSize: 17, fontWeight: '600', color: colors.text.primary },
  headerSub: { fontSize: 12, color: colors.text.muted },

  // Tabs
  tabScroll: { flexGrow: 0, marginBottom: spacing.sm },
  tabRow: { flexDirection: 'row', gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.xs },
  tab: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.xs,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: borderRadius.full, borderWidth: 1, borderColor: colors.glass.border,
    backgroundColor: colors.glass.background,
  },
  tabText: { fontSize: 13, fontWeight: '500', color: colors.text.muted },
  tabBadge: {
    minWidth: 18, height: 18, borderRadius: 9, alignItems: 'center', justifyContent: 'center',
    paddingHorizontal: 4,
  },
  tabBadgeText: { fontSize: 10, fontWeight: '700', color: '#fff' },

  // Content
  scrollView: { flex: 1 },
  scrollContent: { padding: spacing.lg, paddingBottom: 120 },
  loadingCenter: { alignItems: 'center', paddingVertical: spacing.xxl, gap: spacing.md },
  loadingText: { fontSize: 14, color: colors.text.muted },

  // Empty
  emptyCard: { alignItems: 'center', padding: spacing.xl, gap: spacing.md },
  emptyTitle: { fontSize: 16, fontWeight: '500', color: colors.text.primary },
  emptyText: { fontSize: 13, color: colors.text.muted, textAlign: 'center' },

  // Date rows
  dateHeader: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    paddingVertical: spacing.md, paddingHorizontal: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: colors.glass.border,
  },
  dateText: { flex: 1, fontSize: 15, fontWeight: '500', color: colors.text.primary },
  dateBadge: {
    flexDirection: 'row', alignItems: 'center', gap: 3,
    backgroundColor: 'rgba(74,222,128,0.12)', paddingHorizontal: spacing.sm, paddingVertical: 2,
    borderRadius: borderRadius.full,
  },
  dateBadgeText: { fontSize: 11, fontWeight: '600', color: '#4ade80' },

  // Log card
  logCard: { marginTop: spacing.sm, marginBottom: spacing.sm, padding: spacing.md },
  logHeader: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    marginBottom: spacing.sm, paddingBottom: spacing.xs,
    borderBottomWidth: 1, borderBottomColor: colors.glass.border,
  },
  logType: { fontSize: 14, fontWeight: '600', color: colors.text.primary },
  logTime: { fontSize: 12, color: colors.text.muted },

  // Log content
  logContent: { gap: spacing.xs },
  logField: { fontSize: 13, color: colors.text.secondary, lineHeight: 20 },
  logFieldLabel: { fontWeight: '600', color: colors.text.primary },
  signedBy: { fontSize: 12, color: '#4ade80', fontWeight: '500', marginTop: spacing.sm },

  // Activity
  activityRow: {
    paddingLeft: spacing.sm, paddingVertical: 2,
    borderLeftWidth: 2, borderLeftColor: 'rgba(59,130,246,0.3)', marginVertical: 2,
  },
  activityText: { fontSize: 13, color: colors.text.secondary },

  // Attendee
  attendeeText: { fontSize: 12, color: colors.text.muted, paddingLeft: spacing.sm },

  // Worker
  workerRow: { paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.04)' },
  workerName: { fontSize: 14, fontWeight: '500', color: colors.text.primary },
  workerDetail: { fontSize: 12, color: colors.text.muted },
});
