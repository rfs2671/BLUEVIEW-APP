import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator } from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft, Shield, CheckCircle, Save, Calendar } from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import LogbookLockBar from '../../src/components/LogbookLockBar';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI } from '../../src/utils/api';
import { draftKey, readDraft, writeDraft, setDraftBackendId, markPending, clearPending, markFinalized } from '../../src/utils/logbookDrafts';
import { recordSignatureEvent } from '../../src/utils/signatureAudit';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { useTheme } from '../../src/context/ThemeContext';

const LOG_TYPE = 'ssc_daily_safety_log';

const WEATHER_OPTIONS = ['Sunny', 'Cloudy', 'Rainy', 'Windy', 'Snow', 'Fog', 'Stormy'];

export default function SSCDailySafetyLog() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  // The end-of-day Submit & Sign outlives handleSave's own `saving` window (it
  // finalizes afterwards), so it carries its own busy flag — which also blocks
  // a double-tap from double-finalizing.
  const [signing, setSigning] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);
  // Tier 1 (1)b: true when the loaded log is finalized (is_locked) — the form
  // renders read-only and only the Amend path can change anything.
  const [locked, setLocked] = useState(false);

  // SSC/SSM signature state — local to this logbook so a cached
  // personal CP signature from useCpProfile doesn't pre-lock the pad.
  // The pad opens empty on every new log; admin can type + draw from
  // scratch. On load we seed only from the existing logbook document,
  // never from the user-profile cache.
  const [cpName, setCpName] = useState('');
  const [cpSignature, setCpSignature] = useState(null);

  // Form fields
  const [projectAddress, setProjectAddress] = useState('');
  const [sspNumber, setSspNumber] = useState('');
  const [weather, setWeather] = useState('');
  const [siteConditions, setSiteConditions] = useState('');
  const [safetyViolations, setSafetyViolations] = useState('');
  const [correctiveActions, setCorrectiveActions] = useState('');
  const [incidentsReported, setIncidentsReported] = useState(false);
  const [incidentDetails, setIncidentDetails] = useState('');
  const [workersOnSiteCount, setWorkersOnSiteCount] = useState('');
  const [safetyMeetingsHeld, setSafetyMeetingsHeld] = useState(false);
  const [fireProtectionInPlace, setFireProtectionInPlace] = useState(false);
  const [housekeepingSatisfactory, setHousekeepingSatisfactory] = useState(false);
  const [ppeCompliance, setPpeCompliance] = useState(false);

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  // Phase A — autosave every field change to the LOCAL draft (AsyncStorage).
  // Debounced so typing doesn't thrash storage; makes no server call. The cp
  // fields come from this logbook's LOCAL state (never a profile cache), and
  // `status` is intentionally omitted so an autosave never downgrades a
  // submitted log back to draft.
  useEffect(() => {
    if (loading) return undefined;
    const t = setTimeout(() => {
      writeDraft(
        draftKey({ projectId, logType: LOG_TYPE, date }),
        {
          data: {
            project_address: projectAddress,
            ssp_number: sspNumber,
            weather,
            site_conditions: siteConditions,
            safety_violations_observed: safetyViolations,
            corrective_actions_taken: correctiveActions,
            incidents_reported: incidentsReported,
            incident_details: incidentDetails,
            workers_on_site_count: workersOnSiteCount,
            safety_meetings_held: safetyMeetingsHeld,
            fire_protection_in_place: fireProtectionInPlace,
            housekeeping_satisfactory: housekeepingSatisfactory,
            ppe_compliance: ppeCompliance,
          },
          cp_signature: cpSignature,
          cp_name: cpName,
        },
      ).catch(() => {});
    }, 800);
    return () => clearTimeout(t);
  }, [
    loading, projectId, date, projectAddress, sspNumber, weather, siteConditions,
    safetyViolations, correctiveActions, incidentsReported, incidentDetails,
    workersOnSiteCount, safetyMeetingsHeld, fireProtectionInPlace,
    housekeepingSatisfactory, ppeCompliance, cpSignature, cpName,
  ]);

  const fetchData = async () => {
    setLoading(true);
    try {
      // Phase A — local-first: read the on-device draft before touching the
      // network. If one exists we hydrate purely from it (project prefill is
      // skipped) so an offline SSC/SSM reopens to the same in-progress log.
      const key = draftKey({ projectId, logType: LOG_TYPE, date });
      const draft = await readDraft(key);
      if (draft) {
        // Tier 1 (1)b: a draft marked finalized locks the form read-only.
        if (draft.finalized) {
          setLocked(true);
          markFinalized(key);  // lock the offline draft too (mirrors the backend 423)
        }
        setExistingLogId(draft.backend_id);
        const d = draft.data || {};
        if (d.project_address) setProjectAddress(d.project_address);
        if (d.ssp_number) setSspNumber(d.ssp_number);
        if (d.weather) setWeather(d.weather);
        if (d.site_conditions) setSiteConditions(d.site_conditions);
        if (d.safety_violations_observed) setSafetyViolations(d.safety_violations_observed);
        if (d.corrective_actions_taken) setCorrectiveActions(d.corrective_actions_taken);
        if (d.incidents_reported != null) setIncidentsReported(d.incidents_reported);
        if (d.incident_details) setIncidentDetails(d.incident_details);
        if (d.workers_on_site_count) setWorkersOnSiteCount(d.workers_on_site_count);
        if (d.safety_meetings_held != null) setSafetyMeetingsHeld(d.safety_meetings_held);
        if (d.fire_protection_in_place != null) setFireProtectionInPlace(d.fire_protection_in_place);
        if (d.housekeeping_satisfactory != null) setHousekeepingSatisfactory(d.housekeeping_satisfactory);
        if (d.ppe_compliance != null) setPpeCompliance(d.ppe_compliance);
        // Seed the local cp state from the per-log draft only (never a profile cache).
        if (draft.cp_signature) setCpSignature(draft.cp_signature);
        if (draft.cp_name) setCpName(draft.cp_name);
        setLoading(false);
        return;
      }

      const [projectData, existingLogs] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        logbooksAPI.getByProject(projectId, LOG_TYPE, date).catch(() => []),
      ]);

      const fullAddress = projectData?.address || projectData?.location || '';
      setProjectAddress(fullAddress);
      if (projectData?.ssp_number) setSspNumber(projectData.ssp_number);

      // Prefer the EDITABLE (non-locked) doc — an amendment child — over a
      // locked original that shares (project, type, date).
      const arr = Array.isArray(existingLogs) ? existingLogs : [];
      const existing = arr.find(l => !l.is_locked) || arr[0] || null;
      if (existing) {
        if (existing.is_locked) {
          setLocked(true);
          markFinalized(key);  // lock the offline draft too (mirrors the backend 423)
        }
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (d.project_address) setProjectAddress(d.project_address);
        if (d.ssp_number) setSspNumber(d.ssp_number);
        if (d.weather) setWeather(d.weather);
        if (d.site_conditions) setSiteConditions(d.site_conditions);
        if (d.safety_violations_observed) setSafetyViolations(d.safety_violations_observed);
        if (d.corrective_actions_taken) setCorrectiveActions(d.corrective_actions_taken);
        if (d.incidents_reported != null) setIncidentsReported(d.incidents_reported);
        if (d.incident_details) setIncidentDetails(d.incident_details);
        if (d.workers_on_site_count) setWorkersOnSiteCount(d.workers_on_site_count);
        if (d.safety_meetings_held != null) setSafetyMeetingsHeld(d.safety_meetings_held);
        if (d.fire_protection_in_place != null) setFireProtectionInPlace(d.fire_protection_in_place);
        if (d.housekeeping_satisfactory != null) setHousekeepingSatisfactory(d.housekeeping_satisfactory);
        if (d.ppe_compliance != null) setPpeCompliance(d.ppe_compliance);
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (submitStatus = 'draft') => {
    setSaving(true);
    const key = draftKey({ projectId, logType: LOG_TYPE, date });
    try {
      const data = {
        project_address: projectAddress,
        ssp_number: sspNumber,
        weather,
        site_conditions: siteConditions,
        safety_violations_observed: safetyViolations,
        corrective_actions_taken: correctiveActions,
        incidents_reported: incidentsReported,
        incident_details: incidentDetails,
        workers_on_site_count: workersOnSiteCount,
        safety_meetings_held: safetyMeetingsHeld,
        fire_protection_in_place: fireProtectionInPlace,
        housekeeping_satisfactory: housekeepingSatisfactory,
        ppe_compliance: ppeCompliance,
      };
      const payload = {
        project_id: projectId,
        log_type: LOG_TYPE,
        date,
        data,
        cp_signature: cpSignature,
        cp_name: cpName,
        status: submitStatus,
      };

      // Phase A — write the LOCAL draft first. Source of truth, needs no network,
      // so an offline SSC/SSM completes the log without the "could not save" failure.
      await writeDraft(key, { data, cp_signature: cpSignature, cp_name: cpName, status: submitStatus });

      // Best-effort server push. Offline this throws and is swallowed — the key
      // is recorded in the pending-push list for the Phase B reconnect flush.
      let savedId = existingLogId;
      try {
        if (existingLogId) {
          await logbooksAPI.update(existingLogId, {
            data: payload.data,
            cp_signature: cpSignature,
            cp_name: cpName,
            status: submitStatus,
          });
        } else {
          const created = await logbooksAPI.create(payload);
          savedId = created.id || created._id;
          setExistingLogId(savedId);
        }
        await setDraftBackendId(key, savedId);
        await clearPending(key);
      } catch (pushErr) {
        await markPending(key);
        console.warn('Logbook server push deferred (will sync on reconnect):', pushErr?.message);
      }

      if (submitStatus === 'submitted' && cpSignature && savedId) {
        recordSignatureEvent({
          documentType: 'logbook',
          documentId: savedId,
          eventType: 'ssc_sign',
          signerName: cpName,
          signerRole: user?.role || 'ssc',
          signatureData: cpSignature,
          contentSnapshot: {
            log_type: LOG_TYPE,
            date,
            project_id: projectId,
            data: payload.data,
            status: submitStatus,
          },
          user,
        }).catch(e => console.warn('Signature audit failed (non-blocking):', e?.message));
      }

      // DAILY NARRATIVE: the only 'submitted' caller is the end-of-day
      // Submit & Sign below, which still has to finalize + freeze AFTER this
      // returns. Announcing "submitted" (or leaving the screen) from here would
      // report success before the log is actually locked, so that path owns its
      // own toast and navigation. Save Draft is untouched.
      if (submitStatus !== 'submitted') {
        toast.success('Draft Saved', 'Draft saved');
      }
      // Hand back the server id so the caller can /finalize THIS document.
      // `null` = saved locally but not yet on the server (offline).
      return savedId || null;
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save safety log');
      // `undefined` (not null) = the save itself failed and has already been
      // reported — the caller must NOT freeze a log that was never written.
      return undefined;
    } finally {
      setSaving(false);
    }
  };

  /**
   * THE end-of-day action for this daily narrative log — one button, one freeze.
   *
   * Save Draft fills this log all day and never freezes it. There is deliberately
   * no separate "Submit" any more: a log that could be submitted repeatedly and
   * finalized separately can sit REQUIRED-but-unfrozen forever. This is the
   * single closing action, and its order is what makes it hold OFFLINE:
   *
   *   1. handleSave('submitted') — content + signature into the local draft
   *      first, server push best-effort (markPending on failure; draftSync
   *      drains it and re-applies /finalize on reconnect).
   *   2. server /finalize when the doc has an id — best-effort, never fatal.
   *   3. LOCAL freeze, unconditionally: an EOD sign with no signal must still be
   *      frozen on this device. It MUST come after (1) — writeDraft refuses
   *      content patches once a draft is finalized.
   *   4. flip the form read-only.
   */
  const handleSubmitAndSign = async () => {
    if (saving || signing) return;
    // Signed record: no signature, no submit.
    if (!cpSignature) {
      toast.warning('Signature required', 'Sign the log before submitting — this is a signed record.');
      return;
    }
    setSigning(true);
    try {
      const key = draftKey({ projectId, logType: LOG_TYPE, date });
      const savedId = await handleSave('submitted');
      if (savedId === undefined) return;  // save failed and already reported

      let serverLocked = false;
      if (savedId) {
        try {
          await logbooksAPI.finalize(savedId);
          serverLocked = true;
        } catch (finalizeErr) {
          // Offline / server refused. The local freeze below still stands and
          // the reconnect drain re-applies /finalize once the push lands.
          console.warn('Finalize deferred (will re-apply on reconnect):', finalizeErr?.message);
        }
      }

      await markFinalized(key);
      setLocked(true);

      toast.success(
        'Submitted & Signed',
        serverLocked
          ? 'This log is now locked. Corrections require an amendment.'
          : 'Signed and locked on this device. It will sync when you are back online.'
      );
      router.back();
    } finally {
      setSigning(false);
    }
  };

  const ToggleRow = ({ label, value, onToggle }) => (
    <View style={s.toggleRow}>
      <Text style={s.toggleLabel}>{label}</Text>
      <Pressable onPress={onToggle}>
        <View style={[s.toggleDot, value && s.toggleDotActive]} />
      </Pressable>
    </View>
  );

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

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <GlassButton
            variant="icon"
            icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={() => router.back()}
          />
          <Text style={s.headerTitle}>SSC/SSM Daily Safety Log</Text>
        </View>

        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Tier 1 (1)b: a finalized log renders read-only. pointerEvents 'none'
              makes EVERY field below non-interactive (no per-field editable flags
              to miss). Scrolling still works; the LockBar stays interactive. */}
          <View pointerEvents={locked ? 'none' : 'auto'}>
          {/* Date */}
          <GlassCard style={s.section}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
              <Calendar size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.sectionTitle}>
                {new Date(date).toLocaleDateString('en-US', {
                  weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
                })}
              </Text>
            </View>
          </GlassCard>

          {/* Project Info */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Project Information</Text>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Project Address</Text>
              <Text style={[s.input, { paddingVertical: spacing.sm }]}>{projectAddress || 'No address on file'}</Text>
            </View>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>SSP Number</Text>
              <Text style={[s.input, { paddingVertical: spacing.sm }]}>{sspNumber || 'N/A'}</Text>
            </View>
          </GlassCard>

          {/* Weather */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Weather Conditions</Text>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs }}>
              {WEATHER_OPTIONS.map((w) => (
                <Pressable
                  key={w}
                  onPress={() => setWeather(weather === w ? '' : w)}
                  style={[s.chip, weather === w && s.chipActive]}
                >
                  <Text style={[s.chipText, weather === w && s.chipTextActive]}>{w}</Text>
                </Pressable>
              ))}
            </View>
          </GlassCard>

          {/* Site Conditions */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Site Conditions</Text>
            <TextInput
              style={[s.input, s.textArea]}
              value={siteConditions}
              onChangeText={setSiteConditions}
              placeholder="Describe current site conditions..."
              placeholderTextColor={colors.text.subtle}
              multiline
              numberOfLines={4}
            />
          </GlassCard>

          {/* Safety Violations */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Safety Violations Observed</Text>
            <TextInput
              style={[s.input, s.textArea]}
              value={safetyViolations}
              onChangeText={setSafetyViolations}
              placeholder="Describe any safety violations observed..."
              placeholderTextColor={colors.text.subtle}
              multiline
              numberOfLines={4}
            />
          </GlassCard>

          {/* Corrective Actions */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Corrective Actions Taken</Text>
            <TextInput
              style={[s.input, s.textArea]}
              value={correctiveActions}
              onChangeText={setCorrectiveActions}
              placeholder="Describe corrective actions taken..."
              placeholderTextColor={colors.text.subtle}
              multiline
              numberOfLines={4}
            />
          </GlassCard>

          {/* Incidents */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Incidents</Text>
            <ToggleRow
              label="Incidents Reported"
              value={incidentsReported}
              onToggle={() => setIncidentsReported(!incidentsReported)}
            />
            {incidentsReported && (
              <TextInput
                style={[s.input, s.textArea, { marginTop: spacing.sm }]}
                value={incidentDetails}
                onChangeText={setIncidentDetails}
                placeholder="Provide incident details..."
                placeholderTextColor={colors.text.subtle}
                multiline
                numberOfLines={4}
              />
            )}
          </GlassCard>

          {/* Workforce & Compliance */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Workforce & Compliance</Text>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Workers on Site</Text>
              <TextInput
                style={s.input}
                value={workersOnSiteCount}
                onChangeText={setWorkersOnSiteCount}
                placeholder="0"
                placeholderTextColor={colors.text.subtle}
                keyboardType="numeric"
              />
            </View>
            <ToggleRow
              label="Safety Meetings Held"
              value={safetyMeetingsHeld}
              onToggle={() => setSafetyMeetingsHeld(!safetyMeetingsHeld)}
            />
            <ToggleRow
              label="Fire Protection in Place"
              value={fireProtectionInPlace}
              onToggle={() => setFireProtectionInPlace(!fireProtectionInPlace)}
            />
            <ToggleRow
              label="Housekeeping Satisfactory"
              value={housekeepingSatisfactory}
              onToggle={() => setHousekeepingSatisfactory(!housekeepingSatisfactory)}
            />
            <ToggleRow
              label="PPE Compliance"
              value={ppeCompliance}
              onToggle={() => setPpeCompliance(!ppeCompliance)}
            />
          </GlassCard>

          {/* SSC/SSM Signature */}
          <GlassCard style={s.section}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm }}>
              <Shield size={16} strokeWidth={1.5} color="#3b82f6" />
              <Text style={s.sectionTitle}>SSC/SSM Sign-Off</Text>
            </View>
            <SignaturePad
              title="SSC/SSM Signature"
              signerName={cpName}
              onNameChange={setCpName}
              existingSignature={cpSignature}
              onSignatureCapture={setCpSignature}
              autoLock={false}
            />
          </GlassCard>
          </View>

          {/* Actions — hidden when finalized; the LockBar handles amend.
              TWO actions only: fill it all day (Save Draft, never freezes) and
              close it once (Submit & Sign, freezes). There is no third
              "Submit" that leaves a REQUIRED daily log unfrozen. */}
          {!locked && (
          <View style={s.buttonColumn}>
            <GlassButton
              title={saving && !signing ? 'Saving...' : 'Save Draft'}
              icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => handleSave('draft')}
              loading={saving && !signing}
              style={{ width: '100%' }}
            />
            <GlassButton
              title={signing ? 'Submitting...' : 'Submit & Sign (End of Day)'}
              icon={<CheckCircle size={16} strokeWidth={1.5} color="#fff" />}
              onPress={handleSubmitAndSign}
              loading={signing}
              style={{ width: '100%', backgroundColor: semantic.verified, borderColor: semantic.verified }}
            />
            <Text style={s.signHint}>
              Signing closes the day: this log locks and corrections then require an amendment.
            </Text>
          </View>
          )}

          {/* DAILY NARRATIVE log: stays open and accumulating all day;
              intermediate saves do NOT freeze it. It freezes once, at the
              end-of-day Submit & Sign above — which is why canFinalize is
              false: that single button owns finalization, and a second
              "Finalize" here would be the same two-button trap. logType and the
              Amend path stay so a locked narrative log can still be amended. */}
          <LogbookLockBar
            logType={LOG_TYPE}
            locked={locked}
            logId={existingLogId}
            canFinalize={false}
            onFinalized={() => setLocked(true)}
            onAmended={fetchData}
          />
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: { flex: 1 },
    scrollContent: { padding: spacing.lg, paddingBottom: 120 },
    header: { flexDirection: 'row', alignItems: 'center', padding: spacing.lg, gap: spacing.md },
    headerTitle: { fontSize: 20, fontWeight: '700', color: colors.text.primary, flex: 1 },
    section: { marginBottom: spacing.md },
    sectionTitle: { ...typography.label, color: colors.text.muted, marginBottom: spacing.sm },
    inputGroup: { marginBottom: spacing.md },
    inputLabel: { ...typography.label, color: colors.text.muted, marginBottom: 4 },
    input: {
      backgroundColor: withAlpha('#ffffff', 0.05), borderRadius: borderRadius.md,
      padding: spacing.sm, color: colors.text.primary,
      borderWidth: 1, borderColor: withAlpha('#ffffff', 0.1),
    },
    textArea: { minHeight: 80, textAlignVertical: 'top' },
    toggleRow: {
      flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
      paddingVertical: spacing.sm,
    },
    toggleLabel: { color: colors.text.secondary, fontSize: 14 },
    toggleDot: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: colors.text.subtle },
    toggleDotActive: { backgroundColor: semantic.verified, borderColor: semantic.verified },
    // Stacked, not side-by-side: the end-of-day action is irreversible, so it
    // gets its own full-width row and cannot be mistaken for the save next to it.
    buttonColumn: { gap: spacing.sm, marginTop: spacing.lg },
    signHint: { fontSize: 12, color: colors.text.muted, textAlign: 'center', marginTop: spacing.xs },
    loadingContainer: { flex: 1, justifyContent: 'center', alignItems: 'center' },
    chip: {
      paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
      borderRadius: borderRadius.full, borderWidth: 1, borderColor: withAlpha('#ffffff', 0.1),
      backgroundColor: withAlpha('#ffffff', 0.04),
    },
    chipActive: { backgroundColor: 'rgba(59,130,246,0.2)', borderColor: 'rgba(59,130,246,0.5)' },
    chipText: { fontSize: 13, color: colors.text.muted },
    chipTextActive: { color: '#3b82f6', fontWeight: '600' },
  });
}
