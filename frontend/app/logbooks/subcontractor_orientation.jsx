import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  ShieldCheck,
  CheckCircle,
  Save,
  User,
  Calendar,
  ChevronDown,
  ChevronUp,
  Plus,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

/**
 * Subcontractor Safety Orientation
 *
 * This screen reads orientation documents that were automatically created
 * when workers registered via NFC (their checklist answers are stored in
 * logbooks.data.checklist). The CP can:
 *   - See all completed orientations for the project
 *   - Add their CP signature to any document
 *   - Manually add a new orientation for a walk-in worker
 *   - See the full checklist answers per worker
 */

// These items mirror what the NFC registration screen captures
const ORIENTATION_SECTIONS = [
  {
    section: 'General Safety Rules',
    items: [
      { key: 'hard_hats', label: 'Hard hats required at all times on site' },
      { key: 'safety_boots', label: 'Safety boots required (steel toe, ANSI rated)' },
      { key: 'safety_glasses', label: 'Safety glasses / eye protection required' },
      { key: 'high_vis', label: 'High-visibility vest required near traffic' },
      { key: 'no_horseplay', label: 'No horseplay, running, or unsafe behavior' },
      { key: 'report_hazards', label: 'Report all hazards to CP immediately' },
    ],
  },
  {
    section: 'Fall Protection',
    items: [
      { key: 'fall_protection_required', label: 'Fall protection required at 6 ft and above' },
      { key: 'harness_inspection', label: 'Inspect harness before each use' },
      { key: 'ladder_safety', label: 'Three-point contact on ladders at all times' },
      { key: 'scaffold_rules', label: 'Only use scaffold as erected — no modifications' },
    ],
  },
  {
    section: 'Emergency Procedures',
    items: [
      { key: 'emergency_exits', label: 'Emergency exit locations reviewed' },
      { key: 'first_aid', label: 'First aid kit location reviewed' },
      { key: 'emergency_contact', label: 'Emergency contact numbers provided' },
      { key: 'incident_reporting', label: 'All incidents must be reported immediately' },
    ],
  },
  {
    section: 'Site Rules',
    items: [
      { key: 'no_drugs_alcohol', label: 'Zero tolerance for drugs and alcohol on site' },
      { key: 'sign_in_out', label: 'Must sign in and out every day' },
      { key: 'authorized_areas', label: 'Only enter authorized work areas' },
      { key: 'housekeeping', label: 'Keep work area clean at all times' },
    ],
  },
];

const ALL_KEYS = ORIENTATION_SECTIONS.flatMap(s => s.items.map(i => i.key));

export default function SubcontractorOrientation() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const { cpName: newCpName, setCpName: setNewCpName, cpSignature: newCpSignature, setCpSignature: setNewCpSignature, autoSave } = useCpProfile();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // All orientation documents for this project
  const [orientations, setOrientations] = useState([]);
  // Which card is expanded
  const [expandedIndex, setExpandedIndex] = useState(null);
  // Show form to add new manual orientation
  const [showAddForm, setShowAddForm] = useState(false);

  // New manual entry form state
  const [newName, setNewName] = useState('');
  const [newCompany, setNewCompany] = useState('');
  const [newTrade, setNewTrade] = useState('');
  const [newOsha, setNewOsha] = useState('');
  const [newChecklist, setNewChecklist] = useState({});
  const [newOrientationNum, setNewOrientationNum] = useState('');

  useEffect(() => {
    fetchData();
  }, [projectId]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [logs] = await Promise.all([
        // Get ALL orientation docs for this project (no date filter — these are ongoing)
        logbooksAPI.getByProject(projectId, 'subcontractor_orientation').catch(() => []),
      ]);
      setOrientations(Array.isArray(logs) ? logs : []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // CP signs an existing orientation document
  const handleSignExisting = async (orientation, cpSig, cpN) => {
    const id = orientation.id || orientation._id;
    try {
      await logbooksAPI.update(id, {
        cp_signature: cpSig,
        cp_name: cpN,
        status: 'submitted',
      });
      // Update local state
      setOrientations(prev =>
        prev.map(o =>
          (o.id || o._id) === id
            ? { ...o, cp_signature: cpSig, cp_name: cpN, status: 'submitted' }
            : o
        )
      );
      toast.success('Signed', `Orientation for ${orientation.data?.worker_name} signed`);
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save signature');
    }
  };

  // Create a brand new manual orientation
  const handleCreateNew = async () => {
    if (!newName.trim() || !newCompany.trim()) {
      toast.warning('Required', 'Worker name and company are required');
      return;
    }
    setSaving(true);
    try {
      const today = new Date().toISOString().split('T')[0];
      const created = await logbooksAPI.create({
        project_id: projectId,
        log_type: 'subcontractor_orientation',
        date: today,
        cp_signature: newCpSignature,
        cp_name: newCpName,
        status: newCpSignature ? 'submitted' : 'draft',
        data: {
          worker_name: newName.trim(),
          worker_company: newCompany.trim(),
          worker_trade: newTrade.trim(),
          osha_number: newOsha.trim(),
          orientation_number: newOrientationNum.trim(),
          checklist: newChecklist,
          completed_at: new Date().toISOString(),
          worker_signature: null,
        },
      });
      setOrientations(prev => [created, ...prev]);
      // Reset form
      setNewName('');
      setNewCompany('');
      setNewTrade('');
      setNewOsha('');
      setNewOrientationNum('');
      setNewChecklist({});
      setShowAddForm(false);
      await autoSave(newCpName, newCpSignature);
      toast.success('Created', 'Orientation record added');
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not create orientation');
    } finally {
      setSaving(false);
    }
  };

  const toggleNewChecklistItem = (key) => {
    setNewChecklist(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const getChecklistCompletion = (checklist) => {
    if (!checklist) return { checked: 0, total: ALL_KEYS.length };
    const checked = ALL_KEYS.filter(k => checklist[k]).length;
    return { checked, total: ALL_KEYS.length };
  };

  if (loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container} edges={['top']}>
          <View style={styles.loadingCenter}>
            <ActivityIndicator size="large" color={colors.text.primary} />
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
            <View>
              <Text style={styles.headerTitle}>Subcontractor Safety Orientation</Text>
              <Text style={styles.headerSub}>
                {orientations.length} worker{orientations.length !== 1 ? 's' : ''} on record
              </Text>
            </View>
          </View>
        </View>

        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >

          {/* Add new button */}
          <GlassButton
            title="+ Add Manual Orientation"
            icon={<Plus size={16} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={() => setShowAddForm(!showAddForm)}
            style={styles.addBtn}
          />

          {/* Manual add form */}
          {showAddForm && (
            <GlassCard style={styles.addForm}>
              <Text style={styles.sectionTitle}>New Orientation Record</Text>

              {[
                { label: 'Worker Full Name *', value: newName, setter: setNewName },
                { label: 'Company *', value: newCompany, setter: setNewCompany },
                { label: 'Trade', value: newTrade, setter: setNewTrade },
                { label: 'OSHA Card #', value: newOsha, setter: setNewOsha },
                { label: 'Orientation # (optional)', value: newOrientationNum, setter: setNewOrientationNum },
              ].map((f) => (
                <View key={f.label} style={styles.fieldRow}>
                  <Text style={styles.fieldLabel}>{f.label}</Text>
                  <TextInput
                    style={styles.fieldInput}
                    value={f.value}
                    onChangeText={f.setter}
                    placeholder="—"
                    placeholderTextColor={colors.text.subtle}
                    autoCapitalize="words"
                  />
                </View>
              ))}

              {/* Checklist */}
              <Text style={[styles.sectionTitle, { marginTop: spacing.md }]}>
                Safety Topics Reviewed
              </Text>
              {ORIENTATION_SECTIONS.map((section) => (
                <View key={section.section} style={styles.sectionBlock}>
                  <Text style={styles.sectionLabel}>{section.section}</Text>
                  {section.items.map((item) => (
                    <Pressable
                      key={item.key}
                      onPress={() => toggleNewChecklistItem(item.key)}
                      style={styles.checkRow}
                    >
                      <View style={[
                        styles.checkbox,
                        newChecklist[item.key] && styles.checkboxActive,
                      ]}>
                        {newChecklist[item.key] && (
                          <CheckCircle size={14} strokeWidth={2} color="#4ade80" />
                        )}
                      </View>
                      <Text style={[
                        styles.checkLabel,
                        newChecklist[item.key] && styles.checkLabelActive,
                      ]}>
                        {item.label}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              ))}

              {/* CP signature */}
              <Text style={[styles.sectionTitle, { marginTop: spacing.md }]}>CP Signature</Text>
              {newCpSignature && (
                <View style={styles.autoSignBadge}>
                  <CheckCircle size={14} strokeWidth={1.5} color="#4ade80" />
                  <Text style={styles.autoSignText}>Auto-filled from your saved profile</Text>
                </View>
              )}
              <SignaturePad
                title="Competent Person Signature"
                signerName={newCpName}
                onNameChange={setNewCpName}
                existingSignature={newCpSignature}
                onSignatureCapture={setNewCpSignature}
              />

              <View style={styles.formActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => setShowAddForm(false)}
                  style={styles.cancelBtn}
                />
                <GlassButton
                  title={saving ? 'Saving...' : 'Save Orientation'}
                  onPress={handleCreateNew}
                  loading={saving}
                  style={styles.saveBtn}
                />
              </View>
            </GlassCard>
          )}

          {/* Existing orientation cards */}
          {orientations.length === 0 ? (
            <GlassCard style={styles.emptyCard}>
              <ShieldCheck size={40} strokeWidth={1} color={colors.text.subtle} />
              <Text style={styles.emptyTitle}>No orientations yet</Text>
              <Text style={styles.emptySubtitle}>
                Orientations are automatically created when workers register via NFC.
                You can also add one manually above.
              </Text>
            </GlassCard>
          ) : (
            <>
              <Text style={styles.listLabel}>ORIENTATION RECORDS</Text>
              {orientations.map((orient, index) => {
                const d = orient.data || {};
                const isExpanded = expandedIndex === index;
                const isSigned = orient.status === 'submitted' && orient.cp_signature;
                const { checked, total } = getChecklistCompletion(d.checklist);

                return (
                  <GlassCard key={orient._id || orient.id || index} style={styles.orientCard}>

                    {/* Card header — always visible */}
                    <Pressable
                      style={styles.orientHeader}
                      onPress={() => setExpandedIndex(isExpanded ? null : index)}
                    >
                      <View style={styles.orientAvatar}>
                        <User size={18} strokeWidth={1.5} color={colors.text.secondary} />
                      </View>
                      <View style={styles.orientInfo}>
                        <Text style={styles.orientName}>{d.worker_name || 'Unknown Worker'}</Text>
                        <Text style={styles.orientMeta}>
                          {d.worker_company || '—'}
                          {d.worker_trade ? ` · ${d.worker_trade}` : ''}
                        </Text>
                        <Text style={styles.orientDate}>
                          {d.completed_at
                            ? new Date(d.completed_at).toLocaleDateString('en-US', {
                                month: 'short', day: 'numeric', year: 'numeric',
                              })
                            : orient.date}
                        </Text>
                      </View>
                      <View style={styles.orientRight}>
                        <View style={[styles.statusBadge, isSigned ? styles.statusSigned : styles.statusPending]}>
                          {isSigned
                            ? <CheckCircle size={12} strokeWidth={2} color="#4ade80" />
                            : null}
                          <Text style={[styles.statusText, isSigned ? styles.statusTextSigned : styles.statusTextPending]}>
                            {isSigned ? 'Signed' : 'Needs CP sig'}
                          </Text>
                        </View>
                        {isExpanded
                          ? <ChevronUp size={16} strokeWidth={1.5} color={colors.text.muted} />
                          : <ChevronDown size={16} strokeWidth={1.5} color={colors.text.muted} />}
                      </View>
                    </Pressable>

                    {/* Expanded detail */}
                    {isExpanded && (
                      <View style={styles.orientDetail}>
                        <View style={styles.orientDetailDivider} />

                        {/* Worker details */}
                        <View style={styles.detailGrid}>
                          {[
                            { label: 'OSHA #', value: d.osha_number },
                            { label: 'Orientation #', value: d.orientation_number },
                          ].filter(f => f.value).map((f) => (
                            <View key={f.label} style={styles.detailRow}>
                              <Text style={styles.detailLabel}>{f.label}</Text>
                              <Text style={styles.detailValue}>{f.value}</Text>
                            </View>
                          ))}
                        </View>

                        {/* Checklist summary */}
                        <View style={styles.checklistSummary}>
                          <Text style={styles.checklistSummaryLabel}>
                            Checklist: {checked}/{total} items reviewed
                          </Text>
                          <View style={styles.checklistBar}>
                            <View style={[
                              styles.checklistBarFill,
                              { width: `${Math.round((checked / total) * 100)}%` },
                            ]} />
                          </View>
                        </View>

                        {/* Show all checklist items */}
                        {ORIENTATION_SECTIONS.map((section) => (
                          <View key={section.section} style={styles.sectionBlock}>
                            <Text style={styles.sectionLabel}>{section.section}</Text>
                            {section.items.map((item) => {
                              const isChecked = d.checklist ? !!d.checklist[item.key] : false;
                              return (
                                <View key={item.key} style={styles.readonlyCheckRow}>
                                  <View style={[styles.checkbox, isChecked && styles.checkboxActive]}>
                                    {isChecked && <CheckCircle size={12} strokeWidth={2} color="#4ade80" />}
                                  </View>
                                  <Text style={[styles.checkLabel, isChecked && styles.checkLabelActive]}>
                                    {item.label}
                                  </Text>
                                </View>
                              );
                            })}
                          </View>
                        ))}

                        {/* CP signature — add if not yet signed */}
                        {!isSigned && (
                          <OrientationSignaturePanel
                          onSign={(sig, name) => handleSignExisting(orient, sig, name)}
                          />
                        )}

                        {isSigned && (
                          <View style={styles.signedBanner}>
                            <CheckCircle size={16} strokeWidth={1.5} color="#4ade80" />
                            <Text style={styles.signedBannerText}>
                              Signed by {orient.cp_name}
                            </Text>
                          </View>
                        )}
                      </View>
                    )}

                  </GlassCard>
                );
              })}
            </>
          )}
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

/**
 * Inline signature panel for adding CP sig to an existing orientation.
 * Separate component so each card can have its own signature state.
 */
function OrientationSignaturePanel({ onSign }) {
  const { cpName, setCpName, cpSignature, setCpSignature, autoSave: innerAutoSave } = useCpProfile();
  const [saving, setSaving] = useState(false);

  const handleSign = async () => {
    if (!cpSignature) return;
    setSaving(true);
    try {
      await innerAutoSave(cpName, cpSignature);
      await onSign(cpSignature, cpName);
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={styles.signPanel}>
      <Text style={styles.sectionTitle}>Add Your CP Signature</Text>
      <SignaturePad
        title="Competent Person Signature"
        signerName={cpName}
        onNameChange={setCpName}
        existingSignature={cpSignature}
        onSignatureCapture={setCpSignature}
      />
      <GlassButton
        title={saving ? 'Signing...' : 'Sign This Orientation'}
        icon={<CheckCircle size={16} strokeWidth={1.5} color="#fff" />}
        onPress={handleSign}
        loading={saving}
        disabled={!cpSignature}
        style={styles.signBtn}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  loadingCenter: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.08)',
  },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flex: 1 },
  headerTitle: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
  headerSub: { fontSize: 11, color: colors.text.muted },
  scrollView: { flex: 1 },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: 100,
    maxWidth: 720,
    width: '100%',
    alignSelf: 'center',
  },
  addBtn: { marginBottom: spacing.md },
  addForm: { marginBottom: spacing.md, padding: spacing.lg },
  sectionTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: spacing.sm,
  },
  fieldRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.05)',
    gap: spacing.md,
  },
  fieldLabel: { flex: 1, fontSize: 13, color: colors.text.secondary },
  fieldInput: {
    flex: 1.5,
    fontSize: 14,
    color: colors.text.primary,
    padding: spacing.xs,
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: borderRadius.sm,
  },
  sectionBlock: { marginBottom: spacing.md },
  sectionLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: spacing.sm,
    marginTop: spacing.sm,
  },
  checkRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  readonlyCheckRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    paddingVertical: spacing.xs,
    opacity: 0.9,
  },
  checkbox: {
    width: 22,
    height: 22,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.15)',
    backgroundColor: 'rgba(255,255,255,0.04)',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 1,
    flexShrink: 0,
  },
  checkboxActive: {
    backgroundColor: 'rgba(74,222,128,0.1)',
    borderColor: '#4ade80',
  },
  checkLabel: { flex: 1, fontSize: 13, color: colors.text.muted, lineHeight: 18 },
  checkLabelActive: { color: colors.text.secondary },
  autoSignBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.md,
    padding: spacing.sm,
    backgroundColor: 'rgba(74,222,128,0.08)',
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: 'rgba(74,222,128,0.2)',
  },
  autoSignText: { fontSize: 12, color: '#4ade80' },
  formActions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md },
  cancelBtn: { flex: 1 },
  saveBtn: {
    flex: 2,
    backgroundColor: 'rgba(139,92,246,0.2)',
    borderColor: 'rgba(139,92,246,0.4)',
  },
  emptyCard: {
    alignItems: 'center',
    padding: spacing.xxl,
    gap: spacing.md,
  },
  emptyTitle: { fontSize: 17, fontWeight: '500', color: colors.text.primary },
  emptySubtitle: {
    fontSize: 13,
    color: colors.text.muted,
    textAlign: 'center',
    lineHeight: 20,
  },
  listLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.sm,
    marginTop: spacing.sm,
  },
  orientCard: { marginBottom: spacing.sm, padding: 0, overflow: 'hidden' },
  orientHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
  },
  orientAvatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(139,92,246,0.15)',
    borderWidth: 1,
    borderColor: 'rgba(139,92,246,0.3)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  orientInfo: { flex: 1 },
  orientName: { fontSize: 15, fontWeight: '500', color: colors.text.primary },
  orientMeta: { fontSize: 12, color: colors.text.muted, marginTop: 1 },
  orientDate: { fontSize: 11, color: colors.text.subtle, marginTop: 2 },
  orientRight: { alignItems: 'flex-end', gap: spacing.xs },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: borderRadius.full,
  },
  statusSigned: { backgroundColor: 'rgba(74,222,128,0.15)' },
  statusPending: { backgroundColor: 'rgba(245,158,11,0.15)' },
  statusText: { fontSize: 11, fontWeight: '600' },
  statusTextSigned: { color: '#4ade80' },
  statusTextPending: { color: '#f59e0b' },
  orientDetail: { paddingHorizontal: spacing.md, paddingBottom: spacing.md },
  orientDetailDivider: {
    height: 1,
    backgroundColor: 'rgba(255,255,255,0.08)',
    marginBottom: spacing.md,
  },
  detailGrid: { marginBottom: spacing.sm },
  detailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.04)',
  },
  detailLabel: { fontSize: 11, color: colors.text.muted, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.5 },
  detailValue: { fontSize: 13, color: colors.text.primary },
  checklistSummary: { marginBottom: spacing.md },
  checklistSummaryLabel: { fontSize: 12, color: colors.text.muted, marginBottom: spacing.xs },
  checklistBar: {
    height: 4,
    backgroundColor: 'rgba(255,255,255,0.08)',
    borderRadius: 2,
    overflow: 'hidden',
  },
  checklistBarFill: {
    height: '100%',
    backgroundColor: '#8b5cf6',
    borderRadius: 2,
  },
  signPanel: { marginTop: spacing.md },
  signBtn: {
    marginTop: spacing.md,
    backgroundColor: 'rgba(139,92,246,0.2)',
    borderColor: 'rgba(139,92,246,0.4)',
  },
  signedBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.md,
    padding: spacing.sm,
    backgroundColor: 'rgba(74,222,128,0.08)',
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: 'rgba(74,222,128,0.2)',
  },
  signedBannerText: { fontSize: 13, color: '#4ade80', fontWeight: '500' },
});
