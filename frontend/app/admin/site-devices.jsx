import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  Modal,
  KeyboardAvoidingView,
  Platform,
  Image,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Plus,
  Smartphone,
  Building2,
  Trash2,
  X,
  LogOut,
  Key,
  CheckCircle,
  XCircle,
  RefreshCw,
  ChevronDown,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod, GlassListItem } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { GlassSkeleton } from '../../src/components/GlassSkeleton';
import FloatingNav from '../../src/components/FloatingNav';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { projectsAPI } from '../../src/utils/api';
import apiClient from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';

// Site device API functions
const siteDevicesAPI = {
  getAll: async () => {
    const response = await apiClient.get('/api/admin/site-devices');
    return response.data;
  },
  create: async (deviceData) => {
    const response = await apiClient.post('/api/admin/site-devices', deviceData);
    return response.data;
  },
  update: async (deviceId, deviceData) => {
    const response = await apiClient.put(`/api/admin/site-devices/${deviceId}`, deviceData);
    return response.data;
  },
  delete: async (deviceId) => {
    const response = await apiClient.delete(`/api/admin/site-devices/${deviceId}`);
    return response.data;
  },
};

export default function SiteDevicesScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [devices, setDevices] = useState([]);
  const [projects, setProjects] = useState([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showCredentials, setShowCredentials] = useState(null);
  const [newDevice, setNewDevice] = useState({
    project_id: '',
    device_name: '',
    username: '',
    password: '',
  });
  const [saving, setSaving] = useState(false);
  const [showProjectPicker, setShowProjectPicker] = useState(false);

  const isAdmin = user?.role === 'admin';

  // Redirect if not authenticated or not admin
  useEffect(() => {
    if (!authLoading) {
      if (!isAuthenticated) {
        router.replace('/login');
      } else if (!isAdmin) {
        router.replace('/');
        toast.error('Access Denied', 'Admin access required');
      }
    }
  }, [isAuthenticated, authLoading, isAdmin]);

  // Fetch data
  useEffect(() => {
    if (isAuthenticated && isAdmin) {
      fetchData();
    }
  }, [isAuthenticated, isAdmin]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [devicesData, projectsData] = await Promise.all([
        siteDevicesAPI.getAll().catch(() => []),
        projectsAPI.getAll().catch(() => []),
      ]);
      setDevices(Array.isArray(devicesData) ? devicesData : []);
      setProjects(Array.isArray(projectsData) ? projectsData : []);
    } catch (error) {
      console.error('Failed to fetch data:', error);
      toast.error('Load Error', 'Could not load site devices');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateDevice = async () => {
    if (!newDevice.project_id || !newDevice.username || !newDevice.password) {
      toast.warning('Missing Fields', 'Please select a project and fill in username and password');
      return;
    }

    setSaving(true);
    try {
      const result = await siteDevicesAPI.create(newDevice);
      toast.success('Created', 'Site device created successfully');
      
      // Show credentials to admin
      setShowCredentials({
        ...result,
        password: newDevice.password, // Show plain password one time
      });
      
      setShowCreateModal(false);
      setNewDevice({ project_id: '', device_name: '', username: '', password: '' });
      fetchData();
    } catch (error) {
      console.error('Failed to create device:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not create site device');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteDevice = async (deviceId) => {
    const confirmed = Platform.OS === 'web'
      ? window.confirm('Are you sure you want to delete this site device?')
      : await new Promise(resolve => {
          const { Alert } = require('react-native');
          Alert.alert('Delete Device', 'Are you sure you want to delete this site device?', [
            { text: 'Cancel', onPress: () => resolve(false), style: 'cancel' },
            { text: 'Delete', onPress: () => resolve(true), style: 'destructive' },
          ]);
        });
    if (!confirmed) return;

    try {
      await siteDevicesAPI.delete(deviceId);
      toast.success('Deleted', 'Site device removed');
      fetchData();
    } catch (error) {
      console.error('Failed to delete device:', error);
      toast.error('Error', 'Could not delete site device');
    }
  };

  const handleToggleActive = async (device) => {
    try {
      await siteDevicesAPI.update(device.id, { is_active: !device.is_active });
      toast.success('Updated', `Device ${device.is_active ? 'disabled' : 'enabled'}`);
      fetchData();
    } catch (error) {
      console.error('Failed to update device:', error);
      toast.error('Error', 'Could not update device');
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const getSelectedProject = () => {
    return projects.find(p => (p._id || p.id) === newDevice.project_id);
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/')}
            />
            <Image source={require('../../assets/logo-header.png')} style={{ width: 120, height: 32, resizeMode: 'contain' }} />
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
            <Text style={s.titleLabel}>ADMIN</Text>
            <Text style={s.titleText}>Site Devices</Text>
            <Text style={s.subtitle}>
              Create credentials for on-site devices with project-specific access
            </Text>
          </View>

          {/* Add Button */}
          <GlassButton
            title="Add Site Device"
            icon={<Plus size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={() => setShowCreateModal(true)}
            style={s.addButton}
          />

          {/* Devices List */}
          {loading ? (
            <>
              <GlassSkeleton width="100%" height={100} borderRadiusValue={borderRadius.xl} style={s.mb12} />
              <GlassSkeleton width="100%" height={100} borderRadiusValue={borderRadius.xl} />
            </>
          ) : devices.length > 0 ? (
            <View style={s.devicesList}>
              {devices.map((device) => (
                <GlassCard key={device.id} style={s.deviceCard}>
                  <View style={s.deviceHeader}>
                    <IconPod size={44}>
                      <Smartphone size={18} strokeWidth={1.5} color={device.is_active ? '#4ade80' : colors.text.muted} />
                    </IconPod>
                    <View style={s.deviceInfo}>
                      <Text style={s.deviceName}>{device.device_name}</Text>
                      <View style={s.deviceMeta}>
                        <Building2 size={12} strokeWidth={1.5} color={colors.text.muted} />
                        <Text style={s.deviceProject}>{device.project_name}</Text>
                      </View>
                    </View>
                    <View style={[s.statusBadge, device.is_active && s.statusActive]}>
                      {device.is_active ? (
                        <CheckCircle size={12} strokeWidth={1.5} color="#4ade80" />
                      ) : (
                        <XCircle size={12} strokeWidth={1.5} color={colors.text.muted} />
                      )}
                      <Text style={[s.statusText, device.is_active && s.statusTextActive]}>
                        {device.is_active ? 'Active' : 'Disabled'}
                      </Text>
                    </View>
                  </View>

                  <View style={s.credentialsRow}>
                    <View style={s.credentialItem}>
                      <Text style={s.credentialLabel}>USERNAME</Text>
                      <Text style={s.credentialValue}>{device.username}</Text>
                    </View>
                    {device.last_login && (
                      <View style={s.credentialItem}>
                        <Text style={s.credentialLabel}>LAST LOGIN</Text>
                        <Text style={s.credentialValue}>
                          {new Date(device.last_login).toLocaleDateString()}
                        </Text>
                      </View>
                    )}
                  </View>

                  <View style={s.deviceActions}>
                    <GlassButton
                      title={device.is_active ? 'Disable' : 'Enable'}
                      onPress={() => handleToggleActive(device)}
                      style={s.toggleBtn}
                    />
                    <GlassButton
                      variant="icon"
                      icon={<Trash2 size={18} strokeWidth={1.5} color="#ef4444" />}
                      onPress={() => handleDeleteDevice(device.id)}
                    />
                  </View>
                </GlassCard>
              ))}
            </View>
          ) : (
            <GlassCard style={s.emptyCard}>
              <IconPod size={64}>
                <Smartphone size={28} strokeWidth={1.5} color={colors.text.muted} />
              </IconPod>
              <Text style={s.emptyTitle}>No Site Devices</Text>
              <Text style={s.emptyText}>
                Create device credentials to allow on-site tablets or phones to access project-specific data.
              </Text>
            </GlassCard>
          )}
        </ScrollView>

        <FloatingNav />

        {/* Create Device Modal */}
        <Modal
          visible={showCreateModal}
          animationType="slide"
          transparent={true}
          onRequestClose={() => setShowCreateModal(false)}
        >
          <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
            style={s.modalOverlay}
          >
            <View style={s.modalContent}>
              <View style={s.modalHeader}>
                <Text style={s.modalTitle}>Add Site Device</Text>
                <Pressable onPress={() => setShowCreateModal(false)}>
                  <X size={24} strokeWidth={1.5} color={colors.text.muted} />
                </Pressable>
              </View>

              <ScrollView style={s.modalScroll}>
                {/* Project Selector */}
                <View style={s.formGroup}>
                  <Text style={s.formLabel}>PROJECT</Text>
                  <Pressable
                    style={s.selectorCard}
                    onPress={() => setShowProjectPicker(!showProjectPicker)}
                  >
                    <Text style={[s.selectorText, !newDevice.project_id && s.selectorPlaceholder]}>
                      {getSelectedProject()?.name || 'Select a project'}
                    </Text>
                    <ChevronDown
                      size={20}
                      strokeWidth={1.5}
                      color={colors.text.muted}
                      style={showProjectPicker && s.iconRotated}
                    />
                  </Pressable>
                  
                  {showProjectPicker && (
                    <View style={s.dropdown}>
                      {projects.map((p) => (
                        <Pressable
                          key={p._id || p.id}
                          onPress={() => {
                            setNewDevice({ ...newDevice, project_id: p._id || p.id });
                            setShowProjectPicker(false);
                          }}
                          style={[
                            s.dropdownItem,
                            newDevice.project_id === (p._id || p.id) && s.dropdownItemActive,
                          ]}
                        >
                          <Text style={s.dropdownText}>{p.name}</Text>
                        </Pressable>
                      ))}
                    </View>
                  )}
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>DEVICE NAME</Text>
                  <GlassInput
                    value={newDevice.device_name}
                    onChangeText={(val) => setNewDevice({ ...newDevice, device_name: val })}
                    placeholder="e.g., Site Tablet 1"
                  />
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>USERNAME</Text>
                  <GlassInput
                    value={newDevice.username}
                    onChangeText={(val) => setNewDevice({ ...newDevice, username: val })}
                    placeholder="e.g., site-downtown-1"
                    autoCapitalize="none"
                  />
                </View>

                <View style={s.formGroup}>
                  <Text style={s.formLabel}>PASSWORD</Text>
                  <GlassInput
                    value={newDevice.password}
                    onChangeText={(val) => setNewDevice({ ...newDevice, password: val })}
                    placeholder="Create a secure password"
                    secureTextEntry
                  />
                </View>

                <View style={s.infoBox}>
                  <Key size={16} strokeWidth={1.5} color="#f59e0b" />
                  <Text style={s.infoText}>
                    Save these credentials securely. The password cannot be recovered after creation.
                  </Text>
                </View>
              </ScrollView>

              <View style={s.modalActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => setShowCreateModal(false)}
                  style={s.cancelBtn}
                />
                <GlassButton
                  title={saving ? 'Creating...' : 'Create Device'}
                  onPress={handleCreateDevice}
                  loading={saving}
                  style={s.createBtn}
                />
              </View>
            </View>
          </KeyboardAvoidingView>
        </Modal>

        {/* Credentials Display Modal */}
        <Modal
          visible={!!showCredentials}
          animationType="fade"
          transparent={true}
          onRequestClose={() => setShowCredentials(null)}
        >
          <View style={s.modalOverlay}>
            <View style={s.credentialsModal}>
              <View style={s.successIcon}>
                <CheckCircle size={48} strokeWidth={1.5} color="#4ade80" />
              </View>
              <Text style={s.credentialsTitle}>Device Created!</Text>
              <Text style={s.credentialsSubtitle}>
                Save these credentials for the on-site device:
              </Text>

              <View style={s.credentialsBox}>
                <View style={s.credentialRow}>
                  <Text style={s.credentialLabel}>Project</Text>
                  <Text style={s.credentialValueBold}>{showCredentials?.project_name}</Text>
                </View>
                <View style={s.credentialRow}>
                  <Text style={s.credentialLabel}>Device</Text>
                  <Text style={s.credentialValueBold}>{showCredentials?.device_name}</Text>
                </View>
                <View style={s.credentialRow}>
                  <Text style={s.credentialLabel}>Username</Text>
                  <Text style={s.credentialValueMono}>{showCredentials?.username}</Text>
                </View>
                <View style={s.credentialRow}>
                  <Text style={s.credentialLabel}>Password</Text>
                  <Text style={s.credentialValueMono}>{showCredentials?.password}</Text>
                </View>
              </View>

              <GlassButton
                title="Done"
                onPress={() => setShowCredentials(null)}
                style={s.doneBtn}
              />
            </View>
          </View>
        </Modal>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
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
    marginBottom: spacing.lg,
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
  subtitle: {
    fontSize: 14,
    color: colors.text.muted,
    marginTop: spacing.sm,
  },
  addButton: {
    marginBottom: spacing.lg,
  },
  mb12: {
    marginBottom: spacing.sm + 4,
  },
  devicesList: {
    gap: spacing.md,
  },
  deviceCard: {
    padding: spacing.lg,
  },
  deviceHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  deviceInfo: {
    flex: 1,
  },
  deviceName: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  deviceMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginTop: 4,
  },
  deviceProject: {
    fontSize: 13,
    color: colors.text.muted,
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: 'rgba(100, 116, 139, 0.2)',
    borderRadius: borderRadius.full,
  },
  statusActive: {
    backgroundColor: 'rgba(74, 222, 128, 0.15)',
  },
  statusText: {
    fontSize: 11,
    fontWeight: '500',
    color: colors.text.muted,
  },
  statusTextActive: {
    color: '#4ade80',
  },
  credentialsRow: {
    flexDirection: 'row',
    gap: spacing.lg,
    marginBottom: spacing.md,
  },
  credentialItem: {
    flex: 1,
  },
  credentialLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: 2,
  },
  credentialValue: {
    fontSize: 14,
    color: colors.text.secondary,
    fontFamily: 'monospace',
  },
  deviceActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.glass.border,
    paddingTop: spacing.md,
  },
  toggleBtn: {
    flex: 1,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  emptyText: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 280,
    lineHeight: 20,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.lg,
  },
  modalContent: {
    backgroundColor: '#1a1a2e',
    borderRadius: borderRadius.xxl,
    width: '100%',
    maxWidth: 500,
    maxHeight: '80%',
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: colors.glass.border,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
  },
  modalScroll: {
    padding: spacing.lg,
  },
  formGroup: {
    marginBottom: spacing.md,
  },
  formLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.sm,
  },
  selectorCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
  },
  selectorText: {
    fontSize: 15,
    color: colors.text.primary,
  },
  selectorPlaceholder: {
    color: colors.text.muted,
  },
  iconRotated: {
    transform: [{ rotate: '180deg' }],
  },
  dropdown: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    marginTop: spacing.sm,
    overflow: 'hidden',
  },
  dropdownItem: {
    padding: spacing.md,
  },
  dropdownItemActive: {
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
  },
  dropdownText: {
    fontSize: 15,
    color: colors.text.secondary,
  },
  infoBox: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    backgroundColor: 'rgba(245, 158, 11, 0.1)',
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: 'rgba(245, 158, 11, 0.3)',
  },
  infoText: {
    flex: 1,
    fontSize: 13,
    color: '#f59e0b',
    lineHeight: 18,
  },
  modalActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    padding: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: colors.glass.border,
  },
  cancelBtn: {
    flex: 1,
  },
  createBtn: {
    flex: 2,
  },
  credentialsModal: {
    backgroundColor: '#1a1a2e',
    borderRadius: borderRadius.xxl,
    padding: spacing.xl,
    width: '100%',
    maxWidth: 400,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  successIcon: {
    marginBottom: spacing.lg,
  },
  credentialsTitle: {
    fontSize: 24,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.sm,
  },
  credentialsSubtitle: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    marginBottom: spacing.lg,
  },
  credentialsBox: {
    width: '100%',
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    marginBottom: spacing.lg,
  },
  credentialRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.glass.border,
  },
  credentialValueBold: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  credentialValueMono: {
    fontSize: 14,
    fontFamily: 'monospace',
    color: '#4ade80',
  },
  doneBtn: {
    width: '100%',
  },
});
}
