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
  Plus,
  Trash2,
  Nfc,
  MapPin,
  Tag,
  Settings,
  ChevronRight,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import GlassInput from '../../../src/components/GlassInput';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import { projectsAPI, nfcAPI } from '../../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../../src/styles/theme';

export default function ReportSettingsScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [project, setProject] = useState(null);
  
  // Trade mappings
  const [tradeMappings, setTradeMappings] = useState([]);
  const [showAddMapping, setShowAddMapping] = useState(false);
  const [newFieldTrade, setNewFieldTrade] = useState('');
  const [newFormalTrade, setNewFormalTrade] = useState('');

  // NFC Tags
  const [nfcTags, setNfcTags] = useState([]);
  const [showAddTag, setShowAddTag] = useState(false);
  const [newTagId, setNewTagId] = useState('');
  const [newTagLocation, setNewTagLocation] = useState('');

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

  const fetchData = async () => {
    try {
      const projectData = await projectsAPI.getById(projectId);
      setProject(projectData);
      
      // Load trade mappings and NFC tags from project data
      setTradeMappings(projectData.trade_mappings || [
        { field: 'Elec', formal: 'Electrician' },
        { field: 'Plumb', formal: 'Plumber' },
      ]);
      setNfcTags(projectData.nfc_tags || []);
    } catch (error) {
      console.error('Failed to fetch project:', error);
      toast.error('Error', 'Could not load project settings');
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const handleAddMapping = () => {
    if (!newFieldTrade.trim() || !newFormalTrade.trim()) {
      toast.error('Error', 'Please fill in both fields');
      return;
    }
    
    setTradeMappings([...tradeMappings, { field: newFieldTrade, formal: newFormalTrade }]);
    setNewFieldTrade('');
    setNewFormalTrade('');
    setShowAddMapping(false);
    toast.success('Added', 'Trade mapping added');
  };

  const handleDeleteMapping = (index) => {
    const confirmDelete = () => {
      const updated = tradeMappings.filter((_, i) => i !== index);
      setTradeMappings(updated);
      toast.success('Deleted', 'Trade mapping removed');
    };

    if (Platform.OS === 'web') {
      if (window.confirm('Delete this trade mapping?')) {
        confirmDelete();
      }
    } else {
      Alert.alert('Delete Mapping', 'Delete this trade mapping?', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: confirmDelete },
      ]);
    }
  };

  const handleAddTag = async () => {
    if (!newTagId.trim() || !newTagLocation.trim()) {
      toast.error('Error', 'Please fill in both fields');
      return;
    }
    
    try {
      await nfcAPI.linkToProject(projectId, newTagId, newTagLocation);
      setNfcTags([...nfcTags, { tag_id: newTagId, location: newTagLocation }]);
      setNewTagId('');
      setNewTagLocation('');
      setShowAddTag(false);
      toast.success('Added', 'NFC tag registered to project');
    } catch (error) {
      console.error('Failed to add NFC tag:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not register NFC tag');
    }
  };

  const handleDeleteTag = (tagId, index) => {
    const confirmDelete = async () => {
      try {
        await nfcAPI.unlinkFromProject(projectId, tagId);
        const updated = nfcTags.filter((_, i) => i !== index);
        setNfcTags(updated);
        toast.success('Deleted', 'NFC tag removed from project');
      } catch (error) {
        console.error('Failed to delete NFC tag:', error);
        toast.error('Error', error.response?.data?.detail || 'Could not remove NFC tag');
      }
    };

    if (Platform.OS === 'web') {
      if (window.confirm('Remove this NFC tag from project?')) {
        confirmDelete();
      }
    } else {
      Alert.alert('Remove Tag', 'Remove this NFC tag from project?', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Remove', style: 'destructive', onPress: confirmDelete },
      ]);
    }
  };

  const handleScanNfc = () => {
    toast.info('NFC', 'NFC scanning is only available on native devices');
  };

  if (authLoading || loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={styles.loadingText}>Loading settings...</Text>
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
            <Text style={styles.titleLabel}>{project?.name || 'PROJECT'}</Text>
            <Text style={styles.titleText}>Report Settings</Text>
          </View>

          {/* Trade Mappings Section */}
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <View style={styles.sectionTitleRow}>
                <Tag size={20} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={styles.sectionTitle}>Trade Mappings</Text>
              </View>
              {isAdmin && (
                <GlassButton
                  variant="icon"
                  icon={<Plus size={18} strokeWidth={1.5} color={colors.text.primary} />}
                  onPress={() => setShowAddMapping(true)}
                />
              )}
            </View>
            <Text style={styles.sectionDesc}>
              Map field trade names to formal names for reports
            </Text>

            {showAddMapping && (
              <GlassCard style={styles.addForm}>
                <GlassInput
                  value={newFieldTrade}
                  onChangeText={setNewFieldTrade}
                  placeholder="Field trade (e.g., Elec)"
                />
                <GlassInput
                  value={newFormalTrade}
                  onChangeText={setNewFormalTrade}
                  placeholder="Formal trade (e.g., Electrician)"
                  style={styles.inputSpacing}
                />
                <View style={styles.addFormButtons}>
                  <GlassButton
                    title="Cancel"
                    onPress={() => setShowAddMapping(false)}
                    style={styles.cancelBtn}
                  />
                  <GlassButton
                    title="Add Mapping"
                    onPress={handleAddMapping}
                  />
                </View>
              </GlassCard>
            )}

            {tradeMappings.length > 0 ? (
              <View style={styles.listContainer}>
                {tradeMappings.map((mapping, index) => (
                  <View key={index} style={styles.listItem}>
                    <View style={styles.mappingContent}>
                      <Text style={styles.fieldText}>{mapping.field}</Text>
                      <ChevronRight size={16} color={colors.text.subtle} />
                      <Text style={styles.formalText}>{mapping.formal}</Text>
                    </View>
                    {isAdmin && (
                      <Pressable onPress={() => handleDeleteMapping(index)} style={styles.deleteBtn}>
                        <Trash2 size={16} strokeWidth={1.5} color={colors.status.error} />
                      </Pressable>
                    )}
                  </View>
                ))}
              </View>
            ) : (
              <Text style={styles.emptyText}>No trade mappings configured</Text>
            )}
          </View>

          {/* NFC Tags Section */}
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <View style={styles.sectionTitleRow}>
                <Nfc size={20} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={styles.sectionTitle}>NFC Check-In Tags</Text>
              </View>
              {isAdmin && (
                <GlassButton
                  variant="icon"
                  icon={<Plus size={18} strokeWidth={1.5} color={colors.text.primary} />}
                  onPress={() => setShowAddTag(true)}
                />
              )}
            </View>
            <Text style={styles.sectionDesc}>
              Register NFC tags for specific locations on site
            </Text>

            {showAddTag && (
              <GlassCard style={styles.addForm}>
                <View style={styles.nfcScanRow}>
                  <GlassInput
                    value={newTagId}
                    onChangeText={setNewTagId}
                    placeholder="Tag ID"
                    style={styles.tagIdInput}
                  />
                  <GlassButton
                    title="Scan"
                    icon={<Nfc size={16} strokeWidth={1.5} color={colors.text.primary} />}
                    onPress={handleScanNfc}
                  />
                </View>
                <GlassInput
                  value={newTagLocation}
                  onChangeText={setNewTagLocation}
                  placeholder="Location description (e.g., Main Entrance)"
                  style={styles.inputSpacing}
                />
                <View style={styles.addFormButtons}>
                  <GlassButton
                    title="Cancel"
                    onPress={() => setShowAddTag(false)}
                    style={styles.cancelBtn}
                  />
                  <GlassButton
                    title="Add Tag"
                    onPress={handleAddTag}
                  />
                </View>
              </GlassCard>
            )}

            {nfcTags.length > 0 ? (
              <View style={styles.listContainer}>
                {nfcTags.map((tag, index) => (
                  <View key={tag.tag_id || index} style={styles.listItem}>
                    <View style={styles.tagContent}>
                      <IconPod size={36}>
                        <Nfc size={16} strokeWidth={1.5} color={colors.text.secondary} />
                      </IconPod>
                      <View style={styles.tagInfo}>
                        <Text style={styles.tagLocation}>{tag.location || tag.location_description}</Text>
                        <Text style={styles.tagId}>ID: {tag.tag_id || tag.id}</Text>
                      </View>
                    </View>
                    {isAdmin && (
                      <Pressable onPress={() => handleDeleteTag(tag.tag_id || tag.id, index)} style={styles.deleteBtn}>
                        <Trash2 size={16} strokeWidth={1.5} color={colors.status.error} />
                      </Pressable>
                    )}
                  </View>
                ))}
              </View>
            ) : (
              <Text style={styles.emptyText}>No NFC tags registered</Text>
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
    fontSize: 36,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -0.5,
  },
  section: {
    marginBottom: spacing.xl,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
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
  sectionDesc: {
    fontSize: 13,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
  addForm: {
    marginBottom: spacing.md,
  },
  inputSpacing: {
    marginTop: spacing.sm,
  },
  addFormButtons: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  cancelBtn: {
    opacity: 0.7,
  },
  nfcScanRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  tagIdInput: {
    flex: 1,
  },
  listContainer: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    overflow: 'hidden',
  },
  listItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.glass.border,
  },
  mappingContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    flex: 1,
  },
  fieldText: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
    backgroundColor: 'rgba(59, 130, 246, 0.2)',
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
  },
  formalText: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  tagContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    flex: 1,
  },
  tagInfo: {
    flex: 1,
  },
  tagLocation: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  tagId: {
    fontSize: 12,
    color: colors.text.muted,
  },
  deleteBtn: {
    padding: spacing.sm,
  },
  emptyText: {
    fontSize: 14,
    color: colors.text.muted,
    fontStyle: 'italic',
    paddingVertical: spacing.lg,
    textAlign: 'center',
  },
});
