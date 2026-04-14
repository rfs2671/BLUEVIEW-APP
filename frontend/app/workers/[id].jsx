import { workersAPI } from '../../src/utils/api';
import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  TextInput,
  Alert,
  Platform,
  Image,
  Modal,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  User,
  Building2,
  Award,
  Edit3,
  Save,
  Plus,
  Trash2,
  FileText,
  Calendar,
  Pen,
  ShieldCheck,
  CreditCard,
  ChevronDown,
  ChevronUp,
  Check,
  X,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { useWorkers } from '../../src/hooks/useWorkers';
import OfflineIndicator from '../../src/components/OfflineIndicator';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';
import AsyncStorage from '@react-native-async-storage/async-storage';
import HeaderBrand from '../../src/components/HeaderBrand';

export default function WorkerDetailScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: workerId } = useLocalSearchParams();
  const { isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [worker, setWorker] = useState(null);
  const { getWorkerById, updateWorker } = useWorkers();
  const [editMode, setEditMode] = useState(false);
  
  // Edit form fields
  const [name, setName] = useState('');
  const [trade, setTrade] = useState('');
  const [company, setCompany] = useState('');
  const [oshaNumber, setOshaNumber] = useState('');
  
  // Certifications
  const [certifications, setCertifications] = useState([]);
  const [showAddCert, setShowAddCert] = useState(false);
  const [newCertName, setNewCertName] = useState('');
  const [newCertExpiry, setNewCertExpiry] = useState('');
  
  // Signature
  const [signature, setSignature] = useState(null);
  const [showSignaturePad, setShowSignaturePad] = useState(false);

  // OSHA & Safety Orientation (fetched from API)
  const [oshaCardImage, setOshaCardImage] = useState(null);
  const [oshaData, setOshaData] = useState(null);
  const [safetyOrientations, setSafetyOrientations] = useState([]);
  const [loadingOsha, setLoadingOsha] = useState(false);
  const [showOshaCard, setShowOshaCard] = useState(false);
  const [expandedOrientation, setExpandedOrientation] = useState(null);

  const isAdmin = user?.role === 'admin' || user?.role === 'owner';
  const isSiteDevice = user?.role === 'site_device';
  const canViewOsha = isAdmin || isSiteDevice;

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated && workerId) {
      fetchWorker().then(() => {
      if (canViewOsha) {
        fetchOshaData();
        }
      });
    }
  }, [isAuthenticated, workerId]);

  const fetchWorker = async () => {
  try {
    let workerData = await getWorkerById(workerId);
    if (!workerData || !workerData.signature) {
      workerData = await workersAPI.getById(workerId);
    }
      setWorker(workerData);
      setName(workerData.name || '');
      setTrade(workerData.trade || '');
      setCompany(workerData.company || '');
      setOshaNumber(workerData.osha_number || workerData.oshaNumber || '');
      setCertifications(workerData.certifications || []);
      setSignature(workerData.signature || null);
    } catch (error) {
      console.error('Failed to fetch worker:', error);
      toast.error('Error', 'Could not load worker details');
    } finally {
      setLoading(false);
    }
  };

  const fetchOshaData = async () => {
    setLoadingOsha(true);
    try {
      // Use centralized API utility to handle tokens and headers automatically
      const data = await workersAPI.getOshaCard(workerId);
      
      setOshaCardImage(data.osha_card_image || null);
      setOshaData(data.osha_data || null);
      setSafetyOrientations(data.safety_orientations || []);
      setSignature(data.signature || null);
      
      if (data.osha_number && !oshaNumber) {
        setOshaNumber(data.osha_number);
      }
    } catch (error) {
      console.error('Failed to fetch OSHA data:', error);
    } finally {
      setLoadingOsha(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateWorker(workerId, {
        name,
        trade,
        company,
        osha_number: oshaNumber,
        certifications,
      });
      setWorker({ ...worker, name, trade, company, oshaNumber });
      setEditMode(false);
      toast.success('Saved', 'Worker information updated');
    } catch (error) {
      console.error('Failed to save:', error);
      toast.error('Error', 'Could not save changes');
    } finally {
      setSaving(false);
    }
  };

  const CERT_TYPES = [
    { value: 'OSHA_10', label: 'OSHA-10' },
    { value: 'OSHA_30', label: 'OSHA-30' },
    { value: 'SST_FULL', label: 'SST Full (62-hr)' },
    { value: 'SST_LIMITED', label: 'SST Limited (10-hr)' },
    { value: 'SST_SUPERVISOR', label: 'SST Supervisor' },
    { value: 'FDNY_COF', label: 'FDNY Certificate of Fitness' },
    { value: 'SCAFFOLD', label: 'Scaffold Safety' },
    { value: 'RIGGING', label: 'Rigging' },
    { value: 'WELDING', label: 'Welding' },
    { value: 'ASBESTOS', label: 'Asbestos Handler' },
    { value: 'LEAD', label: 'Lead Abatement' },
    { value: 'CONFINED_SPACE', label: 'Confined Space' },
    { value: 'OTHER', label: 'Other' },
  ];

  const [newCertType, setNewCertType] = useState('OSHA_10');

  const handleAddCertification = async () => {
    const certData = {
      type: newCertType,
      card_number: newCertName.trim() || null,
      expiration_date: newCertExpiry || null,
      issue_date: new Date().toISOString(),
      verified: false,
    };

    try {
      const workerId = worker._id || worker.id;
      await apiClient.post(`/api/workers/${workerId}/certifications`, certData);
      const updated = await getWorkerById(workerId);
      setCertifications(updated?.certifications || []);
      setNewCertName('');
      setNewCertExpiry('');
      setNewCertType('OSHA_10');
      setShowAddCert(false);
      toast.success('Added', 'Certification added and validated');
    } catch (error) {
      console.error('Failed to add cert:', error);
      toast.error('Error', 'Could not save certification');
    }
  };

  const handleDeleteCertification = (index) => {
    const confirmDelete = () => {
      const updated = certifications.filter((_, i) => i !== index);
      setCertifications(updated);
      toast.success('Deleted', 'Certification removed');
    };

    if (Platform.OS === 'web') {
      if (window.confirm('Delete this certification?')) {
        confirmDelete();
      }
    } else {
      Alert.alert('Delete Certification', 'Delete this certification?', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: confirmDelete },
      ]);
    }
  };

  const handleUpdateSignature = () => {
    setSignature({ data: 'signature_data', signed_at: new Date().toISOString() });
    setShowSignaturePad(false);
    toast.success('Updated', 'Signature saved');
  };

  if (authLoading || loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container}>
          <View style={s.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={s.loadingText}>Loading worker...</Text>
          </View>
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
          <View style={s.headerRight}>
            <OfflineIndicator />
            {isAdmin && !editMode && (
              <GlassButton
                variant="icon"
                icon={<Edit3 size={18} strokeWidth={1.5} color={colors.text.primary} />}
                onPress={() => setEditMode(true)}
              />
            )}
          </View>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          <GlassCard style={s.profileCard}>
            <View style={s.avatarContainer}>
              <View style={s.avatar}>
                <Text style={s.avatarText}>{name?.charAt(0) || 'W'}</Text>
              </View>
              {editMode && (
                <View style={s.editBadge}>
                  <Edit3 size={12} color="#fff" />
                </View>
              )}
            </View>

            {editMode ? (
              <View style={s.editForm}>
                <GlassInput
                  value={name}
                  onChangeText={setName}
                  placeholder="Full Name"
                  leftIcon={<User size={18} color={colors.text.subtle} />}
                />
                <GlassInput
                  value={trade}
                  onChangeText={setTrade}
                  placeholder="Trade"
                  style={s.inputSpacing}
                />
                <GlassInput
                  value={company}
                  onChangeText={setCompany}
                  placeholder="Company"
                  leftIcon={<Building2 size={18} color={colors.text.subtle} />}
                  style={s.inputSpacing}
                />
                <GlassInput
                  value={oshaNumber}
                  onChangeText={setOshaNumber}
                  placeholder="OSHA Number"
                  leftIcon={<FileText size={18} color={colors.text.subtle} />}
                  style={s.inputSpacing}
                />
                
                <View style={s.editActions}>
                  <GlassButton
                    title="Cancel"
                    onPress={() => {
                      setEditMode(false);
                      setName(worker?.name || '');
                      setTrade(worker?.trade || '');
                      setCompany(worker?.company || '');
                      setOshaNumber(worker?.osha_number || worker?.oshaNumber || '');
                    }}
                    style={s.cancelBtn}
                  />
                  <GlassButton
                    title="Save Changes"
                    icon={<Save size={16} color={colors.text.primary} />}
                    onPress={handleSave}
                    loading={saving}
                  />
                </View>
              </View>
            ) : (
              <View style={s.profileInfo}>
                <Text style={s.workerName}>{name}</Text>
                <Text style={s.workerTrade}>{trade || 'No trade specified'}</Text>
                
                <View style={s.infoRow}>
                  <Building2 size={16} color={colors.text.muted} />
                  <Text style={s.infoText}>{company || 'No company'}</Text>
                </View>
                
                {oshaNumber ? (
                  <View style={s.infoRow}>
                    <FileText size={16} color={colors.text.muted} />
                    <Text style={s.infoText}>OSHA: {oshaNumber}</Text>
                  </View>
                ) : null}
              </View>
            )}
          </GlassCard>

          {canViewOsha && (
            <View style={s.section}>
              <View style={s.sectionHeader}>
                <View style={s.sectionTitleRow}>
                  <CreditCard size={20} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.sectionTitle}>OSHA / SST Card</Text>
                </View>
              </View>

              {loadingOsha ? (
                <GlassCard style={s.emptyCard}>
                  <ActivityIndicator size="small" color={colors.text.muted} />
                  <Text style={s.emptyText}>Loading OSHA data...</Text>
                </GlassCard>
              ) : oshaCardImage ? (
                <GlassCard style={s.oshaCard}>
                  <Pressable onPress={() => setShowOshaCard(true)}>
                    <Image
                      source={{ uri: oshaCardImage }}
                      style={s.oshaCardImage}
                      resizeMode="contain"
                    />
                    <Text style={s.oshaCardTapHint}>Tap to enlarge</Text>
                  </Pressable>

                  {oshaData && (
                    <View style={s.oshaFields}>
                      {oshaData.name && (
                        <View style={s.oshaFieldRow}>
                          <Text style={s.oshaFieldLabel}>Name</Text>
                          <Text style={s.oshaFieldValue}>{oshaData.name}</Text>
                        </View>
                      )}
                      {oshaData.osha_number && (
                        <View style={s.oshaFieldRow}>
                          <Text style={s.oshaFieldLabel}>OSHA #</Text>
                          <Text style={s.oshaFieldValue}>{oshaData.osha_number}</Text>
                        </View>
                      )}
                      {oshaData.sst_number && (
                        <View style={s.oshaFieldRow}>
                          <Text style={s.oshaFieldLabel}>SST #</Text>
                          <Text style={s.oshaFieldValue}>{oshaData.sst_number}</Text>
                        </View>
                      )}
                      {oshaData.trade && (
                        <View style={s.oshaFieldRow}>
                          <Text style={s.oshaFieldLabel}>Trade</Text>
                          <Text style={s.oshaFieldValue}>{oshaData.trade}</Text>
                        </View>
                      )}
                      {oshaData.expiration && (
                        <View style={s.oshaFieldRow}>
                          <Text style={s.oshaFieldLabel}>Expires</Text>
                          <Text style={s.oshaFieldValue}>{oshaData.expiration}</Text>
                        </View>
                      )}
                      {oshaData.training_provider && (
                        <View style={s.oshaFieldRow}>
                          <Text style={s.oshaFieldLabel}>Provider</Text>
                          <Text style={s.oshaFieldValue}>{oshaData.training_provider}</Text>
                        </View>
                      )}
                    </View>
                  )}
                </GlassCard>
              ) : (
                <GlassCard style={s.emptyCard}>
                  <CreditCard size={32} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyText}>No OSHA card on file</Text>
                  <Text style={s.emptySubtext}>Worker will upload during NFC check-in</Text>
                </GlassCard>
              )}
            </View>
          )}

          {canViewOsha && (
            <View style={s.section}>
              <View style={s.sectionHeader}>
                <View style={s.sectionTitleRow}>
                  <ShieldCheck size={20} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.sectionTitle}>Safety Orientations</Text>
                </View>
              </View>

              {safetyOrientations.length > 0 ? (
                <View style={s.orientationList}>
                  {safetyOrientations.map((orientation, index) => (
                    <GlassCard key={index} style={s.orientationItem}>
                      <Pressable
                        style={s.orientationHeader}
                        onPress={() => setExpandedOrientation(expandedOrientation === index ? null : index)}
                      >
                        <View style={s.orientationInfo}>
                          <View style={s.orientationBadge}>
                            <ShieldCheck size={14} color="#22c55e" />
                          </View>
                          <View style={{ flex: 1 }}>
                            <Text style={s.orientationProject}>
                              {orientation.project_name || 'Unknown Project'}
                            </Text>
                            <Text style={s.orientationDate}>
                              {orientation.completed_at
                                ? new Date(orientation.completed_at).toLocaleDateString()
                                : 'Date unknown'}
                            </Text>
                          </View>
                        </View>
                        {expandedOrientation === index ? (
                          <ChevronUp size={18} color={colors.text.muted} />
                        ) : (
                          <ChevronDown size={18} color={colors.text.muted} />
                        )}
                      </Pressable>

                      {expandedOrientation === index && orientation.checklist && (
                        <View style={s.checklistExpanded}>
                          {Object.entries(orientation.checklist).map(([item, val], i) => (
                            <View key={i} style={s.checklistItem}>
                              <View style={[
                                s.checkIcon,
                                val?.checked && s.checkIconChecked,
                              ]}>
                                {val?.checked && <Check size={12} color="#fff" />}
                              </View>
                              <Text style={s.checklistItemText}>{item}</Text>
                            </View>
                          ))}
                        </View>
                      )}
                    </GlassCard>
                  ))}
                </View>
              ) : (
                <GlassCard style={s.emptyCard}>
                  <ShieldCheck size={32} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyText}>No safety orientations</Text>
                  <Text style={s.emptySubtext}>Completed during first NFC check-in at each site</Text>
                </GlassCard>
              )}
            </View>
          )}

          <View style={s.section}>
            <View style={s.sectionHeader}>
              <View style={s.sectionTitleRow}>
                <Award size={20} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={s.sectionTitle}>Certifications</Text>
              </View>
              {isAdmin && (
                <GlassButton
                  variant="icon"
                  icon={<Plus size={18} strokeWidth={1.5} color={colors.text.primary} />}
                  onPress={() => setShowAddCert(true)}
                />
              )}
            </View>

            {showAddCert && (
              <GlassCard style={s.addForm}>
                <GlassInput
                  value={newCertName}
                  onChangeText={setNewCertName}
                  placeholder="Certification name"
                />
                <GlassInput
                  value={newCertExpiry}
                  onChangeText={setNewCertExpiry}
                  placeholder="Expiry date (optional)"
                  leftIcon={<Calendar size={18} color={colors.text.subtle} />}
                  style={s.inputSpacing}
                />
                <View style={s.addFormButtons}>
                  <GlassButton
                    title="Cancel"
                    onPress={() => setShowAddCert(false)}
                  />
                  <GlassButton
                    title="Add"
                    onPress={handleAddCertification}
                  />
                </View>
              </GlassCard>
            )}

            {certifications.length > 0 ? (
              <View style={s.certList}>
                {certifications.map((cert, index) => (
                  <View key={index} style={s.certItem}>
                    <IconPod size={40}>
                      <Award size={18} strokeWidth={1.5} color="#f59e0b" />
                    </IconPod>
                    <View style={s.certInfo}>
                      <Text style={s.certName}>{cert.name}</Text>
                      {cert.expiry && (
                        <Text style={s.certExpiry}>Expires: {cert.expiry}</Text>
                      )}
                    </View>
                    {isAdmin && (
                      <Pressable onPress={() => handleDeleteCertification(index)} style={s.deleteBtn}>
                        <Trash2 size={16} strokeWidth={1.5} color={colors.status.error} />
                      </Pressable>
                    )}
                  </View>
                ))}
              </View>
            ) : (
              <GlassCard style={s.emptyCard}>
                <Award size={32} strokeWidth={1} color={colors.text.subtle} />
                <Text style={s.emptyText}>No certifications</Text>
              </GlassCard>
            )}
          </View>

          <View style={s.section}>
            <View style={s.sectionHeader}>
              <View style={s.sectionTitleRow}>
                <Pen size={20} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={s.sectionTitle}>Digital Signature</Text>
              </View>
            </View>

            <GlassCard style={s.signatureCard}>\
              {signature ? (
                <>
<View style={s.signaturePreview}>
                    {(() => {
                      const sigUri = typeof signature === 'string'
                        ? signature
                        : signature?.data
                          ? `data:image/png;base64,${signature.data}`
                          : null;
                      return sigUri ? (
                        <Image source={{ uri: sigUri }} style={{ width: '100%', height: 150 }} resizeMode="contain" />
                      ) : null;
                    })()}
                    <Text style={s.signatureText}>✍️ Signature on file</Text>
                    <Text style={s.signatureDate}>
                      Updated: {signature?.signed_at ? new Date(signature.signed_at).toLocaleDateString() : 'On file'}
                    </Text>
                  </View>
                </>
              ) : (
                <>
                  <Text style={s.noSignatureText}>No signature on file</Text>
                  {isAdmin && (
                    <GlassButton
                      title="Add Signature"
                      icon={<Plus size={16} color={colors.text.primary} />}
                      onPress={() => setShowSignaturePad(true)}
                    />
                  )}
                </>
              )}
            </GlassCard>

            {showSignaturePad && (
              <GlassCard style={s.signaturePad}>
                <Text style={s.signaturePadTitle}>Draw Signature</Text>
                <View style={s.signatureCanvas}>
                  <Text style={s.signatureCanvasPlaceholder}>
                    Signature pad would appear here
                  </Text>
                </View>
                <div style={s.signaturePadActions}>
                  <GlassButton
                    title="Cancel"
                    onPress={() => setShowSignaturePad(false)}
                  />
                  <GlassButton
                    title="Save Signature"
                    onPress={handleUpdateSignature}
                  />
                </div>
              </GlassCard>
            )}
          </View>
        </ScrollView>

        <Modal
          visible={showOshaCard}
          transparent={true}
          animationType="fade"
          onRequestClose={() => setShowOshaCard(false)}
        >
          <Pressable
            style={s.modalOverlay}
            onPress={() => setShowOshaCard(false)}
          >
            <View style={s.modalContent}>
              <Pressable style={s.modalClose} onPress={() => setShowOshaCard(false)}>
                <X size={24} color="#fff" />
              </Pressable>
              {oshaCardImage && (
                <Image
                  source={{ uri: oshaCardImage }}
                  style={s.modalImage}
                  resizeMode="contain"
                />
              )}
            </View>
          </Pressable>
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
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
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
  profileCard: {
    alignItems: 'center',
    marginBottom: spacing.xl,
  },
  avatarContainer: {
    position: 'relative',
    marginBottom: spacing.lg,
  },
  avatar: {
    width: 100,
    height: 100,
    borderRadius: 50,
    backgroundColor: '#3b82f6',
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    fontSize: 42,
    fontWeight: '300',
    color: '#fff',
  },
  editBadge: {
    position: 'absolute',
    bottom: 0,
    right: 0,
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#f59e0b',
    alignItems: 'center',
    justifyContent: 'center',
  },
  profileInfo: {
    alignItems: 'center',
  },
  workerName: {
    fontSize: 28,
    fontWeight: '300',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  workerTrade: {
    fontSize: 16,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
  infoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  infoText: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  editForm: {
    width: '100%',
  },
  inputSpacing: {
    marginTop: spacing.sm,
  },
  editActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: spacing.sm,
    marginTop: spacing.lg,
  },
  cancelBtn: {
    opacity: 0.7,
  },
  section: {
    marginBottom: spacing.xl,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  sectionTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
  },
  oshaCard: {
    gap: spacing.md,
  },
  oshaCardImage: {
    width: '100%',
    height: 200,
    borderRadius: borderRadius.md,
    backgroundColor: 'rgba(255,255,255,0.03)',
  },
  oshaCardTapHint: {
    fontSize: 11,
    color: colors.text.subtle,
    textAlign: 'center',
    marginTop: 4,
  },
  oshaFields: {
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.06)',
    paddingTop: spacing.md,
    gap: spacing.sm,
  },
  oshaFieldRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  oshaFieldLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  oshaFieldValue: {
    fontSize: 14,
    color: colors.text.primary,
    fontWeight: '500',
  },
  orientationList: {
    gap: spacing.sm,
  },
  orientationItem: {
    padding: 0,
    overflow: 'hidden',
  },
  orientationHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.md,
  },
  orientationInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    flex: 1,
  },
  orientationBadge: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: 'rgba(34,197,94,0.15)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  orientationProject: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
  },
  orientationDate: {
    fontSize: 12,
    color: colors.text.muted,
    marginTop: 2,
  },
  checklistExpanded: {
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.06)',
    padding: spacing.md,
    gap: 8,
  },
  checklistItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  checkIcon: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 1.5,
    borderColor: 'rgba(255,255,255,0.15)',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 1,
  },
  checkIconChecked: {
    backgroundColor: '#22c55e',
    borderColor: '#22c55e',
  },
  checklistItemText: {
    fontSize: 13,
    color: colors.text.secondary,
    flex: 1,
    lineHeight: 18,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xl,
    gap: spacing.sm,
  },
  emptyText: {
    fontSize: 14,
    color: colors.text.muted,
  },
  emptySubtext: {
    fontSize: 12,
    color: colors.text.subtle,
  },
  addForm: {
    marginBottom: spacing.md,
  },
  addFormButtons: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  certList: {
    gap: spacing.sm,
  },
  certItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
  },
  certInfo: {
    flex: 1,
  },
  certName: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
  },
  certExpiry: {
    fontSize: 12,
    color: colors.text.muted,
  },
  deleteBtn: {
    padding: spacing.sm,
  },
  signatureCard: {
    alignItems: 'center',
    gap: spacing.md,
  },
  signaturePreview: {
    alignItems: 'center',
  },
  signatureText: {
    fontSize: 18,
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  signatureDate: {
    fontSize: 12,
    color: colors.text.muted,
  },
  noSignatureText: {
    fontSize: 14,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
  signaturePad: {
    marginTop: spacing.md,
  },
  signaturePadTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.md,
  },
  signatureCanvas: {
    height: 150,
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.glass.border,
    borderStyle: 'dashed',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.md,
  },
  signatureCanvasPlaceholder: {
    fontSize: 14,
    color: colors.text.subtle,
  },
  signaturePadActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: spacing.sm,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.9)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    width: '95%',
    height: '80%',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalClose: {
    position: 'absolute',
    top: 0,
    right: 0,
    zIndex: 10,
    padding: 12,
  },
  modalImage: {
    width: '100%',
    height: '100%',
  },
});
}
