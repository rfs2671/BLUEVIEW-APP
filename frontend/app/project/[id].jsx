import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  Modal,
  Alert,
  Platform,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  LogOut,
  MapPin,
  Users,
  Building2,
  QrCode,
  ClipboardList,
  Settings,
  Wifi,
  ChevronRight,
  HardHat,
  Plus,
  Trash2,
  X,
  Smartphone,
  Key,
  CheckCircle,
  XCircle,
  Mail,
  Cloud,
  Folder,
  FileText,
  Link as LinkIcon,
  Zap,
  Radio,
  Clock,
  Shield,
  FileCheck,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod } from '../../src/components/GlassCard';
import RenewalAlertCard from '../../src/components/RenewalAlertCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { useProjects } from '../../src/hooks/useProjects';
import { useCheckIns } from '../../src/hooks/useCheckIns';
import OfflineIndicator from '../../src/components/OfflineIndicator';
import { projectsAPI, checkinsAPI, checklistsAPI } from '../../src/utils/api';
import apiClient from '../../src/utils/api';
import * as NfcHelper from '../../src/utils/nfcHelper';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';

// Site device API for project-specific devices
const siteDevicesAPI = {
  getByProject: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/site-devices`);
    return response.data;
  },
  create: async (projectId, deviceData) => {
    const response = await apiClient.post(`/api/projects/${projectId}/site-devices`, { ...deviceData, project_id: projectId });
    return response.data;
  },
  delete: async (projectId, deviceId) => {
    const response = await apiClient.delete(`/api/projects/${projectId}/site-devices/${deviceId}`);
    return response.data;
  },
  toggle: async (projectId, deviceId) => {
    const response = await apiClient.put(`/api/projects/${projectId}/site-devices/${deviceId}/toggle`);
    return response.data;
  },
};

// Dropbox API for project-specific integration
const dropboxAPI = {
  linkFolder: async (projectId, folderPath) => {
    const response = await apiClient.post(`/api/projects/${projectId}/link-dropbox`, {
      folder_path: folderPath,
    });
    return response.data;
  },
  getFiles: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/dropbox-files`);
    return response.data;
  },
};

export default function ProjectDetailScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [project, setProject] = useState(null);
  const { getProjectById } = useProjects();
  const { getActiveCheckIns } = useCheckIns();
  const [stats, setStats] = useState({
    onSiteWorkers: 0,
    subcontractors: 0,
    subcontractorCount: 0,
  });
  const [workersByCompany, setWorkersByCompany] = useState([]);
  
  // NFC management
  const [showAddNfcModal, setShowAddNfcModal] = useState(false);
  const [nfcTagId, setNfcTagId] = useState('');
  const [nfcLocation, setNfcLocation] = useState('');
  const [addingNfc, setAddingNfc] = useState(false);
  const [scanningNfc, setScanningNfc] = useState(false);
  const [nfcSupported, setNfcSupported] = useState(false);
  const [nfcEnabled, setNfcEnabled] = useState(false);
  const [nfcTags, setNfcTags] = useState([]);

  // Site devices management
  const [siteDevices, setSiteDevices] = useState([]);
  const [showAddDeviceModal, setShowAddDeviceModal] = useState(false);
  const [newDevice, setNewDevice] = useState({
    device_name: '',
    username: '',
    password: '',
  });
  const [addingDevice, setAddingDevice] = useState(false);
  const [showCredentials, setShowCredentials] = useState(null);

  // Dropbox integration
  const [showDropboxModal, setShowDropboxModal] = useState(false);
  const [dropboxFolder, setDropboxFolder] = useState('');
  const [linkingDropbox, setLinkingDropbox] = useState(false);
  const [dropboxFiles, setDropboxFiles] = useState([]);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [checklists, setChecklists] = useState([]);
  const [loadingChecklists, setLoadingChecklists] = useState(false);

  const isAdmin = user?.role === 'admin';

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated && projectId) {
      fetchData();
    }
  }, [isAuthenticated, projectId]);

  // Check NFC capability
  useEffect(() => {
    const checkNfcCapability = async () => {
      await NfcHelper.initNfc();
      const supported = await NfcHelper.isNfcSupported();
      setNfcSupported(supported);
      if (supported) {
        const enabled = await NfcHelper.isNfcEnabled();
        setNfcEnabled(enabled);
      }
    };
    checkNfcCapability();
  }, []);

  const fetchData = async () => {
    try {
      let projectData = await getProjectById(projectId);
      if (!projectData) {
        try {
          projectData = await projectsAPI.getById(projectId);
        } catch (e) {
          console.error('Failed to fetch project from API:', e);
        }
      }
      setProject(projectData);

        try {
          const tags = await projectsAPI.getNfcTags(projectId);
          setNfcTags(Array.isArray(tags) ? tags : []);
        } catch (e) {
          setNfcTags(projectData?.nfc_tags || []);
        }

      // Fetch site devices for this project
      if (isAdmin) {
        try {
          const devices = await siteDevicesAPI.getByProject(projectId);
          setSiteDevices(Array.isArray(devices) ? devices : []);
        } catch (e) {
          setSiteDevices([]);
        }

        // Fetch Dropbox files if connected
        if (projectData.dropbox_enabled && projectData.dropbox_folder) {
          fetchDropboxFiles();
        }
      }

      // Fetch active check-ins for this project
      try {
        const workers = await getActiveCheckIns(projectId);
        
        // Group workers by company
        const grouped = workers.reduce((acc, worker) => {
          const company = worker.company || 'Unassigned';
          if (!acc[company]) {
            acc[company] = [];
          }
          acc[company].push(worker);
          return acc;
        }, {});

        const companiesArray = Object.entries(grouped).map(([name, workers]) => ({
          name,
          workers,
        }));

        setWorkersByCompany(companiesArray);
        setStats({
          onSiteWorkers: workers.length,
          subcontractors: companiesArray.length,
          subcontractorCount: companiesArray.length,
        });
      } catch (e) {
        setStats({ onSiteWorkers: 0, subcontractors: 0, subcontractorCount: 0 });
        setWorkersByCompany([]);
      }
    } catch (error) {
      console.error('Failed to fetch project:', error);
      toast.error('Error', 'Could not load project details');
    } finally {
      fetchChecklists();
      setLoading(false);
      setRefreshing(false);
    }
  };

  const fetchDropboxFiles = async () => {
    setLoadingFiles(true);
    try {
      const result = await dropboxAPI.getFiles(projectId);
      setDropboxFiles(result.files || []);
    } catch (error) {
      console.error('Failed to fetch Dropbox files:', error);
      setDropboxFiles([]);
    } finally {
      setLoadingFiles(false);
    }
  };

  const fetchChecklists = async () => {
    setLoadingChecklists(true);
    try {
      const data = await checklistsAPI.getByProject(projectId);
      setChecklists(data);
    } catch (error) {
      console.error('Failed to fetch checklists:', error);
      setChecklists([]);
    } finally {
      setLoadingChecklists(false);
    }
  };
  
  const onRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const handleScanNfcTag = async () => {
    if (!nfcLocation.trim()) {
      toast.warning('Location Required', 'Please enter the tag location first');
      return;
    }
    if (!nfcEnabled) {
      toast.error('NFC Disabled', 'Please enable NFC in your device settings');
      return;
    }
    setScanningNfc(true);
    toast.info('Ready to Scan', 'Hold your phone near the NFC tag...');
    try {
      const result = await NfcHelper.registerNfcTag(
        projectId,
        'https://blue-view.app'
      );
      if (result.success) {
        toast.success('Tag Scanned!', `Tag ID: ${result.tagId}`);
        
        setAddingNfc(true);
        try {
          const response = await projectsAPI.addNfcTag(projectId, {
            tag_id: result.tagId,
            location_description: nfcLocation,
          });
          
          if (response.project) {
            setProject(response.project);
          }
          
          toast.success('Success!', 'NFC tag registered to project');
          setNfcLocation('');
          setShowAddNfcModal(false);
          await fetchData();
        } catch (error) {
          console.error('Failed to register tag:', error);
          toast.error('Registration Failed', error.response?.data?.detail || 'Could not register tag to project');
        } finally {
          setAddingNfc(false);
        }
      } else {
        toast.error('Scan Failed', result.error || 'Could not scan NFC tag');
      }
    } catch (error) {
      console.error('NFC scan error:', error);
      toast.error('Error', 'Failed to scan NFC tag');
    } finally {
      setScanningNfc(false);
      await NfcHelper.cancelNfc();
    }
  };

  const handleAddNfcTag = async () => {
    if (!nfcTagId.trim() || !nfcLocation.trim()) {
      toast.error('Error', 'Please enter tag ID and location');
      return;
    }

    setAddingNfc(true);
    try {
      await projectsAPI.addNfcTag(projectId, {
        tag_id: nfcTagId,
        location_description: nfcLocation,
      });

      toast.success('Added', 'NFC tag registered successfully');
      setNfcTagId('');
      setNfcLocation('');
      setShowAddNfcModal(false);
      await fetchData();
    } catch (error) {
      console.error('Failed to add NFC tag:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not add NFC tag');
    } finally {
      setAddingNfc(false);
    }
  };

  const handleDeleteNfcTag = (tagId) => {
    const confirmDelete = async () => {
      try {
        await projectsAPI.deleteNfcTag(projectId, tagId);
        toast.success('Deleted', 'NFC tag removed');
        await fetchData();
      } catch (error) {
        console.error('Failed to delete NFC tag:', error);
        toast.error('Error', 'Could not delete NFC tag');
      }
    };

    if (Platform.OS === 'web') {
      if (window.confirm('Remove this NFC tag?')) {
        confirmDelete();
      }
    } else {
      Alert.alert('Remove NFC Tag', 'Are you sure?', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: confirmDelete },
      ]);
    }
  };

  const handleAddDevice = async () => {
    if (!newDevice.username.trim() || !newDevice.password.trim()) {
      toast.error('Error', 'Please fill in username and password');
      return;
    }

    setAddingDevice(true);
    try {
      const result = await siteDevicesAPI.create(projectId, newDevice);
      toast.success('Created', 'Site device created successfully');
      
      setShowCredentials({
        ...result,
        password: newDevice.password,
      });

      setNewDevice({ device_name: '', username: '', password: '' });
      setShowAddDeviceModal(false);
      await fetchData();
    } catch (error) {
      console.error('Failed to create device:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not create site device');
    } finally {
      setAddingDevice(false);
    }
  };

  const handleDeleteDevice = (deviceId) => {
    const confirmDelete = async () => {
      try {
        await siteDevicesAPI.delete(projectId, deviceId);
        toast.success('Deleted', 'Site device removed');
        await fetchData();
      } catch (error) {
        console.error('Failed to delete device:', error);
        toast.error('Error', 'Could not delete site device');
      }
    };

    if (Platform.OS === 'web') {
      if (window.confirm('Remove this site device?')) {
        confirmDelete();
      }
    } else {
      Alert.alert('Remove Site Device', 'Are you sure?', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: confirmDelete },
      ]);
    }
  };

  const handleToggleDevice = async (device) => {
    try {
      await siteDevicesAPI.toggle(projectId, device.id);
      toast.success('Updated', `Device ${device.is_active ? 'disabled' : 'enabled'}`);
      await fetchData();
    } catch (error) {
      console.error('Failed to toggle device:', error);
      toast.error('Error', 'Could not update device');
    }
  };

  const handleLinkDropbox = async () => {
    if (!dropboxFolder.trim()) {
      toast.error('Error', 'Please enter a Dropbox folder path');
      return;
    }

    setLinkingDropbox(true);
    try {
      await dropboxAPI.linkFolder(projectId, dropboxFolder);
      toast.success('Connected', 'Dropbox folder linked successfully');
      setDropboxFolder('');
      setShowDropboxModal(false);
      await fetchData();
    } catch (error) {
      console.error('Failed to link Dropbox:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not link Dropbox folder');
    } finally {
      setLinkingDropbox(false);
    }
  };

  const handleDisconnectDropbox = () => {
    const confirmDisconnect = async () => {
      try {
        await dropboxAPI.linkFolder(projectId, '');
        toast.success('Disconnected', 'Dropbox folder unlinked');
        setDropboxFiles([]);
        await fetchData();
      } catch (error) {
        console.error('Failed to disconnect Dropbox:', error);
        toast.error('Error', 'Could not disconnect Dropbox');
      }
    };

    if (Platform.OS === 'web') {
      if (window.confirm('Disconnect Dropbox folder from this project?')) {
        confirmDisconnect();
      }
    } else {
      Alert.alert('Disconnect Dropbox', 'Remove Dropbox folder link from this project?', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Disconnect', style: 'destructive', onPress: confirmDisconnect },
      ]);
    }
  };

  const quickActions = [
    { title: 'Daily Log', icon: ClipboardList, path: `/daily-log?projectId=${projectId}`, color: '#8b5cf6' },
    { title: 'DOB Compliance', icon: Shield, path: `/project/${projectId}/dob-logs`, color: '#ef4444' },
    { title: 'Permit Renewals', icon: FileCheck, path: `/project/${projectId}/permit-renewal`, color: '#22c55e' },
    { title: 'Report Settings', icon: Settings, path: `/project/${projectId}/report-settings`, color: '#f59e0b' },
  ];

  if (authLoading || loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container}>
          <View style={s.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={s.loadingText}>Loading project...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

    if (!project) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container}>
          <View style={s.loadingContainer}>
            <Text style={s.loadingText}>Project not found</Text>
            <GlassButton title="Go Back" onPress={() => router.back()} />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }
  const isDropboxConnected = project?.dropbox_enabled && project?.dropbox_folder;

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
            <Text style={s.logoText}>BLUEVIEW</Text>
          </View>
          <View style={s.headerRight}>
            <OfflineIndicator />
            <GlassButton
              variant="icon"
              icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={handleLogout}
            />
          </View>
        </View>
        
        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.text.primary} />
          }
        >
          {/* Project Header */}
          <GlassCard style={s.projectHeader}>
            <View style={s.projectTitleRow}>
              <View style={s.projectInfo}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                  <Text style={s.projectName}>{project?.name || 'Project'}</Text>
                  {project?.classification && (
                    <View style={{
                      paddingHorizontal: 8,
                      paddingVertical: 2,
                      borderRadius: 999,
                      backgroundColor: project.classification === 'major' ? 'rgba(245,158,11,0.15)' : 'rgba(59,130,246,0.15)',
                    }}>
                      <Text style={{
                        fontSize: 10,
                        fontWeight: '600',
                        color: project.classification === 'major' ? '#f59e0b' : '#60a5fa',
                      }}>
                        {project.classification.toUpperCase()}
                      </Text>
                    </View>
                  )}
                </View>
                <View style={s.locationRow}>
                  <MapPin size={14} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.locationText}>{project?.location || project?.address || 'No location'}</Text>
                </View>
              </View>
              <View style={s.qrBadge}>
                <QrCode size={20} strokeWidth={1.5} color={colors.text.primary} />
              </View>
            </View>
          </GlassCard>

          {/* Stats Row */}
          <View style={s.statsRow}>
            <StatCard style={s.statCard}>
              <IconPod style={s.statIcon}>
                <Users size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={s.statValue}>{stats.onSiteWorkers}</Text>
              <Text style={s.statLabel}>ON SITE</Text>
            </StatCard>
            <StatCard style={s.statCard}>
              <IconPod style={s.statIcon}>
                <Wifi size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={s.statValue}>{nfcTags.length}</Text>
              <Text style={s.statLabel}>NFC TAGS</Text>
            </StatCard>
            <StatCard style={s.statCard}>
              <IconPod style={s.statIcon}>
                <Smartphone size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={s.statValue}>{siteDevices.length}</Text>
              <Text style={s.statLabel}>DEVICES</Text>
            </StatCard>
          </View>

          {/* Quick Actions */}
          <Text style={s.sectionLabel}>QUICK ACTIONS</Text>
          <View style={s.actionsGrid}>
            {quickActions.map((action) => {
              const Icon = action.icon;
              return (
                <Pressable
                  key={action.title}
                  onPress={() => router.push(action.path)}
                  style={({ pressed }) => [
                    s.actionCard,
                    pressed && s.actionCardPressed,
                  ]}
                >
                  <View style={[s.actionIcon, { backgroundColor: `${action.color}20` }]}>
                    <Icon size={24} strokeWidth={1.5} color={action.color} />
                  </View>
                  <Text style={s.actionTitle}>{action.title}</Text>
                </Pressable>
              );
            })}
          </View>

          <RenewalAlertCard projectId={projectId} />

          {/* NFC Tags Section - Admin Only */}
          {isAdmin && (
            <>
              <View style={s.sectionHeader}>
                <Text style={s.sectionLabel}>NFC CHECK-IN TAGS</Text>
                <GlassButton
                  title="Add Tag"
                  icon={<Plus size={16} color={colors.text.primary} />}
                  onPress={() => setShowAddNfcModal(true)}
                />
              </View>
              
              {nfcTags.length > 0 ? (
                <View style={s.itemsList}>
                  {nfcTags.map((tag) => (
                    <GlassCard key={tag.tag_id} style={s.itemCard}>
                      <View style={s.itemHeader}>
                        <Wifi size={20} strokeWidth={1.5} color="#10b981" />
                        <View style={s.itemInfo}>
                          <Text style={s.itemId}>{tag.tag_id}</Text>
                          <Text style={s.itemLocation}>{tag.location || 'Check-In Point'}</Text>
                        </View>
                        <Pressable
                          onPress={() => handleDeleteNfcTag(tag.tag_id)}
                          style={s.deleteBtn}
                        >
                          <Trash2 size={16} color={colors.status.error} />
                        </Pressable>
                      </View>
                    </GlassCard>
                  ))}
                </View>
              ) : (
                <GlassCard style={s.emptyCard}>
                  <Wifi size={40} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyText}>No NFC tags registered</Text>
                  <Text style={s.emptySubtext}>Add NFC tags for worker check-in</Text>
                </GlassCard>
              )}
            </>
          )}

          {/* Site Devices Section - Admin Only */}
          {isAdmin && (
            <>
              <View style={s.sectionHeader}>
                <Text style={s.sectionLabel}>SITE DEVICES</Text>
                <GlassButton
                  title="Add Device"
                  icon={<Plus size={16} color={colors.text.primary} />}
                  onPress={() => setShowAddDeviceModal(true)}
                />
              </View>
              
              {siteDevices.length > 0 ? (
                <View style={s.itemsList}>
                  {siteDevices.map((device) => (
                    <GlassCard key={device.id} style={s.deviceCard}>
                      <View style={s.deviceHeader}>
                        <Smartphone size={20} strokeWidth={1.5} color={device.is_active ? '#4ade80' : colors.text.muted} />
                        <View style={s.deviceInfo}>
                          <Text style={s.deviceName}>{device.device_name}</Text>
                          <Text style={s.deviceUsername}>@{device.username}</Text>
                        </View>
                        <View style={[s.deviceStatusBadge, device.is_active && s.deviceStatusActive]}>
                          <Text style={[s.deviceStatusText, device.is_active && s.deviceStatusTextActive]}>
                            {device.is_active ? 'Active' : 'Disabled'}
                          </Text>
                        </View>
                      </View>
                      <View style={s.deviceActions}>
                        <GlassButton
                          title={device.is_active ? 'Disable' : 'Enable'}
                          onPress={() => handleToggleDevice(device)}
                          style={s.toggleBtn}
                        />
                        <Pressable
                          onPress={() => handleDeleteDevice(device.id)}
                          style={s.deleteBtn}
                        >
                          <Trash2 size={16} color={colors.status.error} />
                        </Pressable>
                      </View>
                    </GlassCard>
                  ))}
                </View>
              ) : (
                <GlassCard style={s.emptyCard}>
                  <Smartphone size={40} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyText}>No site devices registered</Text>
                  <Text style={s.emptySubtext}>Add devices for on-site access</Text>
                </GlassCard>
              )}
            </>
          )}
          
          {/* Permit Renewal Alert */}
          <RenewalAlertCard projectId={projectId} />
          
          {/* Dropbox Integration Section - Admin Only */}
          {isAdmin && (
            <>
              <View style={s.sectionHeader}>
                <Text style={s.sectionLabel}>DROPBOX INTEGRATION</Text>
                {!isDropboxConnected && (
                  <GlassButton
                    title="Link Folder"
                    icon={<LinkIcon size={16} color={colors.text.primary} />}
                    onPress={() => setShowDropboxModal(true)}
                  />
                )}
              </View>
              
              {isDropboxConnected ? (
                <View style={s.itemsList}>
                  <GlassCard style={s.dropboxCard}>
                    <View style={s.dropboxHeader}>
                      <Cloud size={20} strokeWidth={1.5} color="#0061FF" />
                      <View style={s.dropboxInfo}>
                        <Text style={s.dropboxTitle}>Connected Folder</Text>
                        <Text style={s.dropboxPath}>{project.dropbox_folder}</Text>
                      </View>
                      <Pressable
                        onPress={handleDisconnectDropbox}
                        style={s.disconnectBtn}
                      >
                        <Text style={s.disconnectText}>Disconnect</Text>
                      </Pressable>
                    </View>

                    {loadingFiles ? (
                      <View style={s.filesLoading}>
                        <ActivityIndicator size="small" color={colors.text.primary} />
                        <Text style={s.filesLoadingText}>Loading files...</Text>
                      </View>
                    ) : dropboxFiles.length > 0 ? (
                      <View style={s.filesList}>
                        <Text style={s.filesHeader}>FILES ({dropboxFiles.length})</Text>
                        {dropboxFiles.map((file, idx) => (
                          <View key={idx} style={s.fileRow}>
                            <FileText size={16} strokeWidth={1.5} color={colors.text.muted} />
                            <Text style={s.fileName} numberOfLines={1}>{file.name}</Text>
                          </View>
                        ))}
                      </View>
                    ) : (
                      <View style={s.noFiles}>
                        <Text style={s.noFilesText}>No files in this folder</Text>
                      </View>
                    )}
                  </GlassCard>
                </View>
              ) : (
                <GlassCard style={s.emptyCard}>
                  <Cloud size={40} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyText}>No Dropbox folder linked</Text>
                  <Text style={s.emptySubtext}>Link a Dropbox folder to share project documents</Text>
                </GlassCard>
              )}
            </>
          )}

          {/* On-Site Workers */}
          <Text style={s.sectionLabel}>ON-SITE WORKERS</Text>
          {workersByCompany.length > 0 ? (
            workersByCompany.map((company) => (
              <GlassCard key={company.name} style={s.companyCard}>
                <View style={s.companyHeader}>
                  <Building2 size={18} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.companyName}>{company.name}</Text>
                  <View style={s.workerCount}>
                    <Text style={s.workerCountText}>{company.workers.length}</Text>
                  </View>
                </View>
                <View style={s.workerTags}>
                  {company.workers.map((worker, idx) => (
                    <View key={idx} style={s.workerTag}>
                      <Text style={s.workerTagName}>{worker.name || worker.worker_name}</Text>
                      <Text style={s.workerTagTrade}>{worker.trade || 'Worker'}</Text>
                    </View>
                  ))}
                </View>
              </GlassCard>
            ))
          ) : (
            <GlassCard style={s.emptyCard}>
              <Users size={40} strokeWidth={1} color={colors.text.subtle} />
              <Text style={s.emptyText}>No workers on site</Text>
              <Text style={s.emptySubtext}>Workers will appear here when they check in</Text>
            </GlassCard>
          )}

          {/* Checklists Section */}
          <Text style={s.sectionLabel}>CHECKLISTS (OTA-TEST)</Text>
          {loadingChecklists ? (
            <ActivityIndicator size="small" color={colors.text.primary} style={{ marginVertical: spacing.lg }} />
          ) : checklists.length > 0 ? (
            <View style={s.itemsList}>
              {checklists.map((assignment) => {
                const completedCount = assignment.completions?.filter(
                  c => c.progress?.completed === c.progress?.total
                ).length || 0;
                const totalAssigned = assignment.assigned_users?.length || 0;
                const allComplete = completedCount === totalAssigned && totalAssigned > 0;

                return (
                  <GlassCard key={assignment.id} style={s.checklistCard}>
                    <View style={s.checklistHeader}>
                      <View style={s.checklistInfo}>
                        <Text style={s.checklistTitle}>
                          {assignment.checklist?.title || 'Checklist'}
                        </Text>
                        {assignment.checklist?.description && (
                          <Text style={s.checklistDescription} numberOfLines={2}>
                            {assignment.checklist.description}
                          </Text>
                        )}
                      </View>
                      {allComplete ? (
                        <CheckCircle size={24} strokeWidth={1.5} color="#4ade80" />
                      ) : (
                        <Clock size={24} strokeWidth={1.5} color="#f59e0b" />
                      )}
                    </View>

                    <View style={s.checklistStats}>
                      <View style={s.checklistStatItem}>
                        <Text style={s.checklistStatLabel}>Items</Text>
                        <Text style={s.checklistStatValue}>
                          {assignment.checklist?.items?.length || 0}
                        </Text>
                      </View>
                      <View style={s.checklistStatDivider} />
                      <View style={s.checklistStatItem}>
                        <Text style={s.checklistStatLabel}>Assigned</Text>
                        <Text style={s.checklistStatValue}>{totalAssigned}</Text>
                      </View>
                      <View style={s.checklistStatDivider} />
                      <View style={s.checklistStatItem}>
                        <Text style={s.checklistStatLabel}>Complete</Text>
                        <Text style={[
                          s.checklistStatValue,
                          allComplete && s.checklistStatValueComplete
                        ]}>
                          {completedCount}/{totalAssigned}
                        </Text>
                      </View>
                    </View>

                    {assignment.assigned_users && assignment.assigned_users.length > 0 && (
                      <View style={s.assignedUsers}>
                        <Text style={s.assignedUsersLabel}>Assigned to:</Text>
                        <View style={s.assignedUsersList}>
                          {assignment.assigned_users.map((user) => {
                            const userCompletion = assignment.completions?.find(
                              c => c.user_id === user.id
                            );
                            const progress = userCompletion?.progress || { completed: 0, total: 0 };
                            const isComplete = progress.completed === progress.total && progress.total > 0;

                            return (
                              <View key={user.id} style={s.assignedUserItem}>
                                <View style={s.assignedUserInfo}>
                                  <Text style={s.assignedUserName}>{user.name}</Text>
                                  <Text style={s.assignedUserProgress}>
                                    {progress.completed}/{progress.total}
                                  </Text>
                                </View>
                                {isComplete && (
                                  <CheckCircle size={14} strokeWidth={1.5} color="#4ade80" />
                                )}
                              </View>
                            );
                          })}
                        </View>
                      </View>
                    )}
                  </GlassCard>
                );
              })}
            </View>
          ) : (
            <GlassCard style={s.emptyCard}>
              <ClipboardList size={40} strokeWidth={1} color={colors.text.subtle} />
              <Text style={s.emptyText}>No checklists assigned</Text>
              <Text style={s.emptySubtext}>Checklists will appear here when assigned to this project</Text>
            </GlassCard>
          )}
        </ScrollView>

        {/* Add NFC Tag Modal */}
        <Modal
          visible={showAddNfcModal}
          transparent
          animationType="slide"
          onRequestClose={() => {
            setShowAddNfcModal(false);
            NfcHelper.cancelNfc();
          }}
        >
          <View style={s.modalOverlay}>
            <Pressable 
              style={s.modalBackdrop} 
              onPress={() => {
                setShowAddNfcModal(false);
                NfcHelper.cancelNfc();
              }} 
            />
            <View style={s.modalContent}>
              <GlassCard variant="modal" style={s.modalCard}>
                <View style={s.modalHeader}>
                  <Text style={s.modalTitle}>Register NFC Tag</Text>
                  <Pressable 
                    onPress={() => {
                      setShowAddNfcModal(false);
                      NfcHelper.cancelNfc();
                    }}
                  >
                    <X size={24} color={colors.text.primary} />
                  </Pressable>
                </View>

                <Text style={s.modalInstructions}>
                  {nfcSupported 
                    ? 'Scan a blank NFC tag to automatically program it with this project\'s check-in link.'
                    : 'NFC not available. You can register tags manually by entering the tag ID.'}
                </Text>

                <View style={s.modalForm}>
                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>LOCATION *</Text>
                    <GlassInput
                      value={nfcLocation}
                      onChangeText={setNfcLocation}
                      placeholder="e.g., Main Entrance, Building A Gate"
                      editable={!scanningNfc && !addingNfc}
                    />
                    <Text style={s.inputHint}>
                      Where is this NFC tag located?
                    </Text>
                  </View>

                  {nfcSupported && (
                    <>
                      <View style={s.scanSection}>
                        <View style={s.scanHeader}>
                          <Radio size={20} strokeWidth={1.5} color="#3b82f6" />
                          <Text style={s.scanTitle}>Scan NFC Tag</Text>
                        </View>

                        {!nfcEnabled && (
                          <View style={s.warningBox}>
                            <Text style={s.warningText}>
                              ⚠️ NFC is disabled. Please enable NFC in your device settings.
                            </Text>
                          </View>
                        )}

                        <GlassButton
                          title={scanningNfc ? 'Scanning... Hold phone near tag' : 'Scan & Program Tag'}
                          icon={
                            <Zap 
                              size={20} 
                              strokeWidth={1.5} 
                              color={scanningNfc ? '#4ade80' : colors.text.primary} 
                            />
                          }
                          onPress={handleScanNfcTag}
                          loading={scanningNfc}
                          disabled={!nfcLocation.trim() || !nfcEnabled || addingNfc}
                          style={[
                            s.scanButton,
                            scanningNfc && s.scanButtonActive,
                          ]}
                        />

                        <View style={s.infoBox}>
                          <Text style={s.infoText}>
                            💡 This will read the tag ID and write the check-in URL to the tag automatically.
                          </Text>
                        </View>
                      </View>

                      <View style={s.divider}>
                        <View style={s.dividerLine} />
                        <Text style={s.dividerText}>OR</Text>
                        <View style={s.dividerLine} />
                      </View>
                    </>
                  )}

                  <View style={s.manualSection}>
                    <Text style={s.manualTitle}>Manual Entry</Text>
                    
                    <View style={s.inputGroup}>
                      <Text style={s.inputLabel}>TAG ID</Text>
                      <GlassInput
                        value={nfcTagId}
                        onChangeText={setNfcTagId}
                        placeholder="e.g., 04:A1:B2:C3:D4:E5:F6"
                        editable={!scanningNfc && !addingNfc}
                      />
                      <Text style={s.inputHint}>
                        Enter the NFC tag ID manually if scanning is unavailable
                      </Text>
                    </View>

                    <GlassButton
                      title={addingNfc ? 'Adding...' : 'Add Manually'}
                      onPress={handleAddNfcTag}
                      loading={addingNfc}
                      disabled={!nfcTagId.trim() || !nfcLocation.trim() || scanningNfc}
                      style={s.manualButton}
                    />
                  </View>
                </View>
              </GlassCard>
            </View>
          </View>
        </Modal>

        {/* Add Site Device Modal */}
        <Modal
          visible={showAddDeviceModal}
          transparent
          animationType="slide"
          onRequestClose={() => setShowAddDeviceModal(false)}
        >
          <View style={s.modalOverlay}>
            <Pressable style={s.modalBackdrop} onPress={() => setShowAddDeviceModal(false)} />
            <View style={s.modalContent}>
              <GlassCard variant="modal" style={s.modalCard}>
                <View style={s.modalHeader}>
                  <Text style={s.modalTitle}>Add Site Device</Text>
                  <Pressable onPress={() => setShowAddDeviceModal(false)}>
                    <X size={24} color={colors.text.primary} />
                  </Pressable>
                </View>

                <Text style={s.modalDesc}>
                  Create credentials for an on-site device (tablet or phone) to access this project.
                </Text>

                <View style={s.modalForm}>
                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>DEVICE NAME</Text>
                    <GlassInput
                      value={newDevice.device_name}
                      onChangeText={(val) => setNewDevice({ ...newDevice, device_name: val })}
                      placeholder="e.g., Site Tablet 1"
                    />
                  </View>

                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>USERNAME</Text>
                    <GlassInput
                      value={newDevice.username}
                      onChangeText={(val) => setNewDevice({ ...newDevice, username: val })}
                      placeholder="e.g., site-tablet-1"
                      autoCapitalize="none"
                    />
                  </View>

                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>PASSWORD</Text>
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

                  <GlassButton
                    title={addingDevice ? 'Creating...' : 'Create Device'}
                    onPress={handleAddDevice}
                    loading={addingDevice}
                    style={s.addButton}
                  />
                </View>
              </GlassCard>
            </View>
          </View>
        </Modal>

        {/* Link Dropbox Folder Modal */}
        <Modal
          visible={showDropboxModal}
          transparent
          animationType="slide"
          onRequestClose={() => setShowDropboxModal(false)}
        >
          <View style={s.modalOverlay}>
            <Pressable style={s.modalBackdrop} onPress={() => setShowDropboxModal(false)} />
            <View style={s.modalContent}>
              <GlassCard variant="modal" style={s.modalCard}>
                <View style={s.modalHeader}>
                  <Text style={s.modalTitle}>Link Dropbox Folder</Text>
                  <Pressable onPress={() => setShowDropboxModal(false)}>
                    <X size={24} color={colors.text.primary} />
                  </Pressable>
                </View>

                <Text style={s.modalDesc}>
                  Enter the path to your Dropbox folder containing project documents.
                </Text>

                <View style={s.modalForm}>
                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>FOLDER PATH</Text>
                    <GlassInput
                      value={dropboxFolder}
                      onChangeText={setDropboxFolder}
                      placeholder="/Projects/Downtown Building"
                    />
                  </View>

                  <View style={s.infoBox}>
                    <Folder size={16} strokeWidth={1.5} color="#0061FF" />
                    <Text style={s.infoText}>
                      All users you create will be able to view files from this folder.
                    </Text>
                  </View>

                  <GlassButton
                    title={linkingDropbox ? 'Linking...' : 'Link Folder'}
                    onPress={handleLinkDropbox}
                    loading={linkingDropbox}
                    style={s.addButton}
                  />
                </View>
              </GlassCard>
            </View>
          </View>
        </Modal>

        {/* Credentials Display Modal */}
        <Modal
          visible={!!showCredentials}
          transparent
          animationType="fade"
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
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
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
  projectHeader: {
    marginBottom: spacing.lg,
  },
  projectTitleRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  projectInfo: {
    flex: 1,
  },
  projectName: {
    fontSize: 28,
    fontWeight: '300',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  locationRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  locationText: {
    fontSize: 14,
    color: colors.text.muted,
  },
  qrBadge: {
    width: 44,
    height: 44,
    borderRadius: borderRadius.md,
    backgroundColor: colors.glass.background,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  statsRow: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.xl,
  },
  statCard: {
    flex: 1,
  },
  statIcon: {
    marginBottom: spacing.sm,
  },
  statValue: {
    fontSize: 28,
    fontWeight: '200',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  statLabel: {
    ...typography.label,
    fontSize: 9,
    color: colors.text.muted,
  },
  sectionLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.md,
    paddingHorizontal: spacing.xs,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
    paddingHorizontal: spacing.xs,
  },
  actionsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.md,
    marginBottom: spacing.xl,
  },
  actionCard: {
    width: '47%',
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.lg,
    alignItems: 'center',
    gap: spacing.sm,
  },
  actionCardPressed: {
    opacity: 0.8,
    transform: [{ scale: 0.98 }],
  },
  actionIcon: {
    width: 56,
    height: 56,
    borderRadius: borderRadius.lg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionTitle: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  itemsList: {
    gap: spacing.sm,
    marginBottom: spacing.xl,
  },
  itemCard: {
    padding: spacing.md,
  },
  itemHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  itemInfo: {
    flex: 1,
  },
  itemId: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  itemLocation: {
    fontSize: 13,
    color: colors.text.muted,
  },
  deleteBtn: {
    padding: spacing.sm,
  },
  deviceCard: {
    padding: spacing.md,
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
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
  },
  deviceUsername: {
    fontSize: 13,
    color: colors.text.muted,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  deviceStatusBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: 'rgba(100, 116, 139, 0.2)',
    borderRadius: borderRadius.full,
  },
  deviceStatusActive: {
    backgroundColor: 'rgba(74, 222, 128, 0.15)',
  },
  deviceStatusText: {
    fontSize: 11,
    fontWeight: '500',
    color: colors.text.muted,
  },
  deviceStatusTextActive: {
    color: '#4ade80',
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
  dropboxCard: {
    padding: spacing.md,
  },
  dropboxHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.md,
    paddingBottom: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.glass.border,
  },
  dropboxInfo: {
    flex: 1,
  },
  dropboxTitle: {
    fontSize: 13,
    color: colors.text.muted,
    marginBottom: 2,
  },
  dropboxPath: {
    fontSize: 14,
    fontWeight: '500',
    color: '#0061FF',
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  disconnectBtn: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  disconnectText: {
    fontSize: 13,
    color: colors.status.error,
  },
  filesLoading: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.md,
  },
  filesLoadingText: {
    fontSize: 13,
    color: colors.text.muted,
  },
  filesList: {
    gap: spacing.xs,
  },
  filesHeader: {
    ...typography.label,
    fontSize: 10,
    color: colors.text.muted,
    marginBottom: spacing.xs,
  },
  fileRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  fileName: {
    flex: 1,
    fontSize: 13,
    color: colors.text.primary,
  },
  noFiles: {
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  noFilesText: {
    fontSize: 13,
    color: colors.text.muted,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xl,
    gap: spacing.sm,
    marginBottom: spacing.xl,
  },
  emptyText: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.muted,
  },
  emptySubtext: {
    fontSize: 13,
    color: colors.text.subtle,
  },
  companyCard: {
    marginBottom: spacing.md,
  },
  companyHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  companyName: {
    flex: 1,
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  workerCount: {
    backgroundColor: colors.glass.background,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
  },
  workerCountText: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.text.primary,
  },
  workerTags: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  workerTag: {
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  workerTagName: {
    fontSize: 13,
    fontWeight: '500',
    color: colors.text.primary,
  },
  workerTagTrade: {
    fontSize: 11,
    color: colors.text.muted,
  },
  modalOverlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  modalBackdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0, 0, 0, 0.85)',
  },
  modalContent: {
    padding: spacing.lg,
  },
  modalCard: {
    maxWidth: 500,
    alignSelf: 'center',
    width: '100%',
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
  },
  modalDesc: {
    fontSize: 14,
    color: colors.text.muted,
    marginBottom: spacing.lg,
  },
  modalForm: {
    gap: spacing.md,
  },
  inputGroup: {
    gap: spacing.sm,
  },
  inputLabel: {
    ...typography.label,
    color: colors.text.muted,
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
  addButton: {
    marginTop: spacing.sm,
  },
  credentialsModal: {
    backgroundColor: '#1a1a2e',
    borderRadius: borderRadius.xxl,
    padding: spacing.xl,
    maxWidth: 400,
    alignSelf: 'center',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.glass.border,
    margin: spacing.lg,
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
  credentialLabel: {
    ...typography.label,
    color: colors.text.muted,
  },
  credentialValueBold: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  credentialValueMono: {
    fontSize: 14,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    color: '#4ade80',
  },
  doneBtn: {
    width: '100%',
  },
  modalInstructions: {
    fontSize: 14,
    color: colors.text.muted,
    lineHeight: 20,
    marginBottom: spacing.lg,
  },
  inputHint: {
    fontSize: 12,
    color: colors.text.subtle,
    marginTop: spacing.xs,
  },
  scanSection: {
    marginBottom: spacing.lg,
  },
  scanHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  scanTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  warningBox: {
    backgroundColor: 'rgba(245, 158, 11, 0.1)',
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: 'rgba(245, 158, 11, 0.3)',
    marginBottom: spacing.md,
  },
  warningText: {
    fontSize: 13,
    color: '#f59e0b',
    lineHeight: 18,
  },
  scanButton: {
    backgroundColor: 'rgba(59, 130, 246, 0.1)',
    borderColor: 'rgba(59, 130, 246, 0.3)',
  },
  scanButtonActive: {
    backgroundColor: 'rgba(74, 222, 128, 0.1)',
    borderColor: 'rgba(74, 222, 128, 0.3)',
  },
  divider: {
    flexDirection: 'row',
    alignItems: 'center',
    marginVertical: spacing.lg,
  },
  dividerLine: {
    flex: 1,
    height: 1,
    backgroundColor: colors.glass.border,
  },
  dividerText: {
    ...typography.label,
    fontSize: 11,
    color: colors.text.subtle,
    paddingHorizontal: spacing.md,
  },
  manualSection: {
    // manual section styles
  },
  manualTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.md,
  },
  manualButton: {
    marginTop: spacing.sm,
  },
  checklistCard: {
    marginBottom: spacing.md,
    padding: spacing.lg,
  },
  checklistHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  checklistInfo: {
    flex: 1,
    marginRight: spacing.md,
  },
  checklistTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  checklistDescription: {
    fontSize: 13,
    color: colors.text.secondary,
    lineHeight: 18,
  },
  checklistStats: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.md,
    marginBottom: spacing.md,
    backgroundColor: 'rgba(255,255,255,0.03)',
    borderRadius: borderRadius.md,
  },
  checklistStatItem: {
    flex: 1,
    alignItems: 'center',
  },
  checklistStatLabel: {
    fontSize: 10,
    color: colors.text.muted,
    marginBottom: spacing.xs,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  checklistStatValue: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text.primary,
  },
  checklistStatValueComplete: {
    color: '#4ade80',
  },
  checklistStatDivider: {
    width: 1,
    height: 28,
    backgroundColor: colors.glass.border,
  },
  assignedUsers: {
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.glass.border,
  },
  assignedUsersLabel: {
    fontSize: 11,
    color: colors.text.muted,
    marginBottom: spacing.sm,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  assignedUsersList: {
    gap: spacing.sm,
  },
  assignedUserItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.xs,
  },
  assignedUserInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    flex: 1,
  },
  assignedUserName: {
    fontSize: 13,
    color: colors.text.primary,
  },
  assignedUserProgress: {
    fontSize: 11,
    color: colors.text.muted,
  },
});
}
