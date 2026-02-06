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
          ) : assignments.le
