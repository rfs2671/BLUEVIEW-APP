import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Building2,
  ClipboardList,
  Calendar,
  Cloud,
  Sun,
  CloudRain,
  Plus,
  LogOut,
  RefreshCw,
  Users,
  PenTool,
  ShieldCheck,
  HardHat,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod, GlassListItem } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { GlassSkeleton } from '../../src/components/GlassSkeleton';
import SiteNav from '../../src/components/SiteNav';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { dailyLogsAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

const weatherOptions = [
  { value: 'sunny', label: 'Sunny', icon: Sun },
  { value: 'cloudy', label: 'Cloudy', icon: Cloud },
  { value: 'rainy', label: 'Rainy', icon: CloudRain },
];

export default function SiteDailyLogsScreen() {
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading, siteMode, siteProject } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [logs, setLogs] = useState([]);
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [todayLog, setTodayLog] = useState(null);
  const [showNewLog, setShowNewLog] = useState(false);
  const [newLogData, setNewLogData] = useState({
    weather: 'sunny',
    notes: '',
    worker_count: 0,
  });
  const [saving, setSaving] = useState(false);

  // Redirect if not authenticated or not in site mode
  useEffect(() => {
    if (!authLoading) {
      if (!isAuthenticated) {
        router.replace('/login');
      } else if (!siteMode) {
        router.replace('/');
      }
    }
  }, [isAuthenticated, authLoading, siteMode]);

  // Fetch data
  useEffect(() => {
    if (isAuthenticated && siteMode && siteProject?.id) {
      fetchLogs();
    }
  }, [isAuthenticated, siteMode, siteProject]);

  const fetchLogs = async () => {
    if (!siteProject?.id) return;
    
    setLoading(true);
    try {
      const logsData = await dailyLogsAPI.getByProject(siteProject.id);
      const logsList = Array.isArray(logsData) ? logsData : [];
      setLogs(logsList);
      
      // Check if there's a log for today
      const today = new Date().toISOString().split('T')[0];
      const existing = logsList.find(l => l.date === today);
      setTodayLog(existing || null);
    } catch (error) {
      console.error('Failed to fetch logs:', error);
      toast.error('Load Error', 'Could not load daily logs');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateLog = async () => {
    if (!siteProject?.id) return;
    
    setSaving(true);
    try {
      const today = new Date().toISOString().split('T')[0];
      const logData = {
        project_id: siteProject.id,
        date: today,
        weather: newLogData.weather,
        notes: newLogData.notes,
        worker_count: parseInt(newLogData.worker_count) || 0,
      };
      
      await dailyLogsAPI.create(logData);
      toast.success('Created', 'Daily log created successfully');
      setShowNewLog(false);
      setNewLogData({ weather: 'sunny', notes: '', worker_count: 0 });
      fetchLogs();
    } catch (error) {
      console.error('Failed to create log:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not create daily log');
    } finally {
      setSaving(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const formatDate = (dateStr) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    });
  };

  const getWeatherIcon = (weather) => {
    const option = weatherOptions.find(w => w.value === weather);
    return option?.icon || Cloud;
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <View style={styles.siteBadge}>
              <Building2 size={14} strokeWidth={1.5} color="#4ade80" />
              <Text style={styles.siteBadgeText}>SITE MODE</Text>
            </View>
            <Text style={styles.projectName} numberOfLines={1}>
              {siteProject?.name || 'Project'}
            </Text>
          </View>
          <GlassButton
            variant="icon"
            icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={handleLogout}
          />
        </View>

        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Title */}
          <View style={styles.titleSection}>
            <Text style={styles.titleLabel}>DAILY</Text>
            <Text style={styles.titleText}>Log Books</Text>
          </View>

          {loading ? (
            <>
              <GlassSkeleton width="100%" height={200} borderRadiusValue={borderRadius.xxl} style={styles.mb16} />
              <GlassSkeleton width="100%" height={100} borderRadiusValue={borderRadius.xl} />
            </>
          ) : (
            <>
              {/* Today's Log or Create New */}
              {todayLog ? (
                <GlassCard style={styles.todayCard}>
                  <View style={styles.todayHeader}>
                    <View style={styles.todayBadge}>
                      <Calendar size={14} strokeWidth={1.5} color="#4ade80" />
                      <Text style={styles.todayBadgeText}>TODAY'S LOG</Text>
                    </View>
                    <Text style={styles.todayDate}>{formatDate(todayLog.date)}</Text>
                  </View>

                  <View style={styles.todayContent}>
                    <View style={styles.todayRow}>
                      <View style={styles.todayItem}>
                        <Text style={styles.todayLabel}>WEATHER</Text>
                        <View style={styles.weatherDisplay}>
                          {React.createElement(getWeatherIcon(todayLog.weather), {
                            size: 18,
                            strokeWidth: 1.5,
                            color: colors.text.secondary,
                          })}
                          <Text style={styles.weatherText}>
                            {todayLog.weather?.charAt(0).toUpperCase() + todayLog.weather?.slice(1)}
                          </Text>
                        </View>
                      </View>
                      <View style={styles.todayItem}>
                        <Text style={styles.todayLabel}>WORKERS</Text>
                        <View style={styles.workerCount}>
                          <Users size={18} strokeWidth={1.5} color={colors.text.secondary} />
                          <Text style={styles.workerCountText}>{todayLog.worker_count || 0}</Text>
                        </View>
                      </View>
                    </View>

                    {todayLog.notes && (
                      <View style={styles.notesSection}>
                        <Text style={styles.todayLabel}>NOTES</Text>
                        <Text style={styles.notesText}>{todayLog.notes}</Text>
                      </View>
                    )}
                  </View>

                  {/* Signature Sections */}
                  <View style={styles.signatureSection}>
                    <Text style={styles.sectionTitle}>Sign-Off Sections</Text>
                    
                    {/* Superintendent Sign-Off */}
                    <View style={styles.signatureCard}>
                      <View style={styles.signatureHeader}>
                        <IconPod size={40}>
                          <HardHat size={18} strokeWidth={1.5} color="#f59e0b" />
                        </IconPod>
                        <View style={styles.signatureInfo}>
                          <Text style={styles.signatureTitle}>Superintendent Sign-Off</Text>
                          <Text style={styles.signatureStatus}>
                            {todayLog.superintendent_signoff ? 'Signed' : 'Pending signature'}
                          </Text>
                        </View>
                      </View>
                      <View style={styles.signatureArea}>
                        <PenTool size={20} strokeWidth={1.5} color={colors.text.subtle} />
                        <Text style={styles.signaturePlaceholder}>
                          Signature area - Coming soon
                        </Text>
                      </View>
                    </View>

                    {/* Competent Person Sign-Off */}
                    <View style={styles.signatureCard}>
                      <View style={styles.signatureHeader}>
                        <IconPod size={40}>
                          <ShieldCheck size={18} strokeWidth={1.5} color="#3b82f6" />
                        </IconPod>
                        <View style={styles.signatureInfo}>
                          <Text style={styles.signatureTitle}>Competent Person Sign-Off</Text>
                          <Text style={styles.signatureStatus}>
                            {todayLog.competent_person_signoff ? 'Signed' : 'Pending signature'}
                          </Text>
                        </View>
                      </View>
                      <View style={styles.signatureArea}>
                        <PenTool size={20} strokeWidth={1.5} color={colors.text.subtle} />
                        <Text style={styles.signaturePlaceholder}>
                          Signature area - Coming soon
                        </Text>
                      </View>
                    </View>
                  </View>
                </GlassCard>
              ) : showNewLog ? (
                <GlassCard style={styles.newLogCard}>
                  <Text style={styles.newLogTitle}>Create Today's Log</Text>

                  {/* Weather Selection */}
                  <View style={styles.formGroup}>
                    <Text style={styles.formLabel}>WEATHER</Text>
                    <View style={styles.weatherOptions}>
                      {weatherOptions.map((option) => {
                        const Icon = option.icon;
                        const isSelected = newLogData.weather === option.value;
                        return (
                          <Pressable
                            key={option.value}
                            onPress={() => setNewLogData({ ...newLogData, weather: option.value })}
                            style={[
                              styles.weatherOption,
                              isSelected && styles.weatherOptionSelected,
                            ]}
                          >
                            <Icon
                              size={20}
                              strokeWidth={1.5}
                              color={isSelected ? '#4ade80' : colors.text.muted}
                            />
                            <Text
                              style={[
                                styles.weatherOptionText,
                                isSelected && styles.weatherOptionTextSelected,
                              ]}
                            >
                              {option.label}
                            </Text>
                          </Pressable>
                        );
                      })}
                    </View>
                  </View>

                  {/* Worker Count */}
                  <View style={styles.formGroup}>
                    <Text style={styles.formLabel}>WORKER COUNT</Text>
                    <GlassInput
                      value={String(newLogData.worker_count)}
                      onChangeText={(val) => setNewLogData({ ...newLogData, worker_count: val })}
                      keyboardType="numeric"
                      placeholder="0"
                    />
                  </View>

                  {/* Notes */}
                  <View style={styles.formGroup}>
                    <Text style={styles.formLabel}>NOTES</Text>
                    <GlassInput
                      value={newLogData.notes}
                      onChangeText={(val) => setNewLogData({ ...newLogData, notes: val })}
                      placeholder="Enter daily notes..."
                      multiline
                      numberOfLines={4}
                      style={styles.notesInput}
                    />
                  </View>

                  <View style={styles.formActions}>
                    <GlassButton
                      title="Cancel"
                      onPress={() => setShowNewLog(false)}
                      style={styles.cancelBtn}
                    />
                    <GlassButton
                      title={saving ? 'Creating...' : 'Create Log'}
                      onPress={handleCreateLog}
                      loading={saving}
                      style={styles.createBtn}
                    />
                  </View>
                </GlassCard>
              ) : (
                <Pressable
                  style={styles.createLogCard}
                  onPress={() => setShowNewLog(true)}
                >
                  <IconPod size={64}>
                    <Plus size={28} strokeWidth={1.5} color={colors.text.secondary} />
                  </IconPod>
                  <Text style={styles.createLogTitle}>Create Today's Log</Text>
                  <Text style={styles.createLogText}>
                    No log for today yet. Tap to create one.
                  </Text>
                </Pressable>
              )}

              {/* Previous Logs */}
              {logs.length > 0 && (
                <View style={styles.previousLogs}>
                  <Text style={styles.previousTitle}>Previous Logs</Text>
                  {logs.slice(0, 7).map((log, index) => {
                    const WeatherIcon = getWeatherIcon(log.weather);
                    const isToday = log.date === new Date().toISOString().split('T')[0];
                    if (isToday) return null;
                    
                    return (
                      <GlassListItem key={log.id || log._id || index} style={styles.logItem}>
                        <View style={styles.logDate}>
                          <Text style={styles.logDateText}>{formatDate(log.date)}</Text>
                        </View>
                        <View style={styles.logInfo}>
                          <WeatherIcon size={16} strokeWidth={1.5} color={colors.text.muted} />
                          <Text style={styles.logWeather}>
                            {log.weather?.charAt(0).toUpperCase() + log.weather?.slice(1)}
                          </Text>
                        </View>
                        <View style={styles.logWorkers}>
                          <Users size={14} strokeWidth={1.5} color={colors.text.muted} />
                          <Text style={styles.logWorkersText}>{log.worker_count || 0}</Text>
                        </View>
                      </GlassListItem>
                    );
                  })}
                </View>
              )}
            </>
          )}
        </ScrollView>

        <SiteNav />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
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
    flex: 1,
  },
  siteBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: 'rgba(74, 222, 128, 0.15)',
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: 'rgba(74, 222, 128, 0.3)',
  },
  siteBadgeText: {
    fontSize: 10,
    fontWeight: '600',
    color: '#4ade80',
    letterSpacing: 0.5,
  },
  projectName: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    flex: 1,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: 120,
  },
  titleSection: {
    marginBottom: spacing.xl,
  },
  titleLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.sm,
  },
  titleText: {
    fontSize: 48,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -1,
  },
  mb16: {
    marginBottom: spacing.md,
  },
  todayCard: {
    marginBottom: spacing.lg,
  },
  todayHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.lg,
  },
  todayBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: 'rgba(74, 222, 128, 0.15)',
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
  },
  todayBadgeText: {
    fontSize: 10,
    fontWeight: '600',
    color: '#4ade80',
    letterSpacing: 0.5,
  },
  todayDate: {
    fontSize: 14,
    color: colors.text.muted,
  },
  todayContent: {
    gap: spacing.md,
  },
  todayRow: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  todayItem: {
    flex: 1,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  todayLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.xs,
  },
  weatherDisplay: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  weatherText: {
    fontSize: 16,
    color: colors.text.primary,
  },
  workerCount: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  workerCountText: {
    fontSize: 24,
    fontWeight: '200',
    color: colors.text.primary,
  },
  notesSection: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  notesText: {
    fontSize: 14,
    color: colors.text.secondary,
    lineHeight: 20,
  },
  signatureSection: {
    marginTop: spacing.lg,
    paddingTop: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: colors.glass.border,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: spacing.md,
    letterSpacing: 0.5,
  },
  signatureCard: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.glass.border,
    marginBottom: spacing.sm,
  },
  signatureHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  signatureInfo: {
    flex: 1,
  },
  signatureTitle: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
  },
  signatureStatus: {
    fontSize: 12,
    color: colors.text.muted,
    marginTop: 2,
  },
  signatureArea: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xl,
    backgroundColor: 'rgba(255, 255, 255, 0.03)',
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.glass.border,
    borderStyle: 'dashed',
  },
  signaturePlaceholder: {
    fontSize: 13,
    color: colors.text.subtle,
    fontStyle: 'italic',
  },
  newLogCard: {
    marginBottom: spacing.lg,
  },
  newLogTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.lg,
  },
  formGroup: {
    marginBottom: spacing.md,
  },
  formLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.sm,
  },
  weatherOptions: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  weatherOption: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.md,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  weatherOptionSelected: {
    borderColor: '#4ade80',
    backgroundColor: 'rgba(74, 222, 128, 0.1)',
  },
  weatherOptionText: {
    fontSize: 13,
    color: colors.text.muted,
  },
  weatherOptionTextSelected: {
    color: '#4ade80',
  },
  notesInput: {
    minHeight: 100,
    textAlignVertical: 'top',
  },
  formActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  cancelBtn: {
    flex: 1,
  },
  createBtn: {
    flex: 2,
  },
  createLogCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xxl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    marginBottom: spacing.lg,
  },
  createLogTitle: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  createLogText: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
  },
  previousLogs: {
    marginTop: spacing.md,
  },
  previousTitle: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
  logItem: {
    gap: spacing.md,
    marginBottom: spacing.sm,
  },
  logDate: {
    minWidth: 100,
  },
  logDateText: {
    fontSize: 14,
    color: colors.text.primary,
  },
  logInfo: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  logWeather: {
    fontSize: 13,
    color: colors.text.muted,
  },
  logWorkers: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  logWorkersText: {
    fontSize: 13,
    color: colors.text.muted,
  },
});
