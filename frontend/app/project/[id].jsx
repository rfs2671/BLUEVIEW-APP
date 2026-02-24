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
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod } from '../../src/components/GlassCard';
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
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

// Site device API for project-specific devices
const siteDevicesAPI = {
  getByProject: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/site-devices`);
    return response.data;
  },
  create: async (projectId, deviceData) => {
    const response = await apiClient.post(`/api/projects/${projectId}/site-devices`, deviceData);
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
    if (!newDevice.device_name.trim() || !newDevice.username.trim() || !newDevice.password.trim()) {
      toast.error('Error', 'Please fill in all fields');
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
    { title: 'Check-In', icon: QrCode, path: `/checkin?projectId=${projectId}`, color: '#3b82f6' },
    { title: 'Daily Log', icon: ClipboardList, path: `/daily-log?projectId=${projectId}`, color: '#8b5cf6' },
    { title: 'Report Settings', icon: Settings, path: `/project/${projectId}/report-settings`, color: '#f59e0b' },
  ];

  if (authLoading || loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={styles.loadingText}>Loading project...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

    if (!project) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.loadingContainer}>
            <Text style={styles.loadingText}>Project not found</Text>
            <GlassButton title="Go Back" onPress={() => router.back()} />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }
  const isDropboxConnected = project?.dropbox_enabled && project?.dropbox_folder;

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.back()}
            />
            <Text style={styles.logoText}>BLUEVIEW</Text>
          </View>
          <View style={styles.headerRight}>
            <OfflineIndicator />
            <GlassButton
              variant="icon"
              icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={handleLogout}
            />
          </View>
        </View>
        
        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.text.primary} />
          }
        >
          {/* Project Header */}
          <GlassCard style={styles.projectHeader}>
            <View style={styles.projectTitleRow}>
              <View style={styles.projectInfo}>
                <Text style={styles.projectName}>{project?.name || 'Project'}</Text>
                <View style={styles.locationRow}>
                  <MapPin size={14} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={styles.locationText}>{project?.location || project?.address || 'No location'}</Text>
                </View>
              </View>
              <View style={styles.qrBadge}>
                <QrCode size={20} strokeWidth={1.5} color={colors.text.primary} />
              </View>
            </View>
          </GlassCard>

          {/* Stats Row */}
          <View style={styles.statsRow}>
            <StatCard style={styles.statCard}>
              <IconPod style={styles.statIcon}>
                <Users size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={styles.statValue}>{stats.onSiteWorkers}</Text>
              <Text style={styles.statLabel}>ON SITE</Text>
            </StatCard>
            <StatCard style={styles.statCard}>
              <IconPod style={styles.statIcon}>
                <Wifi size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={styles.statValue}>{nfcTags.length}</Text>
              <Text style={styles.statLabel}>NFC TAGS</Text>
            </StatCard>
            <StatCard style={styles.statCard}>
              <IconPod style={styles.statIcon}>
                <Smartphone size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={styles.statValue}>{siteDevices.length}</Text>
              <Text style={styles.statLabel}>DEVICES</Text>
            </StatCard>
          </View>

          {/* Quick Actions */}
          <Text style={styles.sectionLabel}>QUICK ACTIONS</Text>
          <View style={styles.actionsGrid}>
            {quickActions.map((action) => {
              const Icon = action.icon;
              return (
                <Pressable
                  key={action.title}
                  onPress={() => router.push(action.path)}
                  style={({ pressed }) => [
                    styles.actionCard,
                    pressed && styles.actionCardPressed,
                  ]}
                >
                  <View style={[styles.actionIcon, { backgroundColor: `${action.color}20` }]}>
                    <Icon size={24} strokeWidth={1.5} color={action.color} />
                  </View>
                  <Text style={styles.actionTitle}>{action.title}</Text>
                </Pressable>
              );
            })}
          </View>

          {/* NFC Tags Section - Admin Only */}
          {isAdmin && (
            <>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionLabel}>NFC CHECK-IN TAGS</Text>
                <GlassButton
                  title="Add Tag"
                  icon={<Plus size={16} color={colors.text.primary} />}
                  onPress={() => setShowAddNfcModal(true)}
                />
              </View>
              
              {nfcTags.length > 0 ? (
                <View style={styles.itemsList}>
                  {nfcTags.map((tag) => (
                    <GlassCard key={tag.tag_id} style={styles.itemCard}>
                      <View style={styles.itemHeader}>
                        <Wifi size={20} strokeWidth={1.5} color="#10b981" />
                        <View style={styles.itemInfo}>
                          <Text style={styles.itemId}>{tag.tag_id}</Text>
                          <Text style={styles.itemLocation}>{tag.location || 'Check-In Point'}</Text>
                        </View>
                        <Pressable
                          onPress={() => handleDeleteNfcTag(tag.tag_id)}
                          style={styles.deleteBtn}
                        >
                          <Trash2 size={16} color={colors.status.error} />
                        </Pressable>
                      </View>
                    </GlassCard>
                  ))}
                </View>
              ) : (
                <GlassCard style={styles.emptyCard}>
                  <Wifi size={40} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={styles.emptyText}>No NFC tags registered</Text>
                  <Text style={styles.emptySubtext}>Add NFC tags for worker check-in</Text>
                </GlassCard>
              )}
            </>
          )}

          {/* Site Devices Section - Admin Only */}
          {isAdmin && (
            <>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionLabel}>SITE DEVICES</Text>
                <GlassButton
                  title="Add Device"
                  icon={<Plus size={16} color={colors.text.primary} />}
                  onPress={() => setShowAddDeviceModal(true)}
                />
              </View>
              
              {siteDevices.length > 0 ? (
                <View style={styles.itemsList}>
                  {siteDevices.map((device) => (
                    <GlassCard key={device.id} style={styles.deviceCard}>
                      <View style={styles.deviceHeader}>
                        <Smartphone size={20} strokeWidth={1.5} color={device.is_active ? '#4ade80' : colors.text.muted} />
                        <View style={styles.deviceInfo}>
                          <Text style={styles.deviceName}>{device.device_name}</Text>
                          <Text style={styles.deviceUsername}>@{device.username}</Text>
                        </View>
                        <View style={[styles.deviceStatusBadge, device.is_active && styles.deviceStatusActive]}>
                          <Text style={[styles.deviceStatusText, device.is_active && styles.deviceStatusTextActive]}>
                            {device.is_active ? 'Active' : 'Disabled'}
                          </Text>
                        </View>
                      </View>
                      <View style={styles.deviceActions}>
                        <GlassButton
                          title={device.is_active ? 'Disable' : 'Enable'}
                          onPress={() => handleToggleDevice(device)}
                          style={styles.toggleBtn}
                        />
                        <Pressable
                          onPress={() => handleDeleteDevice(device.id)}
                          style={styles.deleteBtn}
                        >
                          <Trash2 size={16} color={colors.status.error} />
                        </Pressable>
                      </View>
                    </GlassCard>
                  ))}
                </View>
              ) : (
                <GlassCard style={styles.emptyCard}>
                  <Smartphone size={40} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={styles.emptyText}>No site devices registered</Text>
                  <Text style={styles.emptySubtext}>Add devices for on-site access</Text>
                </GlassCard>
              )}
            </>
          )}

          {/* Dropbox Integration Section - Admin Only */}
          {isAdmin && (
            <>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionLabel}>DROPBOX INTEGRATION</Text>
                {!isDropboxConnected && (
                  <GlassButton
                    title="Link Folder"
                    icon={<LinkIcon size={16} color={colors.text.primary} />}
                    onPress={() => setShowDropboxModal(true)}
                  />
                )}
              </View>
              
              {isDropboxConnected ? (
                <View style={styles.itemsList}>
                  <GlassCard style={styles.dropboxCard}>
                    <View style={styles.dropboxHeader}>
                      <Cloud size={20} strokeWidth={1.5} color="#0061FF" />
                      <View style={styles.dropboxInfo}>
                        <Text style={styles.dropboxTitle}>Connected Folder</Text>
                        <Text style={styles.dropboxPath}>{project.dropbox_folder}</Text>
                      </View>
                      <Pressable
                        onPress={handleDisconnectDropbox}
                        style={styles.disconnectBtn}
                      >
                        <Text style={styles.disconnectText}>Disconnect</Text>
                      </Pressable>
                    </View>

                    {loadingFiles ? (
                      <View style={styles.filesLoading}>
                        <ActivityIndicator size="small" color={colors.text.primary} />
                        <Text style={styles.filesLoadingText}>Loading files...</Text>
                      </View>
                    ) : dropboxFiles.length > 0 ? (
                      <View style={styles.filesList}>
                        <Text style={styles.filesHeader}>FILES ({dropboxFiles.length})</Text>
                        {dropboxFiles.map((file, idx) => (
                          <View key={idx} style={styles.fileRow}>
                            <FileText size={16} strokeWidth={1.5} color={colors.text.muted} />
                            <Text style={styles.fileName} numberOfLines={1}>{file.name}</Text>
                          </View>
                        ))}
                      </View>
                    ) : (
                      <View style={styles.noFiles}>
                        <Text style={styles.noFilesText}>No files in this folder</Text>
                      </View>
                    )}
                  </GlassCard>
                </View>
              ) : (
                <GlassCard style={styles.emptyCard}>
                  <Cloud size={40} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={styles.emptyText}>No Dropbox folder linked</Text>
                  <Text style={styles.emptySubtext}>Link a Dropbox folder to share project documents</Text>
                </GlassCard>
              )}
            </>
          )}

          {/* On-Site Workers */}
          <Text style={styles.sectionLabel}>ON-SITE WORKERS</Text>
          {workersByCompany.length > 0 ? (
            workersByCompany.map((company) => (
              <GlassCard key={company.name} style={styles.companyCard}>
                <View style={styles.companyHeader}>
                  <Building2 size={18} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={styles.companyName}>{company.name}</Text>
                  <View style={styles.workerCount}>
                    <Text style={styles.workerCountText}>{company.workers.length}</Text>
                  </View>
                </View>
                <View style={styles.workerTags}>
                  {company.workers.map((worker, idx) => (
                    <View key={idx} style={styles.workerTag}>
                      <Text style={styles.workerTagName}>{worker.name || worker.worker_name}</Text>
                      <Text style={styles.workerTagTrade}>{worker.trade || 'Worker'}</Text>
                    </View>
                  ))}
                </View>
              </GlassCard>
            ))
          ) : (
            <GlassCard style={styles.emptyCard}>
              <Users size={40} strokeWidth={1} color={colors.text.subtle} />
              <Text style={styles.emptyText}>No workers on site</Text>
              <Text style={styles.emptySubtext}>Workers will appear here when they check in</Text>
            </GlassCard>
          )}

          {/* Checklists Section */}
          <Text style={styles.sectionLabel}>CHECKLISTS (OTA-TEST)</Text>
          {loadingChecklists ? (
            <ActivityIndicator size="small" color={colors.text.primary} style={{ marginVertical: spacing.lg }} />
          ) : checklists.length > 0 ? (
            <View style={styles.itemsList}>
              {checklists.map((assignment) => {
                const completedCount = assignment.completions?.filter(
                  c => c.progress?.completed === c.progress?.total
                ).length || 0;
                const totalAssigned = assignment.assigned_users?.length || 0;
                const allComplete = completedCount === totalAssigned && totalAssigned > 0;

                return (
                  <GlassCard key={assignment.id} style={styles.checklistCard}>
                    <View style={styles.checklistHeader}>
                      <View style={styles.checklistInfo}>
                        <Text style={styles.checklistTitle}>
                          {assignment.checklist?.title || 'Checklist'}
                        </Text>
                        {assignment.checklist?.description && (
                          <Text style={styles.checklistDescription} numberOfLines={2}>
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

                    <View style={styles.checklistStats}>
                      <View style={styles.checklistStatItem}>
                        <Text style={styles.checklistStatLabel}>Items</Text>
                        <Text style={styles.checklistStatValue}>
                          {assignment.checklist?.items?.length || 0}
                        </Text>
                      </View>
                      <View style={styles.checklistStatDivider} />
                      <View style={styles.checklistStatItem}>
                        <Text style={styles.checklistStatLabel}>Assigned</Text>
                        <Text style={styles.checklistStatValue}>{totalAssigned}</Text>
                      </View>
                      <View style={styles.checklistStatDivider} />
                      <View style={styles.checklistStatItem}>
                        <Text style={styles.checklistStatLabel}>Complete</Text>
                        <Text style={[
                          styles.checklistStatValue,
                          allComplete && styles.checklistStatValueComplete
                        ]}>
                          {completedCount}/{totalAssigned}
                        </Text>
                      </View>
                    </View>

                    {assignment.assigned_users && assignment.assigned_users.length > 0 && (
                      <View style={styles.assignedUsers}>
                        <Text style={styles.assignedUsersLabel}>Assigned to:</Text>
                        <View style={styles.assignedUsersList}>
                          {assignment.assigned_users.map((user) => {
                            const userCompletion = assignment.completions?.find(
                              c => c.user_id === user.id
                            );
                            const progress = userCompletion?.progress || { completed: 0, total: 0 };
                            const isComplete = progress.completed === progress.total && progress.total > 0;

                            return (
                              <View key={user.id} style={styles.assignedUserItem}>
                                <View style={styles.assignedUserInfo}>
                                  <Text style={styles.assignedUserName}>{user.name}</Text>
                                  <Text style={styles.assignedUserProgress}>
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
            <GlassCard style={styles.emptyCard}>
              <ClipboardList size={40} strokeWidth={1} color={colors.text.subtle} />
              <Text style={styles.emptyText}>No checklists assigned</Text>
              <Text style={styles.emptySubtext}>Checklists will appear here when assigned to this project</Text>
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
          <View style={styles.modalOverlay}>
            <Pressable 
              style={styles.modalBackdrop} 
              onPress={() => {
                setShowAddNfcModal(false);
                NfcHelper.cancelNfc();
              }} 
            />
            <View style={styles.modalContent}>
              <GlassCard variant="modal" style={styles.modalCard}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>Register NFC Tag</Text>
                  <Pressable 
                    onPress={() => {
                      setShowAddNfcModal(false);
                      NfcHelper.cancelNfc();
                    }}
                  >
                    <X size={24} color={colors.text.primary} />
                  </Pressable>
                </View>

                <Text style={styles.modalInstructions}>
                  {nfcSupported 
                    ? 'Scan a blank NFC tag to automatically program it with this project\'s check-in link.'
                    : 'NFC not available. You can register tags manually by entering the tag ID.'}
                </Text>

                <View style={styles.modalForm}>
                  <View style={styles.inputGroup}>
                    <Text style={styles.inputLabel}>LOCATION *</Text>
                    <GlassInput
                      value={nfcLocation}
                      onChangeText={setNfcLocation}
                      placeholder="e.g., Main Entrance, Building A Gate"
                      editable={!scanningNfc && !addingNfc}
                    />
                    <Text style={styles.inputHint}>
                      Where is this NFC tag located?
                    </Text>
                  </View>

                  {nfcSupported && (
                    <>
                      <View style={styles.scanSection}>
                        <View style={styles.scanHeader}>
                          <Radio size={20} strokeWidth={1.5} color="#3b82f6" />
                          <Text style={styles.scanTitle}>Scan NFC Tag</Text>
                        </View>

                        {!nfcEnabled && (
                          <View style={styles.warningBox}>
                            <Text style={styles.warningText}>
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
                            styles.scanButton,
                            scanningNfc && styles.scanButtonActive,
                          ]}
                        />

                        <View style={styles.infoBox}>
                          <Text style={styles.infoText}>
                            💡 This will read the tag ID and write the check-in URL to the tag automatically.
                          </Text>
                        </View>
                      </View>

                      <View style={styles.divider}>
                        <View style={styles.dividerLine} />
                        <Text style={styles.dividerText}>OR</Text>
                        <View style={styles.dividerLine} />
                      </View>
                    </>
                  )}

                  <View style={styles.manualSection}>
                    <Text style={styles.manualTitle}>Manual Entry</Text>
                    
                    <View style={styles.inputGroup}>
                      <Text style={styles.inputLabel}>TAG ID</Text>
                      <GlassInput
                        value={nfcTagId}
                        onChangeText={setNfcTagId}
                        placeholder="e.g., 04:A1:B2:C3:D4:E5:F6"
                        editable={!scanningNfc && !addingNfc}
                      />
                      <Text style={styles.inputHint}>
                        Enter the NFC tag ID manually if scanning is unavailable
                      </Text>
                    </View>

                    <GlassButton
                      title={addingNfc ? 'Adding...' : 'Add Manually'}
                      onPress={handleAddNfcTag}
                      loading={addingNfc}
                      disabled={!nfcTagId.trim() || !nfcLocation.trim() || scanningNfc}
                      style={styles.manualButton}
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
          <View style={styles.modalOverlay}>
            <Pressable style={styles.modalBackdrop} onPress={() => setShowAddDeviceModal(false)} />
            <View style={styles.modalContent}>
              <GlassCard variant="modal" style={styles.modalCard}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>Add Site Device</Text>
                  <Pressable onPress={() => setShowAddDeviceModal(false)}>
                    <X size={24} color={colors.text.primary} />
                  </Pressable>
                </View>

                <Text style={styles.modalDesc}>
                  Create credentials for an on-site device (tablet or phone) to access this project.
                </Text>

                <View style={styles.modalForm}>
                  <View style={styles.inputGroup}>
                    <Text style={styles.inputLabel}>DEVICE NAME</Text>
                    <GlassInput
                      value={newDevice.device_name}
                      onChangeText={(val) => setNewDevice({ ...newDevice, device_name: val })}
                      placeholder="e.g., Site Tablet 1"
                    />
                  </View>

                  <View style={styles.inputGroup}>
                    <Text style={styles.inputLabel}>USERNAME</Text>
                    <GlassInput
                      value={newDevice.username}
                      onChangeText={(val) => setNewDevice({ ...newDevice, username: val })}
                      placeholder="e.g., site-tablet-1"
                      autoCapitalize="none"
                    />
                  </View>

                  <View style={styles.inputGroup}>
                    <Text style={styles.inputLabel}>PASSWORD</Text>
                    <GlassInput
                      value={newDevice.password}
                      onChangeText={(val) => setNewDevice({ ...newDevice, password: val })}
                      placeholder="Create a secure password"
                      secureTextEntry
                    />
                  </View>

                  <View style={styles.infoBox}>
                    <Key size={16} strokeWidth={1.5} color="#f59e0b" />
                    <Text style={styles.infoText}>
                      Save these credentials securely. The password cannot be recovered after creation.
                    </Text>
                  </View>

                  <GlassButton
                    title={addingDevice ? 'Creating...' : 'Create Device'}
                    onPress={handleAddDevice}
                    loading={addingDevice}
                    style={styles.addButton}
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
          <View style={styles.modalOverlay}>
            <Pressable style={styles.modalBackdrop} onPress={() => setShowDropboxModal(false)} />
            <View style={styles.modalContent}>
              <GlassCard variant="modal" style={styles.modalCard}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>Link Dropbox Folder</Text>
                  <Pressable onPress={() => setShowDropboxModal(false)}>
                    <X size={24} color={colors.text.primary} />
                  </Pressable>
                </View>

                <Text style={styles.modalDesc}>
                  Enter the path to your Dropbox folder containing project documents.
                </Text>

                <View style={styles.modalForm}>
                  <View style={styles.inputGroup}>
                    <Text style={styles.inputLabel}>FOLDER PATH</Text>
                    <GlassInput
                      value={dropboxFolder}
                      onChangeText={setDropboxFolder}
                      placeholder="/Projects/Downtown Building"
                    />
                  </View>

                  <View style={styles.infoBox}>
                    <Folder size={16} strokeWidth={1.5} color="#0061FF" />
                    <Text style={styles.infoText}>
                      All users you create will be able to view files from this folder.
                    </Text>
                  </View>

                  <GlassButton
                    title={linkingDropbox ? 'Linking...' : 'Link Folder'}
                    onPress={handleLinkDropbox}
                    loading={linkingDropbox}
                    style={styles.addButton}
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
          <View style={styles.modalOverlay}>
            <View style={styles.credentialsModal}>
              <View style={styles.successIcon}>
                <CheckCircle size={48} strokeWidth={1.5} color="#4ade80" />
              </View>
              <Text style={styles.credentialsTitle}>Device Created!</Text>
              <Text style={styles.credentialsSubtitle}>
                Save these credentials for the on-site device:
              </Text>

              <View style={styles.credentialsBox}>
                <View style={styles.credentialRow}>
                  <Text style={styles.credentialLabel}>Device</Text>
                  <Text style={styles.credentialValueBold}>{showCredentials?.device_name}</Text>
                </View>
                <View style={styles.credentialRow}>
                  <Text style={styles.credentialLabel}>Username</Text>
                  <Text style={styles.credentialValueMono}>{showCredentials?.username}</Text>
                </View>
                <View style={styles.credentialRow}>
                  <Text style={styles.credentialLabel}>Password</Text>
                  <Text style={styles.credentialValueMono}>{showCredentials?.password}</Text>
                </View>
              </View>

              <GlassButton
                title="Done"
                onPress={() => setShowCredentials(null)}
                style={styles.doneBtn}
              />
            </View>
          </View>
        </Modal>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
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
