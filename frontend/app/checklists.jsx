import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  TextInput,
  Modal,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ClipboardList,
  CheckCircle,
  Circle,
  X,
  AlertCircle,
  Briefcase,
  MapPin,
  ChevronRight,
} from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../src/components/GlassCard';
import GlassButton from '../src/components/GlassButton';
import { GlassSkeleton } from '../src/components/GlassSkeleton';
import FloatingNav from '../src/components/FloatingNav';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { checklistsAPI } from '../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../src/styles/theme';

export default function ChecklistsScreen() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [assignments, setAssignments] = useState([]);
  const [selectedAssignment, setSelectedAssignment] = useState(null);
  const [showCompletionModal, setShowCompletionModal] = useState(false);
  const [itemCompletions, setItemCompletions] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!authLoading) {
      if (!isAuthenticated) {
        router.replace('/login');
      }
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchAssignments();
    }
  }, [isAuthenticated]);

  const fetchAssignments = async () => {
    setLoading(true);
    try {
      const data = await checklistsAPI.getAssigned();
      setAssignments(data);
    } catch (error) {
      console.error('Failed to fetch assignments:', error);
      toast.error('Error', 'Could not load checklists');
    } finally {
      setLoading(false);
    }
  };

  const handleOpenChecklist = async (assignment) => {
    try {
      const details = await checklistsAPI.getAssignmentDetails(assignment.id);
      setSelectedAssignment(details);

      // Initialize completions from existing data
      const initialCompletions = {};
      if (details.completion?.item_completions) {
        Object.keys(details.completion.item_completions).forEach((itemId) => {
          const item = details.completion.item_completions[itemId];
          initialCompletions[itemId] = {
            checked: item.checked || false,
            note: item.note || '',
            timestamp: item.timestamp || new Date().toISOString(),
          };
        });
      } else {
        // Initialize empty for all items
        details.checklist.items.forEach((item) => {
          initialCompletions[item.id] = {
            checked: false,
            note: '',
            timestamp: new Date().toISOString(),
          };
        });
      }

      setItemCompletions(initialCompletions);
      setShowCompletionModal(true);
    } catch (error) {
      console.error('Failed to load checklist details:', error);
      toast.error('Error', 'Could not load checklist');
    }
  };

  const toggleItemCheck = (itemId) => {
    const newCompletions = {
      ...itemCompletions,
      [itemId]: {
        ...itemCompletions[itemId],
        checked: !itemCompletions[itemId]?.checked,
        timestamp: new Date().toISOString(),
      },
    };
    setItemCompletions(newCompletions);
    handleSave(newCompletions);
  };

  const updateItemNote = (itemId, note) => {
    setItemCompletions({
      ...itemCompletions,
      [itemId]: {
        ...itemCompletions[itemId],
        note,
        timestamp: new Date().toISOString(),
      },
    });
  };

  const handleSave = async (completions = itemCompletions) => {
    if (!selectedAssignment) return;

    setSaving(true);
    try {
      await checklistsAPI.updateCompletion(selectedAssignment.id, {
        item_completions: completions,
      });
      // Refresh assignments to update progress
      fetchAssignments();
    } catch (error) {
      console.error('Failed to save:', error);
      toast.error('Error', 'Could not save progress');
    } finally {
      setSaving(false);
    }
  };

  const handleClose = () => {
    // Save on close
    handleSave();
    setShowCompletionModal(false);
    setSelectedAssignment(null);
  };

  const getProgress = (assignment) => {
    if (!assignment.completion?.progress) return { completed: 0, total: 0, percentage: 0 };
    const { completed, total } = assignment.completion.progress;
    const percentage = total > 0 ? Math.round((completed / total) * 100) : 0;
    return { completed, total, percentage };
  };

  const isComplete = (assignment) => {
    const progress = getProgress(assignment);
    return progress.completed === progress.total && progress.total > 0;
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.header}>
            <IconPod size={48}>
              <ClipboardList size={24} strokeWidth={1.5} color="#4ade80" />
            </IconPod>
            <View style={styles.headerText}>
              <Text style={styles.headerLabel}>MY</Text>
              <Text style={styles.headerTitle}>Checklists</Text>
            </View>
          </View>

          {loading ? (
            <>
              <GlassSkeleton width="100%" height={120} borderRadiusValue={borderRadius.xl} style={styles.mb16} />
              <GlassSkeleton width="100%" height={120} borderRadiusValue={borderRadius.xl} style={styles.mb16} />
              <GlassSkeleton width="100%" height={120} borderRadiusValue={borderRadius.xl} />
            </>
          ) : assignments.length === 0 ? (
            <GlassCard style={styles.emptyCard}>
              <AlertCircle size={48} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={styles.emptyTitle}>No Checklists</Text>
              <Text style={styles.emptyText}>You don't have any assigned checklists yet</Text>
            </GlassCard>
          ) : (
            <View style={styles.assignmentsList}>
              {assignments.map((assignment) => {
                const progress = getProgress(assignment);
                const complete = isComplete(assignment);

                return (
                  <Pressable
                    key={assignment.id}
                    onPress={() => handleOpenChecklist(assignment)}
                    style={styles.assignmentCard}
                  >
                    <GlassCard style={[styles.card, complete && styles.cardComplete]}>
                      <View style={styles.cardHeader}>
                        <View style={styles.cardInfo}>
                          <Text style={styles.cardTitle}>{assignment.checklist?.title}</Text>
                          {assignment.checklist?.description && (
                            <Text style={styles.cardDescription} numberOfLines={2}>
                              {assignment.checklist.description}
                            </Text>
                          )}
                        </View>
                        {complete ? (
                          <CheckCircle size={24} strokeWidth={1.5} color="#4ade80" />
                        ) : (
                          <ChevronRight size={24} strokeWidth={1.5} color={colors.text.muted} />
                        )}
                      </View>

                      <View style={styles.cardMeta}>
                        <View style={styles.metaItem}>
                          <Briefcase size={14} strokeWidth={1.5} color={colors.text.muted} />
                          <Text style={styles.metaText}>{assignment.project_name}</Text>
                        </View>
                      </View>

                      <View style={styles.progressSection}>
                        <View style={styles.progressInfo}>
                          <Text style={styles.progressText}>
                            {progress.completed}/{progress.total} items
                          </Text>
                          <Text style={styles.progressPercent}>{progress.percentage}%</Text>
                        </View>
                        <View style={styles.progressBar}>
                          <View
                            style={[
                              styles.progressFill,
                              { width: `${progress.percentage}%` },
                              complete && styles.progressComplete,
                            ]}
                          />
                        </View>
                      </View>
                    </GlassCard>
                  </Pressable>
                );
              })}
            </View>
          )}
        </ScrollView>

        <FloatingNav activeRoute="/checklists" />

        {/* Completion Modal */}
        <Modal
          visible={showCompletionModal}
          animationType="slide"
          transparent
          onRequestClose={handleClose}
        >
          <View style={styles.modalOverlay}>
            <View style={styles.modalContent}>
              <View style={styles.modalHeader}>
                <View style={styles.modalHeaderLeft}>
                  <Text style={styles.modalTitle}>{selectedAssignment?.checklist?.title}</Text>
                  <Text style={styles.modalSubtitle}>{selectedAssignment?.project_name}</Text>
                </View>
                <Pressable onPress={handleClose}>
                  <X size={24} strokeWidth={1.5} color={colors.text.muted} />
                </Pressable>
              </View>

              <ScrollView style={styles.modalScroll} showsVerticalScrollIndicator={false}>
                {selectedAssignment?.checklist?.items.map((item, index) => {
                  const isChecked = itemCompletions[item.id]?.checked || false;

                  return (
                    <View key={item.id} style={styles.checklistItem}>
                      <Pressable
                        onPress={() => toggleItemCheck(item.id)}
                        style={styles.itemHeader}
                      >
                        <View style={styles.itemLeft}>
                          <View style={styles.checkIconContainer}>
                            {isChecked ? (
                              <CheckCircle size={24} strokeWidth={1.5} color="#4ade80" />
                            ) : (
                              <Circle size={24} strokeWidth={1.5} color={colors.text.muted} />
                            )}
                          </View>
                          <Text style={[styles.itemText, isChecked && styles.itemTextChecked]}>
                            {item.text}
                          </Text>
                        </View>
                      </Pressable>

                      {isChecked && (
                        <TextInput
                          style={styles.noteInput}
                          value={itemCompletions[item.id]?.note || ''}
                          onChangeText={(text) => updateItemNote(item.id, text)}
                          onBlur={() => handleSave()}
                          placeholder="Add note (optional)"
                          placeholderTextColor={colors.text.subtle}
                          multiline
                        />
                      )}
                    </View>
                  );
                })}
              </ScrollView>

              <View style={styles.modalFooter}>
                <GlassButton
                  variant="primary"
                  title="Done"
                  onPress={handleClose}
                  loading={saving}
                />
              </View>
            </View>
          </View>
        </Modal>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollView: { flex: 1 },
  scrollContent: { padding: spacing.lg, paddingBottom: 120 },
  header: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, marginBottom: spacing.xl },
  headerText: { flex: 1 },
  headerLabel: { ...typography.label, color: colors.text.muted, marginBottom: spacing.xs },
  headerTitle: { fontSize: 32, fontWeight: '200', color: colors.text.primary, letterSpacing: -1 },
  mb16: { marginBottom: spacing.md },
  emptyCard: { alignItems: 'center', paddingVertical: spacing.xxl },
  emptyTitle: { fontSize: 18, fontWeight: '500', color: colors.text.primary, marginTop: spacing.md },
  emptyText: { fontSize: 14, color: colors.text.muted, marginTop: spacing.xs },
  assignmentsList: { gap: spacing.md },
  assignmentCard: { marginBottom: 0 },
  card: { padding: spacing.lg },
  cardComplete: { borderColor: 'rgba(74,222,128,0.3)', borderWidth: 1 },
  cardHeader: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: spacing.md },
  cardInfo: { flex: 1, marginRight: spacing.md },
  cardTitle: { fontSize: 18, fontWeight: '500', color: colors.text.primary, marginBottom: spacing.xs },
  cardDescription: { fontSize: 14, color: colors.text.secondary, lineHeight: 20 },
  cardMeta: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, marginBottom: spacing.md },
  metaItem: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  metaText: { fontSize: 13, color: colors.text.muted },
  progressSection: { marginTop: spacing.sm },
  progressInfo: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.xs },
  progressText: { fontSize: 13, color: colors.text.secondary },
  progressPercent: { fontSize: 13, fontWeight: '600', color: '#4ade80' },
  progressBar: { height: 6, backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: 3, overflow: 'hidden' },
  progressFill: { height: '100%', backgroundColor: '#4ade80', borderRadius: 3 },
  progressComplete: { backgroundColor: '#4ade80' },
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.7)', justifyContent: 'flex-end' },
  modalContent: { backgroundColor: '#1a1a2e', borderTopLeftRadius: borderRadius.xxl, borderTopRightRadius: borderRadius.xxl, height: '90%', borderTopWidth: 1, borderColor: colors.glass.border },
  modalHeader: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.glass.border },
  modalHeaderLeft: { flex: 1, marginRight: spacing.md },
  modalTitle: { fontSize: 20, fontWeight: '500', color: colors.text.primary, marginBottom: spacing.xs },
  modalSubtitle: { fontSize: 14, color: colors.text.muted },
  modalScroll: { flex: 1, padding: spacing.lg },
  checklistItem: { marginBottom: spacing.lg, backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: borderRadius.lg, padding: spacing.md, borderWidth: 1, borderColor: colors.glass.border },
  itemHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  itemLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flex: 1 },
  checkIconContainer: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  itemText: { fontSize: 15, color: colors.text.primary, flex: 1 },
  itemTextChecked: { textDecorationLine: 'line-through', color: colors.text.muted },
  noteInput: { marginTop: spacing.md, backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: borderRadius.md, borderWidth: 1, borderColor: colors.glass.border, padding: spacing.md, color: colors.text.primary, fontSize: 14, minHeight: 60, textAlignVertical: 'top' },
  modalFooter: { padding: spacing.lg, borderTopWidth: 1, borderTopColor: colors.glass.border },
});
