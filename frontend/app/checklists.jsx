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
import OfflineNotice from '../src/components/OfflineNotice';
import { settleFetch, isOfflineError } from '../src/utils/offlineState';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import { semantic, withAlpha } from '../src/styles/semanticColors';
import { useTheme } from '../src/context/ThemeContext';

export default function ChecklistsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [assignments, setAssignments] = useState([]);
  // OFFLINE vs EMPTY — 'ok' | 'offline' | 'error'. On a failed load this screen
  // used to fall through to "No Checklists / You don't have any assigned
  // checklists yet", which is a claim about the server, not about the network.
  const [fetchState, setFetchState] = useState('ok');
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
    const r = await settleFetch(() => checklistsAPI.getAssigned());
    setFetchState(r.status);
    if (r.status === 'ok') {
      setAssignments(Array.isArray(r.data) ? r.data : []);
    } else {
      console.error('Failed to fetch assignments:', r.error);
      // Keep whatever we already had on screen; the banner below explains why
      // it may be stale. Never blank the list into a confident empty state.
    }
    setLoading(false);
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
      toast.error(
        isOfflineError(error) ? 'Offline' : 'Error',
        isOfflineError(error)
          ? 'This checklist is not saved on this device — reconnect to open it.'
          : 'Could not load checklist',
      );
    }
  };

  const toggleItemCheck = (itemId) => {
    const previous = itemCompletions;
    const newCompletions = {
      ...itemCompletions,
      [itemId]: {
        ...itemCompletions[itemId],
        checked: !itemCompletions[itemId]?.checked,
        timestamp: new Date().toISOString(),
      },
    };
    setItemCompletions(newCompletions);
    // `previous` is the rollback: a tick that never reached the server must not
    // stay ticked on screen — that is a failed write looking like a success.
    handleSave(newCompletions, previous);
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

  // Returns true only when the server actually accepted the write. Callers use
  // that to decide whether it is honest to close the sheet.
  const handleSave = async (completions = itemCompletions, revertTo = null) => {
    if (!selectedAssignment) return true; // nothing to save == nothing failed

    setSaving(true);
    try {
      await checklistsAPI.updateCompletion(selectedAssignment.id, {
        item_completions: completions,
      });
      // Refresh assignments to update progress
      fetchAssignments();
      return true;
    } catch (error) {
      console.error('Failed to save:', error);
      if (revertTo) setItemCompletions(revertTo);
      toast.error(
        isOfflineError(error) ? 'Not saved — offline' : 'Not saved',
        isOfflineError(error)
          ? 'Your change was not recorded. Reconnect and tap it again.'
          : 'Could not save progress. Try again.',
      );
      return false;
    } finally {
      setSaving(false);
    }
  };

  // "Done" — flush any pending note, and only DISMISS if the save landed.
  // Closing the sheet on a failed write reads as "saved", which is the lie this
  // change exists to kill. The X / back button uses handleDismiss instead, so a
  // user offline is never trapped in the sheet.
  const handleClose = async () => {
    const ok = await handleSave();
    if (!ok) return;
    setShowCompletionModal(false);
    setSelectedAssignment(null);
  };

  // Explicit close WITHOUT claiming a save. Item ticks are written (and rolled
  // back) individually on tap and notes on blur, so this discards nothing that
  // was ever reported as saved.
  const handleDismiss = () => {
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
      <SafeAreaView style={s.container} edges={['top']}>
        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          <View style={s.header}>
            <IconPod size={48}>
              <ClipboardList size={24} strokeWidth={1.5} color={semantic.neutral} />
            </IconPod>
            <View style={s.headerText}>
              <Text style={s.headerLabel}>MY</Text>
              <Text style={s.headerTitle}>Checklists</Text>
            </View>
          </View>

          {loading ? (
            <>
              <GlassSkeleton width="100%" height={120} borderRadiusValue={borderRadius.xl} style={s.mb16} />
              <GlassSkeleton width="100%" height={120} borderRadiusValue={borderRadius.xl} style={s.mb16} />
              <GlassSkeleton width="100%" height={120} borderRadiusValue={borderRadius.xl} />
            </>
          ) : fetchState !== 'ok' && assignments.length === 0 ? (
            /* The LOAD failed and we have nothing to show. "No Checklists"
               would assert none are assigned — say what actually happened. */
            <OfflineNotice mode={fetchState} />
          ) : assignments.length === 0 ? (
            <GlassCard style={s.emptyCard}>
              <AlertCircle size={48} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.emptyTitle}>No Checklists</Text>
              <Text style={s.emptyText}>You don't have any assigned checklists yet</Text>
            </GlassCard>
          ) : (
            <View style={s.assignmentsList}>
              {/* Stale list served after a failed refresh — flag it. */}
              {fetchState !== 'ok' && (
                <OfflineNotice mode={fetchState} cachedCount={assignments.length} />
              )}
              {assignments.map((assignment) => {
                const progress = getProgress(assignment);
                const complete = isComplete(assignment);

                return (
                  <Pressable
                    key={assignment.id}
                    onPress={() => handleOpenChecklist(assignment)}
                    style={s.assignmentCard}
                  >
                    <GlassCard style={[s.card, complete && s.cardComplete]}>
                      <View style={s.cardHeader}>
                        <View style={s.cardInfo}>
                          <Text style={s.cardTitle}>{assignment.checklist?.title}</Text>
                          {assignment.checklist?.description && (
                            <Text style={s.cardDescription} numberOfLines={2}>
                              {assignment.checklist.description}
                            </Text>
                          )}
                        </View>
                        {complete ? (
                          <CheckCircle size={24} strokeWidth={1.5} color={semantic.verified} />
                        ) : (
                          <ChevronRight size={24} strokeWidth={1.5} color={colors.text.muted} />
                        )}
                      </View>

                      <View style={s.cardMeta}>
                        <View style={s.metaItem}>
                          <Briefcase size={14} strokeWidth={1.5} color={colors.text.muted} />
                          <Text style={s.metaText}>{assignment.project_name}</Text>
                        </View>
                      </View>

                      <View style={s.progressSection}>
                        <View style={s.progressInfo}>
                          <Text style={s.progressText}>
                            {progress.completed}/{progress.total} items
                          </Text>
                          <Text style={s.progressPercent}>{progress.percentage}%</Text>
                        </View>
                        <View style={s.progressBar}>
                          <View
                            style={[
                              s.progressFill,
                              { width: `${progress.percentage}%` },
                              complete && s.progressComplete,
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
          onRequestClose={handleDismiss}
        >
          <View style={s.modalOverlay}>
            <View style={s.modalContent}>
              <View style={s.modalHeader}>
                <View style={s.modalHeaderLeft}>
                  <Text style={s.modalTitle}>{selectedAssignment?.checklist?.title}</Text>
                  <Text style={s.modalSubtitle}>{selectedAssignment?.project_name}</Text>
                </View>
                <Pressable onPress={handleDismiss}>
                  <X size={24} strokeWidth={1.5} color={colors.text.muted} />
                </Pressable>
              </View>

              <ScrollView style={s.modalScroll} showsVerticalScrollIndicator={false}>
                {selectedAssignment?.checklist?.items.map((item, index) => {
                  const isChecked = itemCompletions[item.id]?.checked || false;

                  return (
                    <View key={item.id} style={s.checklistItem}>
                      <Pressable
                        onPress={() => toggleItemCheck(item.id)}
                        style={s.itemHeader}
                      >
                        <View style={s.itemLeft}>
                          <View style={s.checkIconContainer}>
                            {isChecked ? (
                              <CheckCircle size={24} strokeWidth={1.5} color={semantic.verified} />
                            ) : (
                              <Circle size={24} strokeWidth={1.5} color={colors.text.muted} />
                            )}
                          </View>
                          <Text style={[s.itemText, isChecked && s.itemTextChecked]}>
                            {item.text}
                          </Text>
                        </View>
                      </Pressable>

                      {isChecked && (
                        <TextInput
                          style={s.noteInput}
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

              <View style={s.modalFooter}>
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

function buildStyles(colors, isDark) {
  return StyleSheet.create({
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
  cardComplete: { borderColor: semantic.verifiedBorder, borderWidth: 1 },
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
  progressBar: { height: 6, backgroundColor: withAlpha('#ffffff', 0.05), borderRadius: 3, overflow: 'hidden' },
  progressFill: { height: '100%', backgroundColor: '#4ade80', borderRadius: 3 },
  progressComplete: { backgroundColor: '#4ade80' },
  modalOverlay: { flex: 1, backgroundColor: withAlpha('#000000', 0.7), justifyContent: 'flex-end' },
  modalContent: { backgroundColor: '#1a1a2e', borderTopLeftRadius: borderRadius.xxl, borderTopRightRadius: borderRadius.xxl, height: '90%', borderTopWidth: 1, borderColor: colors.glass.border },
  modalHeader: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.glass.border },
  modalHeaderLeft: { flex: 1, marginRight: spacing.md },
  modalTitle: { fontSize: 20, fontWeight: '500', color: colors.text.primary, marginBottom: spacing.xs },
  modalSubtitle: { fontSize: 14, color: colors.text.muted },
  modalScroll: { flex: 1, padding: spacing.lg },
  checklistItem: { marginBottom: spacing.lg, backgroundColor: withAlpha('#ffffff', 0.03), borderRadius: borderRadius.lg, padding: spacing.md, borderWidth: 1, borderColor: colors.glass.border },
  itemHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  itemLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flex: 1 },
  checkIconContainer: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  itemText: { fontSize: 15, color: colors.text.primary, flex: 1 },
  itemTextChecked: { textDecorationLine: 'line-through', color: colors.text.muted },
  noteInput: { marginTop: spacing.md, backgroundColor: withAlpha('#ffffff', 0.05), borderRadius: borderRadius.md, borderWidth: 1, borderColor: colors.glass.border, padding: spacing.md, color: colors.text.primary, fontSize: 14, minHeight: 60, textAlignVertical: 'top' },
  modalFooter: { padding: spacing.lg, borderTopWidth: 1, borderTopColor: colors.glass.border },
});
}
