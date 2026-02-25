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
  LogOut,
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
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';
import AsyncStorage from '@react-native-async-storage/async-storage';

export default function WorkerDetailScreen() {
  const router = useRouter();
  const { id: workerId } = useLocalSearchParams();
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
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
      fetchWorker();
      if (canViewOsha) {
        fetchOshaData();
      }
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

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
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

  const handleAddCertification = () => {
    if (!newCertName.trim()) {
      toast.error('Error', 'Please enter certification name');
      return;
    }
    
    const newCert = {
      name: newCertName,
      expiry: newCertExpiry || null,
      issued: new Date().toISOString(),
    };
    
    setCertifications([...certifications, newCert]);
    setNewCertName('');
    setNewCertExpiry('');
    setShowAddCert(false);
    toast.success('Added', 'Certification added');
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
    setSignature({ data: 'signature_data', updated: new Date().toISOString() });
    setShowSignaturePad(false);
    toast.success('Updated', 'Signature saved');
  };

  if (authLoading || loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={styles.loadingText}>Loading worker...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
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
            {isAdmin && !editMode && (
              <GlassButton
                variant="icon"
                icon={<Edit3 size={18} strokeWidth={1.5} color={colors.text.primary} />}
                onPress={() => setEditMode(true)}
              />
            )}
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
        >
          <GlassCard style={styles.profileCard}>
            <View style={styles.avatarContainer}>
              <View style={styles.avatar}>
                <Text style={styles.avatarText}>{name?.charAt(0) || 'W'}</Text>
              </View>
              {editMode && (
                <View style={styles.editBadge}>
                  <Edit3 size={12} color="#fff" />
                </View>
              )}
            </View>

            {editMode ? (
              <View style={styles.editForm}>
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
                  style={styles.inputSpacing}
                />
                <GlassInput
                  value={company}
                  onChangeText={setCompany}
                  placeholder="Company"
                  leftIcon={<Building2 size={18} color={colors.text.subtle} />}
                  style={styles.inputSpacing}
                />
                <GlassInput
                  value={oshaNumber}
                  onChangeText={setOshaNumber}
                  placeholder="OSHA Number"
                  leftIcon={<FileText size={18} color={colors.text.subtle} />}
                  style={styles.inputSpacing}
                />
                
                <View style={styles.editActions}>
                  <GlassButton
                    title="Cancel"
                    onPress={() => {
                      setEditMode(false);
                      setName(worker?.name || '');
                      setTrade(worker?.trade || '');
                      setCompany(worker?.company || '');
                      setOshaNumber(worker?.osha_number || worker?.oshaNumber || '');
                    }}
                    style={styles.cancelBtn}
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
              <View style={styles.profileInfo}>
                <Text style={styles.workerName}>{name}</Text>
                <Text style={styles.workerTrade}>{trade || 'No trade specified'}</Text>
                
                <View style={styles.infoRow}>
                  <Building2 size={16} color={colors.text.muted} />
                  <Text style={styles.infoText}>{company || 'No company'}</Text>
                </View>
                
                {oshaNumber ? (
                  <View style={styles.infoRow}>
                    <FileText size={16} color={colors.text.muted} />
                    <Text style={styles.infoText}>OSHA: {oshaNumber}</Text>
                  </View>
                ) : null}
              </View>
            )}
          </GlassCard>

          {canViewOsha && (
            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <View style={styles.sectionTitleRow}>
                  <CreditCard size={20} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={styles.sectionTitle}>OSHA / SST Card</Text>
                </View>
              </View>

              {loadingOsha ? (
                <GlassCard style={styles.emptyCard}>
                  <ActivityIndicator size="small" color={colors.text.muted} />
                  <Text style={styles.emptyText}>Loading OSHA data...</Text>
                </GlassCard>
              ) : oshaCardImage ? (
                <GlassCard style={styles.oshaCard}>
                  <Pressable onPress={() => setShowOshaCard(true)}>
                    <Image
                      source={{ uri: oshaCardImage }}
                      style={styles.oshaCardImage}
                      resizeMode="contain"
                    />
                    <Text style={styles.oshaCardTapHint}>Tap to enlarge</Text>
                  </Pressable>

                  {oshaData && (
                    <View style={styles.oshaFields}>
                      {oshaData.name && (
                        <View style={styles.oshaFieldRow}>
                          <Text style={styles.oshaFieldLabel}>Name</Text>
                          <Text style={styles.oshaFieldValue}>{oshaData.name}</Text>
                        </View>
                      )}
                      {oshaData.osha_number && (
                        <View style={styles.oshaFieldRow}>
                          <Text style={styles.oshaFieldLabel}>OSHA #</Text>
                          <Text style={styles.oshaFieldValue}>{oshaData.osha_number}</Text>
                        </View>
                      )}
                      {oshaData.sst_number && (
                        <View style={styles.oshaFieldRow}>
                          <Text style={styles.oshaFieldLabel}>SST #</Text>
                          <Text style={styles.oshaFieldValue}>{oshaData.sst_number}</Text>
                        </View>
                      )}
                      {oshaData.trade && (
                        <View style={styles.oshaFieldRow}>
                          <Text style={styles.oshaFieldLabel}>Trade</Text>
                          <Text style={styles.oshaFieldValue}>{oshaData.trade}</Text>
                        </View>
                      )}
                      {oshaData.expiration && (
                        <View style={styles.oshaFieldRow}>
                          <Text style={styles.oshaFieldLabel}>Expires</Text>
                          <Text style={styles.oshaFieldValue}>{oshaData.expiration}</Text>
                        </View>
                      )}
                      {oshaData.training_provider && (
                        <View style={styles.oshaFieldRow}>
                          <Text style={styles.oshaFieldLabel}>Provider</Text>
                          <Text style={styles.oshaFieldValue}>{oshaData.training_provider}</Text>
                        </View>
                      )}
                    </View>
                  )}
                </GlassCard>
              ) : (
                <GlassCard style={styles.emptyCard}>
                  <CreditCard size={32} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={styles.emptyText}>No OSHA card on file</Text>
                  <Text style={styles.emptySubtext}>Worker will upload during NFC check-in</Text>
                </GlassCard>
              )}
            </View>
          )}

          {canViewOsha && (
            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <View style={styles.sectionTitleRow}>
                  <ShieldCheck size={20} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={styles.sectionTitle}>Safety Orientations</Text>
                </View>
              </View>

              {safetyOrientations.length > 0 ? (
                <View style={styles.orientationList}>
                  {safetyOrientations.map((orientation, index) => (
                    <GlassCard key={index} style={styles.orientationItem}>
                      <Pressable
                        style={styles.orientationHeader}
                        onPress={() => setExpandedOrientation(expandedOrientation === index ? null : index)}
                      >
                        <View style={styles.orientationInfo}>
                          <View style={styles.orientationBadge}>
                            <ShieldCheck size={14} color="#22c55e" />
                          </View>
                          <View style={{ flex: 1 }}>
                            <Text style={styles.orientationProject}>
                              {orientation.project_name || 'Unknown Project'}
                            </Text>
                            <Text style={styles.orientationDate}>
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
                        <View style={styles.checklistExpanded}>
                          {Object.entries(orientation.checklist).map(([item, val], i) => (
                            <View key={i} style={styles.checklistItem}>
                              <View style={[
                                styles.checkIcon,
                                val?.checked && styles.checkIconChecked,
                              ]}>
                                {val?.checked && <Check size={12} color="#fff" />}
                              </View>
                              <Text style={styles.checklistItemText}>{item}</Text>
                            </View>
                          ))}
                        </View>
                      )}
                    </GlassCard>
                  ))}
                </View>
              ) : (
                <GlassCard style={styles.emptyCard}>
                  <ShieldCheck size={32} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={styles.emptyText}>No safety orientations</Text>
                  <Text style={styles.emptySubtext}>Completed during first NFC check-in at each site</Text>
                </GlassCard>
              )}
            </View>
          )}

          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <View style={styles.sectionTitleRow}>
                <Award size={20} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={styles.sectionTitle}>Certifications</Text>
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
              <GlassCard style={styles.addForm}>
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
                  style={styles.inputSpacing}
                />
                <View style={styles.addFormButtons}>
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
              <View style={styles.certList}>
                {certifications.map((cert, index) => (
                  <View key={index} style={styles.certItem}>
                    <IconPod size={40}>
                      <Award size={18} strokeWidth={1.5} color="#f59e0b" />
                    </IconPod>
                    <View style={styles.certInfo}>
                      <Text style={styles.certName}>{cert.name}</Text>
                      {cert.expiry && (
                        <Text style={styles.certExpiry}>Expires: {cert.expiry}</Text>
                      )}
                    </View>
                    {isAdmin && (
                      <Pressable onPress={() => handleDeleteCertification(index)} style={styles.deleteBtn}>
                        <Trash2 size={16} strokeWidth={1.5} color={colors.status.error} />
                      </Pressable>
                    )}
                  </View>
                ))}
              </View>
            ) : (
              <GlassCard style={styles.emptyCard}>
                <Award size={32} strokeWidth={1} color={colors.text.subtle} />
                <Text style={styles.emptyText}>No certifications</Text>
              </GlassCard>
            )}
          </View>

          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <View style={styles.sectionTitleRow}>
                <Pen size={20} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={styles.sectionTitle}>Digital Signature</Text>
              </View>
            </View>

            <GlassCard style={styles.signatureCard}>
              {signature ? (
                <>
                  <View style={styles.signaturePreview}>
                    <Text style={styles.signatureText}>✍️ Signature on file</Text>
                    <Text style={styles.signatureDate}>
                      Updated: {new Date(signature.updated).toLocaleDateString()}
                    </Text>
                  </View>
                  {isAdmin && (
                    <GlassButton
                      title="Update Signature"
                      icon={<Edit3 size={16} color={colors.text.primary} />}
                      onPress={() => setShowSignaturePad(true)}
                    />
                  )}
                </>
              ) : (
                <>
                  <Text style={styles.noSignatureText}>No signature on file</Text>
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
              <GlassCard style={styles.signaturePad}>
                <Text style={styles.signaturePadTitle}>Draw Signature</Text>
                <View style={styles.signatureCanvas}>
                  <Text style={styles.signatureCanvasPlaceholder}>
                    Signature pad would appear here
                  </Text>
                </View>
                <div style={styles.signaturePadActions}>
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
            style={styles.modalOverlay}
            onPress={() => setShowOshaCard(false)}
          >
            <View style={styles.modalContent}>
              <Pressable style={styles.modalClose} onPress={() => setShowOshaCard(false)}>
                <X size={24} color="#fff" />
              </Pressable>
              {oshaCardImage && (
                <Image
                  source={{ uri: oshaCardImage }}
                  style={styles.modalImage}
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
