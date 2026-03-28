import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Image,
  Linking, Platform,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft, ClipboardList, BookOpen, Users, FileText,
  Building2, Calendar, CheckCircle, ChevronRight, ChevronDown,
  CloudSun, Clock, MapPin, Wrench, ShieldCheck, Eye, Truck,
  AlertTriangle, Pen, XCircle, Download, Share2,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SiteNav from '../../src/components/SiteNav';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, getToken } from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';

const LOG_TABS = [
  { key: 'daily_jobsite', label: 'Daily Jobsite', icon: ClipboardList, color: '#3b82f6' },
  { key: 'toolbox_talk', label: 'Toolbox Talk', icon: BookOpen, color: '#8b5cf6' },
  { key: 'preshift_signin', label: 'Pre-Shift Sign-In', icon: Users, color: '#f59e0b' },
];

export default function SiteLogbooksViewer() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
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

  // PDF handlers
  const BASE_URL = 'https://blueview2-production.up.railway.app';

  const handleViewLogPdf = async (logbookId) => {
    try {
      const token = await getToken();
      const url = `${BASE_URL}/api/reports/logbook/${logbookId}/pdf?token=${token}`;
      await Linking.openURL(url);
    } catch (e) {
      console.error('PDF open failed:', e);
    }
  };

  const handleShareLogPdf = async (logbookId, logType, date) => {
    try {
      const Sharing = require('expo-sharing');
      const FileSystem = require('expo-file-system');
      const token = await getToken();
      const url = `${BASE_URL}/api/reports/logbook/${logbookId}/pdf?token=${token}`;
      const filename = `Blueview_${logType}_${date}.pdf`;
      const fileUri = FileSystem.cacheDirectory + filename;
      const download = await FileSystem.downloadAsync(url, fileUri);
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(download.uri, { mimeType: 'application/pdf', dialogTitle: 'Share Logbook PDF' });
      }
    } catch (e) {
      console.error('PDF share failed:', e);
    }
  };

  const handleCombinedPdf = async (date) => {
    try {
      const token = await getToken();
      const url = `${BASE_URL}/api/reports/project/${siteProject.id}/date/${date}/pdf?token=${token}`;
      await Linking.openURL(url);
    } catch (e) {
      console.error('Combined PDF failed:', e);
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
        <View style={s.logContent}>
          {data.weather && (
            <Text style={s.logField}>
              <Text style={s.logFieldLabel}>Weather: </Text>{data.weather} {data.weather_temp || ''}
            </Text>
          )}
          {data.general_description && (
            <Text style={s.logField}>
              <Text style={s.logFieldLabel}>Description: </Text>{data.general_description}
            </Text>
          )}
          {(data.activities || []).map((act, i) => (
            <View key={i} style={s.activityRow}>
              <Text style={s.activityText}>
                {act.company || 'Unknown'} — {act.num_workers || 0} workers — {act.work_description || 'N/A'}
              </Text>
            </View>
          ))}
          {data.equipment_on_site && (
            <Text style={s.logField}>
              <Text style={s.logFieldLabel}>Equipment: </Text>
              {Object.entries(data.equipment_on_site).filter(([_, v]) => v).map(([k]) => k.replace(/_/g, ' ')).join(', ') || 'None'}
            </Text>
          )}
          <Text style={s.signedBy}>Signed by: {log.cp_name || 'N/A'}</Text>
        </View>
      );
    }

    if (log.log_type === 'toolbox_talk') {
      const topics = data.checked_topics || {};
      const topicList = Object.entries(topics).filter(([_, v]) => v).map(([k]) => k.replace(/_/g, ' '));
      const attendees = data.attendees || [];
      return (
        <View style={s.logContent}>
          {data.location && (
            <Text style={s.logField}>
              <Text style={s.logFieldLabel}>Location: </Text>{data.location}
            </Text>
          )}
          {data.performed_by && (
            <Text style={s.logField}>
              <Text style={s.logFieldLabel}>Performed By: </Text>{data.performed_by}
            </Text>
          )}
          <Text style={s.logField}>
            <Text style={s.logFieldLabel}>Topics ({topicList.length}): </Text>
            {topicList.join(', ') || 'None'}
          </Text>
          <Text style={s.logField}>
            <Text style={s.logFieldLabel}>Attendees: </Text>
            {attendees.length} workers
          </Text>
          {attendees.map((a, i) => (
            <Text key={i} style={s.attendeeText}>
              • {a.name || 'Unknown'} ({a.company || ''}) {a.signed ? '✓' : '—'}
            </Text>
          ))}
          <Text style={s.signedBy}>Signed by: {log.cp_name || 'N/A'}</Text>
        </View>
      );
    }

    if (log.log_type === 'preshift_signin') {
      const workers = (data.workers || []).filter(w => w.name?.trim());
      return (
        <View style={s.logContent}>
          <Text style={s.logField}>
            <Text style={s.logFieldLabel}>Workers: </Text>{workers.length}
          </Text>
          {workers.map((w, i) => (
            <View key={i} style={s.workerRow}>
              <Text style={s.workerName}>{w.name}</Text>
              <Text style={s.workerDetail}>{w.company} • OSHA: {w.osha_number || 'N/A'}</Text>
              <Text style={s.workerDetail}>
                Injury: {w.had_injury || '—'} | PPE: {w.inspected_ppe || '—'}
              </Text>
            </View>
          ))}
          <Text style={s.signedBy}>Signed by: {log.cp_name || 'N/A'}</Text>
        </View>
      );
    }

    return <Text style={s.logField}>No data available</Text>;
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <GlassButton
            variant="icon"
            icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={() => router.push('/site')}
          />
          <View style={{ flex: 1 }}>
            <Text style={s.headerTitle}>Log Books</Text>
            <Text style={s.headerSub}>Submitted Records</Text>
          </View>
        </View>

        {/* Tabs */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={s.tabScroll}>
          <View style={s.tabRow}>
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
                  style={[s.tab, isActive && { backgroundColor: `${tab.color}20`, borderColor: `${tab.color}50` }]}
                >
                  <Icon size={16} strokeWidth={1.5} color={isActive ? tab.color : colors.text.muted} />
                  <Text style={[s.tabText, isActive && { color: tab.color }]}>{tab.label}</Text>
                  {count > 0 && (
                    <View style={[s.tabBadge, { backgroundColor: isActive ? tab.color : colors.text.muted }]}>
                      <Text style={s.tabBadgeText}>{count}</Text>
                    </View>
                  )}
                </Pressable>
              );
            })}
          </View>
        </ScrollView>

        {/* Content */}
        <ScrollView style={s.scrollView} contentContainerStyle={s.scrollContent}>
          {loading ? (
            <View style={s.loadingCenter}>
              <ActivityIndicator size="large" color={colors.text.primary} />
              <Text style={s.loadingText}>Loading logbooks...</Text>
            </View>
          ) : sortedDates.length === 0 ? (
            <GlassCard style={s.emptyCard}>
              <FileText size={40} strokeWidth={1} color={colors.text.muted} />
              <Text style={s.emptyTitle}>No Submitted Logs</Text>
              <Text style={s.emptyText}>
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
                    style={s.dateHeader}
                  >
                    <Calendar size={16} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={s.dateText}>{formatDate(date)}</Text>
                    <View style={s.dateBadge}>
                      <CheckCircle size={12} strokeWidth={2} color="#4ade80" />
                      <Text style={s.dateBadgeText}>{logs.length}</Text>
                    </View>
                    <ChevronRight
                      size={16} strokeWidth={1.5} color={colors.text.muted}
                      style={isExpanded ? { transform: [{ rotate: '90deg' }] } : {}}
                    />
                  </Pressable>

                  {isExpanded && (
                    <>
                      {/* Combined PDF button for this date */}
                      <View style={s.pdfRow}>
                        <GlassButton
                          title="Download Full Day Report"
                          icon={<Download size={14} strokeWidth={1.5} color={colors.text.primary} />}
                          onPress={() => handleCombinedPdf(date)}
                          style={s.pdfBtn}
                        />
                      </View>

                      {logs.map((log, idx) => (
                        <GlassCard key={log.id || idx} style={s.logCard}>
                          {/* Document Header */}
                          <View style={s.docHeader}>
                            <View style={s.docHeaderLeft}>
                              <Text style={s.logType}>
                                {LOG_TABS.find(t => t.key === log.log_type)?.label || log.log_type}
                              </Text>
                              <Text style={s.docDate}>{formatDate(log.date || date)}</Text>
                            </View>
                            <View style={s.docHeaderRight}>
                              <View style={[s.statusBadge, log.status === 'submitted' ? s.statusSubmitted : s.statusDraft]}>
                                <Text style={[s.statusText, log.status === 'submitted' ? s.statusTextSubmitted : s.statusTextDraft]}>
                                  {log.status === 'submitted' ? 'SUBMITTED' : 'DRAFT'}
                                </Text>
                              </View>
                              <Text style={s.logTime}>
                                {log.created_at ? new Date(log.created_at).toLocaleTimeString('en-US', {
                                  hour: 'numeric', minute: '2-digit', hour12: true,
                                }) : ''}
                              </Text>
                            </View>
                          </View>

                          {/* Full Document Content */}
                          {renderLogContent(log)}

                          {/* PDF Actions — tap = browser, long-press = share */}
                          {log.status === 'submitted' && (log.id || log._id) && (
                            <View style={s.pdfActions}>
                              <Pressable
                                style={s.pdfActionBtn}
                                onPress={() => handleViewLogPdf(log.id || log._id)}
                                onLongPress={() => handleShareLogPdf(log.id || log._id, log.log_type, log.date || date)}
                              >
                                <Download size={14} strokeWidth={1.5} color="#3b82f6" />
                                <Text style={s.pdfActionText}>PDF</Text>
                              </Pressable>
                              <Pressable
                                style={s.pdfActionBtn}
                                onPress={() => handleShareLogPdf(log.id || log._id, log.log_type, log.date || date)}
                              >
                                <Share2 size={14} strokeWidth={1.5} color="#3b82f6" />
                                <Text style={s.pdfActionText}>Share</Text>
                              </Pressable>
                            </View>
                          )}
                        </GlassCard>
                      ))}
                    </>
                  )}
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

function buildStyles(colors, isDark) {
  return StyleSheet.create({
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
}
