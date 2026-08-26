import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  TextInput,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  HardHat,
  Plus,
  X,
  Save,
  RotateCw,
  ShieldAlert,
  Briefcase,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import { projectsAPI, tradesAPI } from '../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';
import HeaderBrand from '../../../src/components/HeaderBrand';
import { withAlpha } from '../../../src/styles/semanticColors';
import OfflineNotice from '../../../src/components/OfflineNotice';
import { readCachedProject } from '../../../src/utils/projectCache';
import { isOfflineError, settleFetch } from '../../../src/utils/offlineState';

/**
 * Per-project subcontractor roster editor.
 *
 * Each entry pairs a trade with the specific company doing that trade on this
 * project.
 *
 * TWO ACTORS, AND THE OLD COMMENT ONLY DESCRIBED ONE. It ended "No free-text",
 * which was true of the WORKER and false of the ADMIN — and it sat directly
 * above the admin's free-text TextInput. That is how "Framers" reached
 * production while a twenty-entry list sat two files away validating nothing.
 *
 *   THE WORKER, at the NFC gate: picks one combined trade+company entry from a
 *   dropdown built out of this roster. Both fields come from the pick. No
 *   free-text, and that was always true.
 *
 *   THE ADMIN, here: picks a trade from the server's controlled vocabulary.
 *   Free-text is still reachable — a fixed list always lags a live jobsite —
 *   but only through an explicit "add a trade not on the list" step, so an
 *   admin who goes off-vocabulary knows he did.
 *
 * The vocabulary is FETCHED, never carried. TRADE_SUGGESTIONS used to live in
 * this file as a second copy of the server's list; a test now asserts no such
 * copy exists.
 */


export default function ProjectTradesScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [project, setProject] = useState(null);
  const [assignments, setAssignments] = useState([]); // [{trade, company}]
  const [newTrade, setNewTrade] = useState('');
  const [newCompany, setNewCompany] = useState('');
  const [showSuggest, setShowSuggest] = useState(false);
  // The server's controlled list, fetched. `deprecated` labels stay VALID on
  // rows that already carry them but are never offered for a new pick, so they
  // are held separately and only consulted by isVocabularyTrade.
  const [vocabulary, setVocabulary] = useState([]);
  const [deprecatedTrades, setDeprecatedTrades] = useState([]);
  // The explicit off-list step. Never entered by mistyping.
  const [customMode, setCustomMode] = useState(false);
  const [dirty, setDirty] = useState(false);
  // 'ok' | 'offline' | 'error'. Anything but 'ok' means the roster on screen is
  // a cached copy (or nothing) — and that saving is impossible right now.
  const [fetchState, setFetchState] = useState('ok');

  const isAdmin = user?.role === 'admin';
  const readOnly = fetchState !== 'ok';
  // Soft-deleted rows are kept in state (they must be SENT back marked
  // inactive) but are never shown and never offered for selection.
  const visibleAssignments = assignments.filter((a) => a.status !== 'inactive');

  /**
   * Is this trade a published label?
   *
   * MIRRORS server._trade_source, which uses _roster_key -- strip + casefold --
   * the project's one normalization rule, already mirrored a third time by
   * rosterKey() in checkin.html. The server is authoritative; this copy only
   * decides what the screen SAYS, never what is stored.
   *
   * Deprecated labels count. They were published, so a row carrying one is not
   * an admin's off-list improvisation -- it is history, and it must never be
   * re-spelled.
   */
  const rosterKey = (v) => String(v || '').trim().toLowerCase();
  const knownTradeKeys = React.useMemo(
    () => new Set([...vocabulary, ...deprecatedTrades].map(rosterKey)),
    [vocabulary, deprecatedTrades],
  );
  const isVocabularyTrade = (t) => knownTradeKeys.has(rosterKey(t));

  // Surfaced so the vocabulary earns its next entries: an admin who sees five
  // rows off the list can say which of them should be on it.
  const offVocabularyCount = visibleAssignments.filter(
    (a) => !isVocabularyTrade(a.trade),
  ).length;

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated && projectId) {
      fetchProject();
    }
  }, [isAuthenticated, projectId]);

  // NON-FATAL. A failed vocabulary fetch leaves the picker empty, and the
  // "add a trade not on the list" step still works -- an admin standing on a
  // site at 6am must not be stopped from adding a crew because a list did not
  // load. The roster itself is what matters and it has its own cache.
  useEffect(() => {
    if (!isAuthenticated) return;
    let alive = true;
    tradesAPI.getVocabulary()
      .then((v) => {
        if (!alive) return;
        setVocabulary(v.trades);
        setDeprecatedTrades(Object.keys(v.deprecated || {}));
      })
      .catch(() => { /* picker stays empty; custom entry still reachable */ });
    return () => { alive = false; };
  }, [isAuthenticated]);

  const fetchProject = async () => {
    setLoading(true);
    // The project list/detail screens already write every project through
    // cacheProject() — read it back here instead of blanking out offline.
    const r = await settleFetch(() => projectsAPI.getById(projectId));
    let data = r.data;
    if (r.status !== 'ok') {
      console.error('Failed to fetch project:', r.error);
      data = await readCachedProject(projectId);
    }
    setFetchState(r.status);

    if (data) {
      setProject(data);
      const rows = Array.isArray(data.trade_assignments)
        ? data.trade_assignments
        : [];
      setAssignments(
        rows
          .filter(
            (r2) => r2 && typeof r2 === 'object' && r2.trade && r2.company
          )
          .map((r2) => ({
            trade: String(r2.trade).trim(),
            company: String(r2.company).trim(),
            // Stable server-minted row id. Carried through load AND save so
            // a round-trip never strips it. The server owns the value and
            // re-derives it on every PUT — this is a passthrough, not a
            // claim the client can make.
            id: r2.id ? String(r2.id) : '',
            // Soft-delete marker. Inactive rows stay in the payload (they
            // are never hard-deleted) but are hidden from this list and
            // from every check-in dropdown.
            status: String(r2.status || '').trim().toLowerCase(),
          }))
      );
      setDirty(false);
    }
    setLoading(false);
  };

  const samePair = (a, t, c) =>
    a.trade.trim().toLowerCase() === t.trim().toLowerCase() &&
    a.company.trim().toLowerCase() === c.trim().toLowerCase();

  const addAssignment = () => {
    const t = newTrade.trim();
    const c = newCompany.trim();
    if (!t || !c) {
      toast.warning('Required', 'Enter both trade and company');
      return;
    }
    const dup = assignments.some(
      (a) => a.status !== 'inactive' && samePair(a, t, c)
    );
    if (dup) {
      toast.info('Already added', `${t} — ${c} is already in the list`);
      return;
    }
    // The pair may already exist as a soft-deleted row. Reactivate that row
    // so its id (and everything referencing it) survives, instead of
    // appending a second row for the same pair.
    const wasRemoved = assignments.some(
      (a) => a.status === 'inactive' && samePair(a, t, c)
    );
    if (wasRemoved) {
      setAssignments(
        assignments.map((a) =>
          a.status === 'inactive' && samePair(a, t, c)
            ? { ...a, status: '' }
            : a
        )
      );
    } else {
      setAssignments([...assignments, { trade: t, company: c, id: '', status: '' }]);
    }
    setDirty(true);
    setNewTrade('');
    setNewCompany('');
    // Back to the list. A custom entry is a deliberate act each time, not a
    // mode the screen quietly stays in for the next row.
    setCustomMode(false);
  };

  // Removal is a SOFT delete: the row stays in the payload marked inactive.
  // Hard-deleting it would erase the roster entry that past check-ins,
  // logbooks and reports were recorded against.
  const removeAssignment = (row) => {
    setAssignments(
      assignments.map((a) =>
        a === row ? { ...a, status: 'inactive' } : a
      )
    );
    setDirty(true);
  };

  const pickSuggestion = (trade) => {
    setNewTrade(trade);
    setShowSuggest(false);
    setCustomMode(false);
  };

  const save = async () => {
    setSaving(true);
    try {
      const cleaned = assignments
        .map((a) => {
          const row = {
            trade: String(a.trade || '').trim(),
            company: String(a.company || '').trim(),
          };
          // Carry the id back so the server can match this row to its
          // stored twin. The server still re-derives the id itself — a
          // client-supplied id is never trusted.
          if (a.id) row.id = String(a.id);
          // Soft-deleted rows are SENT, marked inactive — that is what
          // records the removal. Omitting them would leave the removal to
          // the server's carry-forward and lose the explicit intent.
          if (a.status === 'inactive') row.status = 'inactive';
          return row;
        })
        .filter((a) => a.trade && a.company);
      await projectsAPI.update(projectId, { trade_assignments: cleaned });
      toast.success('Saved', 'Subcontractor roster updated');
      setDirty(false);
    } catch (err) {
      console.error('Failed to save:', err);
      // NOT queued and NOT saved — say so plainly rather than implying it stuck.
      if (isOfflineError(err)) {
        setFetchState('offline');
        toast.error('Not saved', 'You are offline. The roster was NOT saved — reconnect and save again.');
      } else {
        toast.error('Error', err.response?.data?.detail || 'Could not save');
      }
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <View style={s.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  if (!isAdmin) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <View style={s.header}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.back()}
            />
            <HeaderBrand />
          </View>
          <GlassCard style={s.accessDeniedCard}>
            <ShieldAlert size={56} strokeWidth={1} color={colors.status.error} />
            <Text style={s.accessDeniedTitle}>Admin Access Required</Text>
            <Text style={s.accessDeniedDesc}>
              Only administrators can edit a project's subcontractor roster.
            </Text>
          </GlassCard>
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
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        >
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>PROJECT SETTINGS</Text>
            <Text style={s.titleText}>Check-in Trades</Text>
            {project?.name && (
              <Text style={s.subtitleText}>{project.name}</Text>
            )}
          </View>

          {readOnly && (
            <>
              <OfflineNotice
                mode={fetchState}
                cachedCount={project ? 1 : 0}
                detail={
                  project
                    ? 'Showing the saved copy of this project. The roster is read-only until you reconnect — saving needs a connection and nothing is queued.'
                    : 'This project has no saved copy on this device. Reconnect to load its roster — this is NOT a statement that no subcontractors are configured.'
                }
              />
              <GlassButton
                title="Retry"
                icon={<RotateCw size={16} strokeWidth={1.5} color={colors.text.primary} />}
                onPress={fetchProject}
                style={s.retryBtn}
              />
            </>
          )}

          <GlassCard style={s.infoCard}>
            <HardHat size={24} strokeWidth={1.5} color={colors.text.primary} />
            <View style={s.infoTextWrap}>
              <Text style={s.infoTitle}>Subcontractor roster</Text>
              <Text style={s.infoDesc}>
                Pair each trade with the specific company doing that trade on
                this project (e.g. HVAC → Air Star, Framing → ODD). Workers
                tapping the NFC tag will pick one entry from the dropdown;
                both their trade and company auto-fill. Custom entries are
                rejected.
              </Text>
            </View>
          </GlassCard>

          <GlassCard style={s.card}>
            <Text style={s.sectionLabel}>ADD AN ASSIGNMENT</Text>

            <View style={s.addGroup}>
              <View style={s.addField}>
                <View style={s.addLabelRow}>
                  <HardHat size={14} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.addLabel}>TRADE</Text>
                </View>

                {/*
                  A PICKER, NOT A TEXT BOX. The control here used to be a plain
                  TextInput with a filtered suggestion list that merely filled
                  it in, so anything an admin typed was stored. That is how
                  "Framers" reached production while a twenty-entry list sat in
                  this same file validating nothing.
                */}
                {customMode ? (
                  <>
                    <TextInput
                      style={s.input}
                      value={newTrade}
                      onChangeText={setNewTrade}
                      placeholder="Trade not on the list"
                      placeholderTextColor={colors.text.subtle}
                      autoCapitalize="words"
                      autoFocus
                    />
                    {/*
                      SAID PLAINLY, because the whole point of the explicit step
                      is that the admin knows what he is choosing. The stored
                      string is a plain English trade either way — no marker, no
                      prefix — so the DOB record, the report and the PDF are
                      byte-identical whichever path produced the row. Only
                      trade_source differs, and the server derives that.
                    */}
                    <Text style={s.customNote}>
                      This trade is not on the standard list. It will be saved
                      exactly as typed and flagged as a custom trade.
                    </Text>
                    <Pressable onPress={() => { setCustomMode(false); setNewTrade(''); }}>
                      <Text style={s.customToggle}>Choose from the list instead</Text>
                    </Pressable>
                  </>
                ) : (
                  <>
                    <Pressable
                      style={s.input}
                      onPress={() => setShowSuggest((v) => !v)}
                    >
                      <Text style={newTrade ? s.pickerValue : s.pickerPlaceholder}>
                        {newTrade || 'Select a trade'}
                      </Text>
                    </Pressable>
                    {/*
                      A CUSTOM VALUE SHOWS BACK AS CHOSEN. Reopening a row whose
                      trade is off-vocabulary must not blank the field — that
                      would turn "we do not recognise this" into "you never
                      entered anything".
                    */}
                    {newTrade && !isVocabularyTrade(newTrade) && (
                      <Text style={s.customNote}>Custom trade — not on the standard list.</Text>
                    )}
                    {showSuggest && (
                      <View style={s.suggestBox}>
                        <ScrollView
                          style={{ maxHeight: 220 }}
                          keyboardShouldPersistTaps="handled"
                        >
                          {vocabulary.map((t) => (
                            <Pressable
                              key={t}
                              style={({ pressed }) => [
                                s.suggestItem,
                                pressed && { opacity: 0.7 },
                              ]}
                              onPress={() => pickSuggestion(t)}
                            >
                              <Text style={s.suggestItemText}>{t}</Text>
                            </Pressable>
                          ))}
                          {/*
                            THE EXPLICIT STEP. One tap away, and deliberately at
                            the bottom of the list rather than beside the field:
                            an admin reaches it by looking for it, not by
                            mistyping. A fixed list always lags a live jobsite,
                            so removing this escape hatch would push every
                            off-list crew to "My company isn't listed" at the
                            gate and land the work on the CP.
                          */}
                          <Pressable
                            style={({ pressed }) => [
                              s.suggestItem,
                              s.customItem,
                              pressed && { opacity: 0.7 },
                            ]}
                            onPress={() => { setCustomMode(true); setShowSuggest(false); setNewTrade(''); }}
                          >
                            <Plus size={13} strokeWidth={1.5} color={colors.text.muted} />
                            <Text style={s.customItemText}>Add a trade not on the list</Text>
                          </Pressable>
                        </ScrollView>
                      </View>
                    )}
                  </>
                )}
              </View>

              <View style={s.addField}>
                <View style={s.addLabelRow}>
                  <Briefcase size={14} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.addLabel}>COMPANY</Text>
                </View>
                <TextInput
                  style={s.input}
                  value={newCompany}
                  onChangeText={setNewCompany}
                  placeholder="e.g. Air Star"
                  placeholderTextColor={colors.text.subtle}
                  onSubmitEditing={addAssignment}
                  returnKeyType="done"
                  autoCapitalize="words"
                />
              </View>
            </View>

            <Pressable
              style={({ pressed }) => [
                s.addBtn,
                pressed && { opacity: 0.8 },
                readOnly && s.addBtnDisabled,
              ]}
              onPress={addAssignment}
              disabled={readOnly}
            >
              <Plus size={18} strokeWidth={2} color="#fff" />
              <Text style={s.addBtnText}>Add Assignment</Text>
            </Pressable>
            {readOnly && (
              <Text style={s.offlineHint}>
                Editing needs a connection — the roster is stored on the server.
              </Text>
            )}
          </GlassCard>

          <GlassCard style={s.card}>
            <Text style={s.sectionLabel}>
              ROSTER ({visibleAssignments.length})
            </Text>

            {/*
              WHAT IS OFF THE LIST, counted. Not a warning and not an error --
              a custom trade is a legitimate answer to a jobsite the vocabulary
              has not caught up with. It is surfaced so the vocabulary can earn
              its next entries: an admin who can see which rows are off the list
              is the one who can say which of them belong on it.
            */}
            {offVocabularyCount > 0 && (
              <Text style={s.offVocabNote}>
                {offVocabularyCount === 1
                  ? '1 trade on this roster is not on the standard list.'
                  : `${offVocabularyCount} trades on this roster are not on the standard list.`}
              </Text>
            )}

            {visibleAssignments.length === 0 && readOnly ? (
              // A failed read is not "nobody is configured" — that claim would
              // send an admin re-entering a roster the server already has.
              <View style={s.emptyState}>
                <Text style={s.emptyText}>Roster unavailable offline.</Text>
                <Text style={s.emptySubtext}>
                  Reconnect to see the trades configured for this project.
                </Text>
              </View>
            ) : visibleAssignments.length === 0 ? (
              <View style={s.emptyState}>
                <Text style={s.emptyText}>No subcontractors added yet.</Text>
                <Text style={s.emptySubtext}>
                  Workers will not be able to check in until at least one
                  trade/company pair is configured.
                </Text>
              </View>
            ) : (
              <View style={s.rosterList}>
                {visibleAssignments.map((a, idx) => (
                  <View key={a.id || `${a.trade}|${a.company}|${idx}`} style={s.rosterRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={s.rosterTrade}>{a.trade}</Text>
                      <Text style={s.rosterCompany}>{a.company}</Text>
                    </View>
                    <Pressable
                      onPress={() => removeAssignment(a)}
                      style={s.rosterRemove}
                      hitSlop={10}
                    >
                      <X size={18} strokeWidth={2} color={colors.text.muted} />
                    </Pressable>
                  </View>
                ))}
              </View>
            )}
          </GlassCard>

          <GlassButton
            title={
              saving
                ? 'Saving…'
                : readOnly
                  ? 'Saving needs a connection'
                  : dirty
                    ? 'Save Changes'
                    : 'Saved'
            }
            icon={
              !saving && dirty && !readOnly ? (
                <Save size={18} strokeWidth={1.5} color={colors.text.primary} />
              ) : null
            }
            onPress={save}
            loading={saving}
            disabled={saving || !dirty || readOnly}
            style={s.saveBtn}
          />
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: { flex: 1 },
    loadingContainer: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
    },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: withAlpha('#ffffff', 0.08),
    },
    headerLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
    },
    scrollView: { flex: 1 },
    scrollContent: {
      padding: spacing.lg,
      paddingBottom: 120,
    },
    titleSection: { marginBottom: spacing.xl },
    titleLabel: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.sm,
    },
    titleText: {
      fontSize: 38,
      fontWeight: '200',
      color: colors.text.primary,
      letterSpacing: -1,
    },
    subtitleText: {
      fontSize: 14,
      color: colors.text.muted,
      marginTop: spacing.xs,
    },
    infoCard: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: spacing.md,
      padding: spacing.lg,
      marginBottom: spacing.lg,
    },
    infoTextWrap: { flex: 1 },
    infoTitle: {
      fontSize: 15,
      fontWeight: '500',
      color: colors.text.primary,
      marginBottom: spacing.xs,
    },
    infoDesc: {
      fontSize: 13,
      color: colors.text.muted,
      lineHeight: 20,
    },
    card: {
      padding: spacing.lg,
      marginBottom: spacing.lg,
    },
    sectionLabel: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.md,
    },
    addGroup: {
      gap: spacing.md,
      marginBottom: spacing.md,
    },
    addField: {
      gap: spacing.xs,
    },
    addLabelRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
    },
    addLabel: {
      ...typography.label,
      fontSize: 11,
      color: colors.text.muted,
    },
    input: {
      backgroundColor: withAlpha('#ffffff', 0.05),
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.md,
      color: colors.text.primary,
      fontSize: 15,
    },
    suggestBox: {
      marginTop: spacing.xs,
      backgroundColor: isDark ? '#1a1f2e' : '#ffffff',
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
      overflow: 'hidden',
    },
    suggestItem: {
      paddingVertical: spacing.sm + 2,
      paddingHorizontal: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: colors.border?.subtle || withAlpha('#ffffff', 0.05),
    },
    suggestItemText: {
      fontSize: 14,
      color: colors.text.primary,
    },
    // The picker's closed state reuses `input` for its box, so these only
    // carry the text: a chosen value reads like typed text, a placeholder
    // reads like a placeholder.
    pickerValue: {
      color: colors.text.primary,
      fontSize: 15,
    },
    pickerPlaceholder: {
      color: colors.text.subtle,
      fontSize: 15,
    },
    // A custom trade is a legitimate answer, not an error — muted, never a
    // warning colour. Saying it plainly is the point of the explicit step.
    customNote: {
      marginTop: spacing.xs,
      fontSize: 12,
      lineHeight: 17,
      color: colors.text.muted,
    },
    customToggle: {
      marginTop: spacing.xs,
      fontSize: 13,
      color: colors.text.secondary || colors.text.muted,
      textDecorationLine: 'underline',
    },
    customItem: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      borderBottomWidth: 0,
    },
    customItemText: {
      fontSize: 14,
      color: colors.text.muted,
    },
    offVocabNote: {
      marginBottom: spacing.sm,
      fontSize: 12,
      lineHeight: 17,
      color: colors.text.muted,
    },
    addBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: spacing.xs,
      backgroundColor: '#3b82f6',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderRadius: borderRadius.lg,
    },
    addBtnText: {
      color: '#fff',
      fontSize: 14,
      fontWeight: '600',
    },
    addBtnDisabled: {
      opacity: 0.4,
    },
    offlineHint: {
      fontSize: 12,
      color: colors.text.subtle,
      marginTop: spacing.sm,
    },
    retryBtn: {
      alignSelf: 'flex-start',
      marginBottom: spacing.lg,
    },
    emptyState: {
      paddingVertical: spacing.lg,
      alignItems: 'center',
      gap: spacing.xs,
    },
    emptyText: {
      fontSize: 14,
      color: colors.text.muted,
    },
    emptySubtext: {
      fontSize: 12,
      color: colors.text.subtle,
      textAlign: 'center',
      maxWidth: 320,
    },
    rosterList: {
      gap: spacing.sm,
    },
    rosterRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
      backgroundColor: withAlpha('#ffffff', 0.04),
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      padding: spacing.md,
    },
    rosterTrade: {
      fontSize: 15,
      fontWeight: '500',
      color: colors.text.primary,
    },
    rosterCompany: {
      fontSize: 13,
      color: colors.text.muted,
      marginTop: 2,
    },
    rosterRemove: {
      padding: spacing.xs,
    },
    saveBtn: {
      marginTop: spacing.md,
    },
    accessDeniedCard: {
      alignItems: 'center',
      paddingVertical: spacing.xxl,
      gap: spacing.md,
      margin: spacing.lg,
    },
    accessDeniedTitle: {
      fontSize: 22,
      fontWeight: '500',
      color: colors.text.primary,
      marginTop: spacing.md,
    },
    accessDeniedDesc: {
      fontSize: 14,
      color: colors.text.muted,
      textAlign: 'center',
      maxWidth: 300,
      lineHeight: 22,
    },
  });
}
