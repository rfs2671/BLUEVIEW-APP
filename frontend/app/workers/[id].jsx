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
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { workersAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

export default function WorkerDetailScreen() {
  const router = useRouter();
  const { id: workerId } = useLocalSearchParams();
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [worker, setWorker] = useState(null);
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

  const isAdmin = user?.role === 'admin';

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated && workerId) {
      fetchWorker();
    }
  }, [isAuthenticated, workerId]);

  const fetchWorker = async () => {
    try {
      const workerData = await workersAPI.getById(workerId);
      setWorker(workerData);
      setName(workerData.name || '');
      setTrade(workerData.trade || '');
      setCompany(workerData.company || '');
      setOshaNumber(workerData.osha_number || '');
      setCertifications(workerData.certifications || []);
      setSignature(workerData.signature || null);
    } catch (error) {
      console.error('Failed to fetch worker:', error);
      toast.error('Error', 'Could not load worker details');
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      // In real app, would call API to update worker
      setWorker({ ...worker, name, trade, company, osha_number: oshaNumber });
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
    // In real app, would open signature canvas
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
          {/* Worker Profile Card */}
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
                      setOshaNumber(worker?.osha_number || '');
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
                
                {oshaNumber && (
                  <View style={styles.infoRow}>
                    <FileText size={16} color={colors.text.muted} />
                    <Text style={styles.infoText}>OSHA: {oshaNumber}</Text>
                  </View>
                )}
              </View>
            )}
          </GlassCard>

          {/* Certifications Section */}
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

          {/* Digital Signature Section */}
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
                <View style={styles.signaturePadActions}>
                  <GlassButton
                    title="Cancel"
                    onPress={() => setShowSignaturePad(false)}
                  />
                  <GlassButton
                    title="Save Signature"
                    onPress={handleUpdateSignature}
                  />
                </View>
              </GlassCard>
            )}
          </View>
        </ScrollView>
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
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xl,
    gap: spacing.sm,
  },
  emptyText: {
    fontSize: 14,
    color: colors.text.muted,
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
});
