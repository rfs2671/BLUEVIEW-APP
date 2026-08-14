import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft, BookOpen, Check, CheckCircle, Save, Users, Calendar,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import LogbookLockBar from '../../src/components/LogbookLockBar';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI } from '../../src/utils/api';
import { draftKey, readDraft, writeDraft, setDraftBackendId, markPending, clearPending, markFinalized } from '../../src/utils/logbookDrafts';
import { withGateSnapshot, reconcileRoster } from '../../src/utils/rosterReconcile';
import { freezeIfImmediate } from '../../src/utils/logbookTiming';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { useTheme } from '../../src/context/ThemeContext';

const TOPICS = {
  'PPE': [
    { key: 'hard_hats', label: 'Hard Hats' },
    { key: 'safety_boots', label: 'Safety Boots' },
    { key: 'safety_glasses', label: 'Safety Glasses' },
    { key: 'harness', label: 'Harness' },
    { key: 'gloves', label: 'Gloves' },
    { key: 'covid19', label: 'Covid-19' },
  ],
  'Fall Protection': [
    { key: 'ladder_safety', label: 'Ladder Safety' },
    { key: 'harness_fp', label: 'Harness' },
    { key: 'guard_rails', label: 'Guard Rails' },
    { key: 'slopes', label: 'Slopes' },
  ],
  'Hazards': [
    { key: 'tripping_hazards', label: 'Tripping Hazards' },
    { key: 'fire_hazards', label: 'Fire Hazards' },
    { key: 'egress', label: 'Egress' },
    { key: 'flammables', label: 'Flammables' },
  ],
  'Equipment': [
    { key: 'electric_tool_safety', label: 'Electric Tool Safety' },
    { key: 'scaffold_safety', label: 'Scaffold Safety' },
    { key: 'excavator', label: 'Excavator' },
    { key: 'generator', label: 'Generator' },
  ],
  'Public Safety': [
    { key: 'flags_man_regulations', label: 'Flags / Man Regulations' },
    { key: 'sidewalk', label: 'Side Walk' },
    { key: 'street_safety', label: 'Street Safety' },
    { key: 'adjacent_property', label: 'Adjacent Property' },
  ],
};

// Renders an ISO check-in timestamp as a short local clock time ("7:12 AM").
// Falls back to the raw string so a legacy non-ISO value still shows something
// rather than "Invalid Date" on a legal record.
const formatClock = (value) => {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
};

export default function ToolboxTalkLog() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const { cpName, setCpName, cpSignature, setCpSignature, autoSave } = useCpProfile();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);
  // Tier 1 (1)b: true when the loaded log is finalized (is_locked) — the form
  // renders read-only and only the Amend path can change anything.
  const [locked, setLocked] = useState(false);
  const [project, setProject] = useState(null);

  const [location, setLocation] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [typeOfWork, setTypeOfWork] = useState('');
  const [meetingTime, setMeetingTime] = useState(
    new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  );
  const [performedBy, setPerformedBy] = useState('');
  const [checkedTopics, setCheckedTopics] = useState({});
  const [attendees, setAttendees] = useState([]);

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  // Auto-fill Performed By from CP profile when available
  useEffect(() => {
    if (cpName && !performedBy) {
      setPerformedBy(cpName);
    }
  }, [cpName]);

  // Phase A — autosave every field change to the LOCAL draft (AsyncStorage).
  // Debounced so typing doesn't thrash storage; makes no server call. This is
  // what lets the CP fill with zero network and reopen to the same draft.
  // `status` is intentionally omitted so an autosave never downgrades a
  // submitted log back to draft.
  useEffect(() => {
    if (loading) return undefined;
    const t = setTimeout(() => {
      writeDraft(
        draftKey({ projectId, logType: 'toolbox_talk', date }),
        {
          data: {
            location,
            company_name: companyName,
            type_of_work: typeOfWork,
            meeting_time: meetingTime,
            performed_by: performedBy,
            checked_topics: checkedTopics,
            attendees,
          },
          cp_signature: cpSignature,
          cp_name: cpName,
        },
      ).catch(() => {});
    }, 800);
    return () => clearTimeout(t);
  }, [
    loading, projectId, date, location, companyName, typeOfWork, meetingTime,
    performedBy, checkedTopics, attendees, cpSignature, cpName,
  ]);

  // Toolbox had NO provenance marker of any kind before this — a hand-added
  // attendee was shaped identically to a gate-built one. gate_sourced +
  // gate_snapshot supply it. `signed` is the CP's present tick, which the gate
  // never sets, so a tick is proof the row is his.
  const TOOLBOX_GATE_FIELDS = ['name', 'title', 'company'];
  const TOOLBOX_ANSWER_FIELDS = ['signed'];

  /** Re-check a stored roster against today's check-ins. `fresh` null (offline)
   *  keeps everything — never delete a man because the server was unreachable. */
  const _reconcileAttendees = (stored, fresh) => {
    if (!Array.isArray(fresh)) return stored;
    const built = fresh
      .filter((c) => c && c.blocked !== true && c.source !== 'cert_block')
      .map((c) => withGateSnapshot({
        worker_id: c.worker_id,
        name: c.worker_name || '',
        title: c.trade || '',
        company: c.company || '',
        time: c.check_in_time || '',
        gate_confirmed: c.toolbox_talk_confirmed === true,
        gate_confirmed_at: c.toolbox_talk_confirmed_at || null,
        signed: false,
        signature: null,
      }, TOOLBOX_GATE_FIELDS));
    return reconcileRoster({
      stored,
      fresh: built,
      fields: TOOLBOX_GATE_FIELDS,
      answers: TOOLBOX_ANSWER_FIELDS,
    }).rows;
  };

  const fetchData = async () => {
    setLoading(true);
    try {
      // Phase A — local-first: read the on-device draft first. If a local copy
      // exists, hydrate from it and skip the server fetch + check-in
      // auto-populate entirely (works fully offline).
      const key = draftKey({ projectId, logType: 'toolbox_talk', date });
      const draft = await readDraft(key);
      if (draft) {
        // Tier 1 (1)b: a draft marked finalized locks the form read-only.
        if (draft.finalized) {
          setLocked(true);
          markFinalized(key);
        }
        setExistingLogId(draft.backend_id);
        const d = draft.data || {};
        if (d.location) setLocation(d.location);
        if (d.company_name) setCompanyName(d.company_name);
        if (d.type_of_work) setTypeOfWork(d.type_of_work);
        if (d.meeting_time) setMeetingTime(d.meeting_time);
        if (d.performed_by) setPerformedBy(d.performed_by);
        if (d.checked_topics) setCheckedTopics(d.checked_topics);
        // RE-CHECK AGAINST TODAY, even on the draft path. This early return
        // used to skip /checkins-today entirely. Best-effort: offline the
        // fetch fails and everything is kept, as before this change.
        if (d.attendees && d.attendees.length > 0) {
          const _fresh = await logbooksAPI
            .getCheckinsForDate(projectId, date).catch(() => null);
          setAttendees(_reconcileAttendees(d.attendees, _fresh));
        }
        if (draft.cp_signature) setCpSignature(draft.cp_signature);
        if (draft.cp_name) setCpName(draft.cp_name);
        setLoading(false);
        return;
      }

      const [projectData, checkins, existingLogs] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        logbooksAPI.getCheckinsForDate(projectId, date).catch(() => []),
        logbooksAPI.getByProject(projectId, 'toolbox_talk', date).catch(() => []),
      ]);

      if (projectData) {
        setProject(projectData);
        setLocation(projectData.address || projectData.location || '');
      }

      // ROSTER MODEL (counsel-approved) — the check-in list BUILDS the roster:
      // a worker present on site today is on the roster. That is a record of
      // presence, NOT a legal attestation. The CP's fresh, time-stamped
      // signature at the conclusion of the talk is the sole legal anchor
      // (NYC DOB §3301.12.3, OSHA 29 CFR 1926.21). Workers do not sign.
      const checkinList = Array.isArray(checkins) ? checkins : [];
      const autoAttendees = checkinList
        // Workers TURNED AWAY at the gate (cert block) never entered the site.
        // They exist in this response so the OSHA log can prove who lacked a
        // card — they must never appear on an ATTENDANCE roster.
        .filter((c) => c.blocked !== true && c.source !== 'cert_block')
        .map((c) => withGateSnapshot({
          worker_id: c.worker_id,
          // §3301.12.3 roster fields: name, title, company, time.
          name: c.worker_name || '',
          title: c.trade || '',
          company: c.company || '',
          time: c.check_in_time || '',
          // Optional gate confirmation ("Confirm attending toolbox talk"). A
          // worker who did NOT tap is still fully on the roster — this is a
          // courtesy marker, never a deficiency flag.
          gate_confirmed: c.toolbox_talk_confirmed === true,
          gate_confirmed_at: c.toolbox_talk_confirmed_at || null,
          // CP-tapped presence marker (see "Present" column) — not a signature.
          signed: false,
          // DELIBERATELY NULL. The worker's stored gate signature attests to the
          // §3301.11 site orientation captured once on day one; site/logbooks.jsx
          // renders any non-null `signature`/`worker_signature` under a heading
          // reading "Worker Signatures", so carrying it here would misrepresent
          // its provenance on a toolbox-talk record. Gate confirmation is
          // recorded as name + timestamp instead.
          signature: null,
        }, TOOLBOX_GATE_FIELDS));

      // Tier 1 (1)b: prefer the EDITABLE (non-locked) doc — an amendment child —
      // over a locked original that shares (project, type, date).
      const arr = Array.isArray(existingLogs) ? existingLogs : [];
      const existing = arr.find(l => !l.is_locked) || arr[0] || null;
      if (existing) {
        if (existing.is_locked) {
          setLocked(true);
          markFinalized(key);  // lock the offline draft too (mirrors the backend 423)
        }
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (d.location) setLocation(d.location);
        if (d.company_name) setCompanyName(d.company_name);
        if (d.type_of_work) setTypeOfWork(d.type_of_work);
        if (d.meeting_time) setMeetingTime(d.meeting_time);
        if (d.performed_by) setPerformedBy(d.performed_by);
        if (d.checked_topics) setCheckedTopics(d.checked_topics);
        if (d.attendees && d.attendees.length > 0) {
          setAttendees(_reconcileAttendees(d.attendees, checkinList));
        } else {
        setAttendees(autoAttendees);
          
        // Auto-fill company name from project or user
        if (projectData?.company) {
          setCompanyName(projectData.company);
        } else if (user?.company_name) {
          setCompanyName(user.company_name);
        } else if (user?.name) {
          setCompanyName(user.name.split(' ')[0]); // fallback
        }
      }
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      } else {
        setAttendees(autoAttendees);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const toggleTopic = (key) => {
    setCheckedTopics(prev => ({ ...prev, [key]: !prev[key] }));
  };

  // "Present" toggle — a CP-tapped boolean, NOT a worker signature. The stored
  // field stays `signed` so already-saved logs (and the record viewer in
  // site/logbooks.jsx) keep reading the same key.
  const toggleAttendeePresent = (index) => {
    setAttendees(prev => prev.map((a, i) =>
      i === index ? { ...a, signed: !a.signed } : a
    ));
  };

  const addAttendee = () => {
    setAttendees(prev => [...prev, {
      worker_id: null,
      name: '',
      title: '',
      company: '',
      time: '',
      gate_confirmed: false,
      gate_confirmed_at: null,
      signed: false,
      signature: null,
    }]);
  };

  const updateAttendee = (index, field, value) => {
    setAttendees(prev => prev.map((a, i) =>
      i === index ? { ...a, [field]: value } : a
    ));
  };

  const handleSave = async (submitStatus = 'draft') => {
    setSaving(true);
    const key = draftKey({ projectId, logType: 'toolbox_talk', date });
    const data = {
      location,
      company_name: companyName,
      type_of_work: typeOfWork,
      meeting_time: meetingTime,
      performed_by: performedBy,
      checked_topics: checkedTopics,
      attendees,
    };
    try {
      // Phase A — write the LOCAL draft first. Source of truth, needs no network,
      // so an offline CP completes the log without the "could not save" failure.
      await writeDraft(key, { data, cp_signature: cpSignature, cp_name: cpName, status: submitStatus });

      // Best-effort server push. Offline this throws and is swallowed — the key
      // is recorded in the pending-push list for the Phase B reconnect flush.
      // NOTE: a submit made offline has no server id yet, so the signature-audit
      // record below is skipped until the draft syncs (a Phase B reconcile item).
      let savedId = existingLogId;
      let pushOk = true;
      try {
        if (existingLogId) {
          await logbooksAPI.update(existingLogId, {
            data, cp_signature: cpSignature, cp_name: cpName, status: submitStatus,
          });
        } else {
          const created = await logbooksAPI.create({
            project_id: projectId, log_type: 'toolbox_talk', date,
            data, cp_signature: cpSignature, cp_name: cpName, status: submitStatus,
          });
          savedId = created.id || created._id;
          setExistingLogId(savedId);
        }
        await setDraftBackendId(key, savedId);
        await clearPending(key);
      } catch (pushErr) {
        pushOk = false;
        await markPending(key);
        console.warn('Logbook server push deferred (will sync on reconnect):', pushErr?.message);
      }

      // FREEZE ON SIGN — toolbox_talk is an IMMEDIATE log: the SIGNATURE IS THE
      // FREEZE. "Submit & Sign" finalizes the record in one action (there is no
      // separate Finalize step, and it is never reopened). This runs after the
      // local writeDraft above — so the frozen draft holds the SIGNED content —
      // and after the push attempt on BOTH paths, because the talk is signed at
      // the muster point with no signal: the freeze must not need the server. A
      // later talk that day is a NEW log; corrections go through Amend.
      if (submitStatus === 'submitted') {
        await freezeIfImmediate(key, 'toolbox_talk');
        setLocked(true);
      }

      await autoSave(cpName, cpSignature).catch(() => {});

      if (submitStatus === 'submitted' && cpSignature && savedId) {
        const { recordSignatureEvent } = require('../../src/utils/signatureAudit');
        recordSignatureEvent({
          documentType: 'logbook', documentId: savedId, eventType: 'cp_sign',
          signerName: cpName, signerRole: user?.role || 'cp',
          signatureData: cpSignature,
          contentSnapshot: { log_type: 'toolbox_talk', date, project_id: projectId, data, status: submitStatus },
          user,
        }).catch(e => console.warn('Signature audit failed (non-blocking):', e?.message));
      }

      toast.success(
        submitStatus === 'submitted' ? 'Signed & Locked' : 'Saved',
        submitStatus !== 'submitted'
          ? 'Tool Box Talk saved'
          : pushOk
            ? 'Signed — this log is now locked. Corrections require an amendment.'
            : 'Signed — locked on this device and will sync when you are back online.');
      if (submitStatus === 'submitted') router.back();
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save log');
    } finally {
      setSaving(false);
    }
  };

  const checkedCount = Object.values(checkedTopics).filter(Boolean).length;
  const presentCount = attendees.filter(a => a.signed).length;

  if (loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <View style={s.loadingCenter}>
            <ActivityIndicator size="large" color={colors.text.primary} />
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
              onPress={() => router.push('/logbooks')}
            />
            <View>
              <Text style={s.headerTitle}>Tool Box Talk</Text>
              <Text style={s.headerSub}>OSHA — Weekly Safety Meeting</Text>
            </View>
          </View>
          <View style={s.statRow}>
            <View style={s.statBadge}>
              <Text style={s.statText}>{checkedCount} topics</Text>
            </View>
            <View style={s.statBadge}>
              <Text style={s.statText}>{presentCount} present</Text>
            </View>
          </View>
        </View>

        <ScrollView style={s.scrollView} contentContainerStyle={s.scrollContent} showsVerticalScrollIndicator={false}>

          {/* Tier 1 (1)b: a finalized log renders read-only. pointerEvents 'none'
              makes EVERY field below non-interactive (no per-field editable flags
              to miss). Scrolling still works; the LockBar stays interactive. */}
          <View pointerEvents={locked ? 'none' : 'auto'}>

          {/* Date */}
          <GlassCard style={s.dateCard}>
            <Calendar size={16} strokeWidth={1.5} color={colors.text.muted} />
            <Text style={s.dateText}>
              {new Date(date + 'T12:00:00').toLocaleDateString('en-US', {
                weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
              })}
            </Text>
          </GlassCard>

          {/* Header Info */}
          <GlassCard style={s.section}>
            <Text style={s.sectionHeader}>Meeting Information</Text>
            {[
              { label: 'Location', value: location, setter: setLocation },
              { label: 'Company Name', value: companyName, setter: setCompanyName },
              { label: 'Type of Work', value: typeOfWork, setter: setTypeOfWork },
              { label: 'Time', value: meetingTime, setter: setMeetingTime },
              { label: 'Performed By (CP)', value: performedBy, setter: setPerformedBy },
            ].map((f) => (
              <View key={f.label} style={s.fieldRow}>
                <Text style={s.fieldLabel}>{f.label}</Text>
                <TextInput
                  style={s.fieldInput}
                  value={f.value}
                  onChangeText={f.setter}
                  placeholder="—"
                  placeholderTextColor={colors.text.subtle}
                />
              </View>
            ))}
          </GlassCard>

          {/* Topics Grid */}
          <GlassCard style={s.section}>
            <Text style={s.sectionHeader}>Topics Covered</Text>
            <Text style={s.sectionSubtitle}>Check all topics discussed in this meeting</Text>
            {Object.entries(TOPICS).map(([category, items]) => (
              <View key={category} style={s.topicCategory}>
                <Text style={s.topicCategoryLabel}>{category}</Text>
                <View style={s.topicGrid}>
                  {items.map((item) => {
                    const isChecked = !!checkedTopics[item.key];
                    return (
                      <Pressable
                        key={item.key}
                        onPress={() => toggleTopic(item.key)}
                        style={[s.topicItem, isChecked && s.topicItemActive]}
                      >
                        <View style={[s.topicCheckbox, isChecked && s.topicCheckboxActive]}>
                          {isChecked && <Check size={12} strokeWidth={2.5} color="#fff" />}
                        </View>
                        <Text style={[s.topicLabel, isChecked && s.topicLabelActive]}>
                          {item.label}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            ))}
          </GlassCard>

          {/* Attendance Roster — §3301.12.3 name / title / company / time.
              The roster records WHO WAS PRESENT; the CP signature below is the
              attestation. No worker signature is captured or displayed here. */}
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <Users size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.sectionHeader}>Attendance Roster</Text>
              <Text style={s.attendeeCount}>{attendees.length} workers</Text>
            </View>
            <Text style={s.sectionSubtitle}>
              Roster auto-built from today's check-ins. The Competent Person's
              signature below is the required attestation — workers are not
              required to sign.
            </Text>

            {/* Table Header */}
            <View style={s.tableHeader}>
              <Text style={[s.tableHeaderText, { flex: 2 }]}>Name / Title</Text>
              <Text style={[s.tableHeaderText, { flex: 2 }]}>Company / Time In</Text>
              <Text style={[s.tableHeaderText, { flex: 1, textAlign: 'center' }]}>Present</Text>
            </View>

            {attendees.map((attendee, index) => {
              const timeIn = formatClock(attendee.time);
              const confirmedAt = formatClock(attendee.gate_confirmed_at || attendee.time);
              return (
              <View key={index} style={s.attendeeRow}>
                <View style={s.attendeeMain}>
                  <View style={s.attendeeLine}>
                    <TextInput
                      style={[s.attendeeInput, { flex: 2 }]}
                      value={attendee.name}
                      onChangeText={(v) => updateAttendee(index, 'name', v)}
                      placeholder="Name"
                      placeholderTextColor={colors.text.subtle}
                    />
                    <TextInput
                      style={[s.attendeeInput, { flex: 2 }]}
                      value={attendee.company}
                      onChangeText={(v) => updateAttendee(index, 'company', v)}
                      placeholder="Company"
                      placeholderTextColor={colors.text.subtle}
                    />
                  </View>
                  {/* Secondary line keeps title + check-in time on the record
                      without a fifth column crushing the phone layout. */}
                  <View style={s.attendeeLine}>
                    <TextInput
                      style={[s.attendeeMetaInput, { flex: 2 }]}
                      value={attendee.title || ''}
                      onChangeText={(v) => updateAttendee(index, 'title', v)}
                      placeholder="Title / Trade"
                      placeholderTextColor={colors.text.subtle}
                    />
                    <Text style={[s.attendeeMetaText, { flex: 2 }]} numberOfLines={1}>
                      {timeIn ? `In ${timeIn}` : '—'}
                    </Text>
                  </View>
                  {/* Optional, honest marker. Its absence means only that the
                      worker did not tap at the gate — never a deficiency. */}
                  {attendee.gate_confirmed ? (
                    <Text style={s.gateConfirmText} numberOfLines={1}>
                      {confirmedAt ? `Confirmed at gate · ${confirmedAt}` : 'Confirmed at gate'}
                    </Text>
                  ) : null}
                </View>
                <Pressable
                  onPress={() => toggleAttendeePresent(index)}
                  style={[s.signedToggle, attendee.signed && s.signedToggleActive]}
                >
                  {attendee.signed
                    ? <CheckCircle size={20} strokeWidth={1.5} color={semantic.verified} />
                    : <View style={s.unsignedCircle} />
                  }
                </Pressable>
              </View>
              );
            })}

            <GlassButton
              title="+ Add Worker"
              onPress={addAttendee}
              style={s.addWorkerBtn}
            />
          </GlassCard>

          {/* CP Signature */}
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <BookOpen size={16} strokeWidth={1.5} color="#3b82f6" />
              <Text style={s.sectionHeader}>Performed By — CP Signature</Text>
            </View>
            <SignaturePad
              title="Competent Person Signature"
              signerName={cpName}
              onNameChange={setCpName}
              existingSignature={cpSignature}
              onSignatureCapture={setCpSignature}
            />
          </GlassCard>
          </View>

          {/* Actions — hidden when finalized; the LockBar handles finalize/amend. */}
          {!locked && (
          <View style={s.actions}>
            <GlassButton
              title={saving ? 'Saving...' : 'Save Draft'}
              icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => handleSave('draft')}
              loading={saving}
              style={s.draftBtn}
            />
            <GlassButton
              title={saving ? 'Submitting...' : 'Submit & Sign'}
              icon={<CheckCircle size={16} strokeWidth={1.5} color="#fff" />}
              onPress={() => handleSave('submitted')}
              loading={saving}
              disabled={!cpSignature || attendees.length === 0}
              style={s.submitBtn}
            />
          </View>
          )}

          {/* logType drives the FREEZE MODEL: toolbox_talk is IMMEDIATE, so the
              bar hides Finalize (the signature already froze the log) and offers
              only Amend once locked. canFinalize stays false for that reason. */}
          <LogbookLockBar
            locked={locked}
            logId={existingLogId}
            logType="toolbox_talk"
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
  loadingCenter: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.08),
  },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flex: 1 },
  headerTitle: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
  headerSub: { fontSize: 11, color: colors.text.muted },
  statRow: { flexDirection: 'row', gap: spacing.xs },
  statBadge: {
    backgroundColor: 'rgba(59,130,246,0.15)',
    borderRadius: borderRadius.full,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderWidth: 1,
    borderColor: 'rgba(59,130,246,0.3)',
  },
  statText: { fontSize: 11, color: '#60a5fa', fontWeight: '600' },
  scrollView: { flex: 1 },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: 100,
    maxWidth: 720,
    width: '100%',
    alignSelf: 'center',
  },
  dateCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
    padding: spacing.md,
  },
  dateText: { fontSize: 14, color: colors.text.secondary },
  section: { marginBottom: spacing.md, padding: spacing.lg },
  sectionHeader: { fontSize: 16, fontWeight: '600', color: colors.text.primary, marginBottom: spacing.md },
  sectionHeaderRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.md },
  sectionSubtitle: { fontSize: 12, color: colors.text.muted, marginBottom: spacing.md, marginTop: -spacing.sm },
  attendeeCount: { marginLeft: 'auto', fontSize: 12, color: colors.text.muted },
  fieldRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.05),
    gap: spacing.md,
  },
  fieldLabel: { flex: 1, fontSize: 13, color: colors.text.secondary },
  fieldInput: {
    flex: 1.5,
    fontSize: 14,
    color: colors.text.primary,
    textAlign: 'right',
    padding: spacing.xs,
    backgroundColor: withAlpha('#ffffff', 0.04),
    borderRadius: borderRadius.sm,
  },
  topicCategory: { marginBottom: spacing.md },
  topicCategoryLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: spacing.sm,
  },
  topicGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  topicItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: withAlpha('#ffffff', 0.1),
    backgroundColor: withAlpha('#ffffff', 0.04),
  },
  topicItemActive: {
    backgroundColor: 'rgba(59,130,246,0.15)',
    borderColor: 'rgba(59,130,246,0.4)',
  },
  topicCheckbox: {
    width: 18,
    height: 18,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: withAlpha('#ffffff', 0.2),
    backgroundColor: withAlpha('#ffffff', 0.05),
    alignItems: 'center',
    justifyContent: 'center',
  },
  topicCheckboxActive: { backgroundColor: '#3b82f6', borderColor: '#3b82f6' },
  topicLabel: { fontSize: 13, color: colors.text.muted },
  topicLabelActive: { color: '#93c5fd', fontWeight: '500' },
  tableHeader: {
    flexDirection: 'row',
    gap: spacing.sm,
    paddingBottom: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.08),
    marginBottom: spacing.xs,
  },
  tableHeaderText: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  attendeeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.04),
  },
  // Roster row: name/company on the primary line, title/time-in beneath, so
  // the four §3301.12.3 fields fit a phone without a horizontal scroll.
  attendeeMain: { flex: 4, gap: 2 },
  attendeeLine: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  attendeeInput: {
    fontSize: 13,
    color: colors.text.primary,
    padding: spacing.xs,
    backgroundColor: withAlpha('#ffffff', 0.04),
    borderRadius: borderRadius.sm,
  },
  attendeeMetaInput: {
    fontSize: 11,
    color: colors.text.muted,
    paddingHorizontal: spacing.xs,
    paddingVertical: 2,
    backgroundColor: withAlpha('#ffffff', 0.02),
    borderRadius: borderRadius.sm,
  },
  attendeeMetaText: {
    fontSize: 11,
    color: colors.text.muted,
    paddingHorizontal: spacing.xs,
  },
  gateConfirmText: {
    fontSize: 10,
    color: semantic.verified,
    paddingHorizontal: spacing.xs,
  },
  signedToggle: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.xs,
  },
  signedToggleActive: {},
  unsignedCircle: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: withAlpha('#ffffff', 0.2),
  },
  addWorkerBtn: { marginTop: spacing.md, borderStyle: 'dashed' },
  autoSignBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.md,
    padding: spacing.sm,
    backgroundColor: semantic.verifiedBg,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: semantic.verifiedBorder,
  },
  autoSignText: { fontSize: 12, color: semantic.verified },
  actions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  draftBtn: { flex: 1 },
  submitBtn: { flex: 2, backgroundColor: 'rgba(59,130,246,0.2)', borderColor: 'rgba(59,130,246,0.4)' },
});
}
