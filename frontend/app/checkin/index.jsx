import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Alert,
  Platform,
  Image,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  LogOut,
  QrCode,
  Nfc,
  Users,
  CheckCircle,
  Clock,
  Building2,
  Search,
  UserCheck,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { projectsAPI, workersAPI, checkinsAPI } from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';

export default function CheckInScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { projectId } = useLocalSearchParams();
  const { logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [checkingIn, setCheckingIn] = useState(false);
  const [project, setProject] = useState(null);
  const [projects, setProjects] = useState([]);
  const [workers, setWorkers] = useState([]);
  const [selectedProject, setSelectedProject] = useState(projectId || null);
  const [selectedWorker, setSelectedWorker] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [showWorkerPicker, setShowWorkerPicker] = useState(false);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchData();
    }
  }, [isAuthenticated]);

  const fetchData = async () => {
    try {
      const [projectsData, workersData] = await Promise.all([
        projectsAPI.getAll().catch(() => []),
        workersAPI.getAll().catch(() => []),
      ]);

      setProjects(Array.isArray(projectsData) ? projectsData : []);
      setWorkers(Array.isArray(workersData) ? workersData : []);

      if (projectId) {
        const proj = projectsData.find(p => (p._id || p.id) === projectId);
        setProject(proj);
        setSelectedProject(projectId);
      }
    } catch (error) {
      console.error('Failed to fetch data:', error);
      toast.error('Error', 'Could not load data');
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const handleSelectProject = (proj) => {
    setSelectedProject(proj._id || proj.id);
    setProject(proj);
  };

  const handleCheckIn = async () => {
    if (!selectedProject) {
      toast.error('Error', 'Please select a project');
      return;
    }
    if (!selectedWorker) {
      toast.error('Error', 'Please select a worker');
      return;
    }

    setCheckingIn(true);
    try {
      // API call to check in worker
      await checkinsAPI.checkIn?.({
        project_id: selectedProject,
        worker_id: selectedWorker._id || selectedWorker.id,
        timestamp: new Date().toISOString(),
      }) || Promise.resolve();
      
      toast.success('Checked In', `${selectedWorker.name} has been checked in`);
      setSelectedWorker(null);
      setShowWorkerPicker(false);
    } catch (error) {
      console.error('Check-in failed:', error);
      toast.error('Error', 'Check-in failed. Please try again.');
    } finally {
      setCheckingIn(false);
    }
  };

  const handleNfcCheckIn = () => {
    toast.info('NFC', 'NFC check-in is only available on native devices');
  };

  const filteredWorkers = workers.filter(w => 
    w.name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    w.trade?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    w.company?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const currentTime = new Date().toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
  });

  if (authLoading || loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container}>
          <View style={s.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={s.loadingText}>Loading...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

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
            <Image source={require('../../assets/logo-header.png')} style={{ width: 180, height: 48, resizeMode: 'contain' }} />
          </View>
          <GlassButton
            variant="icon"
            icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={handleLogout}
          />
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Title */}
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>WORKER</Text>
            <Text style={s.titleText}>Check-In</Text>
          </View>

          {/* Project Selection */}
          <GlassCard style={s.projectCard}>
            <Text style={s.cardLabel}>SELECT PROJECT</Text>
            {project ? (
              <Pressable 
                onPress={() => setProject(null)}
                style={s.selectedProject}
              >
                <IconPod size={44}>
                  <Building2 size={20} strokeWidth={1.5} color={colors.text.secondary} />
                </IconPod>
                <View style={s.projectInfo}>
                  <Text style={s.projectName}>{project.name}</Text>
                  <Text style={s.projectLocation}>{project.location || project.address}</Text>
                </View>
                <View style={s.qrBadge}>
                  <QrCode size={20} strokeWidth={1.5} color={colors.text.muted} />
                </View>
              </Pressable>
            ) : (
              <View style={s.projectList}>
                {projects.map((proj) => (
                  <Pressable
                    key={proj._id || proj.id}
                    onPress={() => handleSelectProject(proj)}
                    style={({ pressed }) => [
                      s.projectItem,
                      pressed && s.projectItemPressed,
                    ]}
                  >
                    <Building2 size={18} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={s.projectItemName}>{proj.name}</Text>
                  </Pressable>
                ))}
                {projects.length === 0 && (
                  <Text style={s.emptyText}>No projects available</Text>
                )}
              </View>
            )}
          </GlassCard>

          {/* Check-In Methods */}
          {project && (
            <>
              {/* Manual Check-In */}
              <GlassCard style={s.methodCard}>
                <View style={s.methodHeader}>
                  <IconPod size={44}>
                    <UserCheck size={20} strokeWidth={1.5} color="#3b82f6" />
                  </IconPod>
                  <View style={s.methodInfo}>
                    <Text style={s.methodTitle}>Manual Check-In</Text>
                    <Text style={s.methodDesc}>Select worker from list</Text>
                  </View>
                </View>

                {/* Selected Worker */}
                {selectedWorker ? (
                  <View style={s.selectedWorker}>
                    <View style={s.workerAvatar}>
                      <Text style={s.workerInitial}>
                        {selectedWorker.name?.charAt(0) || 'W'}
                      </Text>
                    </View>
                    <View style={s.workerInfo}>
                      <Text style={s.workerName}>{selectedWorker.name}</Text>
                      <Text style={s.workerTrade}>
                        {selectedWorker.trade} • {selectedWorker.company || 'No company'}
                      </Text>
                    </View>
                    <Pressable 
                      onPress={() => setSelectedWorker(null)}
                      style={s.changeBtn}
                    >
                      <Text style={s.changeBtnText}>Change</Text>
                    </Pressable>
                  </View>
                ) : (
                  <GlassButton
                    title="Select Worker"
                    icon={<Users size={18} strokeWidth={1.5} color={colors.text.primary} />}
                    onPress={() => setShowWorkerPicker(true)}
                    style={s.selectWorkerBtn}
                  />
                )}

                {/* Time Display */}
                <View style={s.timeDisplay}>
                  <Clock size={16} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.timeText}>Check-in time: {currentTime}</Text>
                </View>

                {/* Check In Button */}
                <GlassButton
                  title={checkingIn ? 'Checking In...' : 'Check In Worker'}
                  icon={<CheckCircle size={20} strokeWidth={1.5} color="#fff" />}
                  onPress={handleCheckIn}
                  loading={checkingIn}
                  disabled={!selectedWorker || checkingIn}
                  style={[
                    s.checkInBtn,
                    (!selectedWorker || checkingIn) && s.checkInBtnDisabled,
                  ]}
                  textStyle={s.checkInBtnText}
                />
              </GlassCard>

              {/* NFC Check-In */}
              <GlassCard style={s.methodCard}>
                <View style={s.methodHeader}>
                  <IconPod size={44}>
                    <Nfc size={20} strokeWidth={1.5} color="#10b981" />
                  </IconPod>
                  <View style={s.methodInfo}>
                    <Text style={s.methodTitle}>NFC Tag Scan</Text>
                    <Text style={s.methodDesc}>Tap worker's NFC badge</Text>
                  </View>
                </View>
                <GlassButton
                  title="Scan NFC Tag"
                  icon={<Nfc size={18} strokeWidth={1.5} color={colors.text.primary} />}
                  onPress={handleNfcCheckIn}
                  style={s.nfcBtn}
                />
              </GlassCard>
            </>
          )}

          {/* Worker Picker Modal */}
          {showWorkerPicker && (
            <GlassCard style={s.workerPicker}>
              <View style={s.pickerHeader}>
                <Text style={s.pickerTitle}>Select Worker</Text>
                <GlassButton
                  variant="icon"
                  icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
                  onPress={() => setShowWorkerPicker(false)}
                />
              </View>

              <GlassInput
                value={searchQuery}
                onChangeText={setSearchQuery}
                placeholder="Search workers..."
                leftIcon={<Search size={18} strokeWidth={1.5} color={colors.text.subtle} />}
              />

              <ScrollView style={s.workerList} nestedScrollEnabled>
                {filteredWorkers.map((worker) => (
                  <Pressable
                    key={worker._id || worker.id}
                    onPress={() => {
                      setSelectedWorker(worker);
                      setShowWorkerPicker(false);
                    }}
                    style={({ pressed }) => [
                      s.workerItem,
                      pressed && s.workerItemPressed,
                    ]}
                  >
                    <View style={s.workerItemAvatar}>
                      <Text style={s.workerItemInitial}>
                        {worker.name?.charAt(0) || 'W'}
                      </Text>
                    </View>
                    <View style={s.workerItemInfo}>
                      <Text style={s.workerItemName}>{worker.name}</Text>
                      <Text style={s.workerItemTrade}>
                        {worker.trade || 'Worker'} • {worker.company || 'No company'}
                      </Text>
                    </View>
                  </Pressable>
                ))}
                {filteredWorkers.length === 0 && (
                  <Text style={s.emptyText}>No workers found</Text>
                )}
              </ScrollView>
            </GlassCard>
          )}
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: {
    flex: 1,
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.md,
  },
  loadingText: {
    color: colors.text.muted,
    fontSize: 14,
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
  logoText: {
    ...typography.label,
    color: colors.text.muted,
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
    fontSize: 42,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -1,
  },
  projectCard: {
    marginBottom: spacing.lg,
  },
  cardLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
  selectedProject: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderRadius: borderRadius.lg,
  },
  projectInfo: {
    flex: 1,
  },
  projectName: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  projectLocation: {
    fontSize: 13,
    color: colors.text.muted,
  },
  qrBadge: {
    width: 40,
    height: 40,
    borderRadius: borderRadius.md,
    backgroundColor: colors.glass.background,
    alignItems: 'center',
    justifyContent: 'center',
  },
  projectList: {
    gap: spacing.sm,
  },
  projectItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.md,
  },
  projectItemPressed: {
    backgroundColor: 'rgba(255, 255, 255, 0.12)',
  },
  projectItemName: {
    fontSize: 15,
    color: colors.text.primary,
  },
  methodCard: {
    marginBottom: spacing.lg,
  },
  methodHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.lg,
  },
  methodInfo: {
    flex: 1,
  },
  methodTitle: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
  },
  methodDesc: {
    fontSize: 13,
    color: colors.text.muted,
  },
  selectedWorker: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
    backgroundColor: 'rgba(59, 130, 246, 0.1)',
    borderRadius: borderRadius.lg,
    marginBottom: spacing.md,
  },
  workerAvatar: {
    width: 44,
    height: 44,
    borderRadius: borderRadius.full,
    backgroundColor: '#3b82f6',
    alignItems: 'center',
    justifyContent: 'center',
  },
  workerInitial: {
    fontSize: 18,
    fontWeight: '600',
    color: '#fff',
  },
  workerInfo: {
    flex: 1,
  },
  workerName: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
  },
  workerTrade: {
    fontSize: 12,
    color: colors.text.muted,
  },
  changeBtn: {
    padding: spacing.sm,
  },
  changeBtnText: {
    fontSize: 13,
    color: '#3b82f6',
    fontWeight: '500',
  },
  selectWorkerBtn: {
    marginBottom: spacing.md,
  },
  timeDisplay: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  timeText: {
    fontSize: 14,
    color: colors.text.muted,
  },
  checkInBtn: {
    backgroundColor: '#10b981',
    borderColor: '#10b981',
  },
  checkInBtnDisabled: {
    opacity: 0.5,
  },
  checkInBtnText: {
    color: '#fff',
    fontWeight: '600',
  },
  nfcBtn: {
    borderColor: 'rgba(16, 185, 129, 0.3)',
  },
  workerPicker: {
    marginTop: spacing.lg,
    maxHeight: 400,
  },
  pickerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  pickerTitle: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
  },
  workerList: {
    marginTop: spacing.md,
    maxHeight: 250,
  },
  workerItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    marginBottom: spacing.sm,
  },
  workerItemPressed: {
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
  },
  workerItemAvatar: {
    width: 40,
    height: 40,
    borderRadius: borderRadius.full,
    backgroundColor: colors.glass.background,
    alignItems: 'center',
    justifyContent: 'center',
  },
  workerItemInitial: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  workerItemInfo: {
    flex: 1,
  },
  workerItemName: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  workerItemTrade: {
    fontSize: 12,
    color: colors.text.muted,
  },
  emptyText: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    paddingVertical: spacing.lg,
  },
});
}
