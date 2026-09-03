/**
 * Job completion, legal hold, and what they mean for this project's records.
 *
 * WHY THIS IS ON THE PROJECT SCREEN. The two fields it shows are the only
 * things standing between a project's compliance history and the owner's
 * irreversible purge. ESRA BB2024-007 §V.4 wants seven years past job
 * completion; until a completion date is recorded here, that period is not
 * computable for this project and nothing is checking it.
 *
 * THE ABSENT CASE IS NOT A CLEARANCE. A project with no completion date shows
 * "Not recorded", never "no retention requirement". The distinction is the
 * whole point of the field: a date nobody asserted is an open question, not a
 * negative answer. See backend/lib/project_retention.py — the dob_logs TTL
 * incident is what happens when a retention clock is allowed to guess.
 *
 * `purge_eligible_at` arrives COMPUTED from the server on every read and is
 * stored nowhere. This component must never derive it locally: a second
 * implementation of the seven-year arithmetic is a second answer.
 */

import React, { useMemo, useState } from 'react';
import { View, Text, StyleSheet, Pressable, Modal, ScrollView } from 'react-native';
import { CalendarCheck, Lock, LockOpen, Pencil } from 'lucide-react-native';

import { GlassCard } from './GlassCard';
import GlassButton from './GlassButton';
import GlassInput from './GlassInput';
import { useTheme } from '../context/ThemeContext';
import { useToast } from './Toast';
import { projectsAPI } from '../utils/api';
import { isOfflineError } from '../utils/offlineState';
import { spacing, borderRadius, typography } from '../styles/theme';
import { semantic } from '../styles/semanticColors';

// Mirrors VALID_COMPLETION_SOURCES in backend/server.py. The server is the
// authority and rejects anything else with a 400; this list only decides what
// the picker offers.
const SOURCES = [
  { key: 'final_co', label: 'Final C of O' },
  { key: 'final_signoff', label: 'DOB sign-off' },
  { key: 'admin_attested', label: 'Attested' },
];

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export default function ProjectRetentionCard({ project, canEdit, onUpdated }) {
  const { colors } = useTheme();
  const toast = useToast();
  const s = useMemo(() => buildStyles(colors), [colors]);

  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dateDraft, setDateDraft] = useState('');
  const [sourceDraft, setSourceDraft] = useState('final_co');
  const [holdReasonDraft, setHoldReasonDraft] = useState('');

  if (!project) return null;

  const completed = project.job_completion_date;
  const eligible = project.purge_eligible_at;
  const held = !!project.legal_hold;

  const openEditor = () => {
    setDateDraft(completed || '');
    setSourceDraft(project.completion_source || 'final_co');
    setHoldReasonDraft(project.legal_hold_reason || '');
    setEditing(true);
  };

  const save = async (patch) => {
    setSaving(true);
    try {
      const updated = await projectsAPI.update(project.id, patch);
      onUpdated?.(updated);
      setEditing(false);
      return true;
    } catch (e) {
      if (isOfflineError(e)) {
        // These fields gate an irreversible deletion. An ambiguous "failed"
        // could be read as "probably saved", and a hold someone believes is
        // in place but is not is the worst outcome this screen can produce.
        toast.error('Offline', 'Nothing was saved. This needs a connection.');
      } else {
        toast.error('Could not save', e?.response?.data?.detail || '');
      }
      return false;
    } finally {
      setSaving(false);
    }
  };

  const saveCompletion = async () => {
    const v = dateDraft.trim();
    // Checked here only to give an immediate message; the server validates
    // the same rule and is the one that decides.
    if (!DATE_RE.test(v)) {
      toast.error('Check the date', 'Use YYYY-MM-DD, e.g. 2026-08-15.');
      return;
    }
    if (await save({ job_completion_date: v, completion_source: sourceDraft })) {
      toast.success('Completion recorded', `Records retained 7 years from ${v}.`);
    }
  };

  const placeHold = async () => {
    const reason = holdReasonDraft.trim();
    if (!reason) {
      toast.error('A hold needs a reason', 'It never expires on its own.');
      return;
    }
    if (await save({ legal_hold: true, legal_hold_reason: reason })) {
      toast.success('Legal hold placed', 'This project can no longer be deleted.');
    }
  };

  const liftHold = async () => {
    if (await save({ legal_hold: false })) {
      toast.success('Legal hold lifted', 'Recorded against your account.');
    }
  };

  return (
    <>
      <GlassCard style={s.card}>
        <View style={s.headerRow}>
          <CalendarCheck size={16} strokeWidth={1.5} color={colors.text.muted} />
          <Text style={s.title}>RECORDS & RETENTION</Text>
          {canEdit && (
            <Pressable onPress={openEditor} hitSlop={8} style={s.editBtn}>
              <Pencil size={14} strokeWidth={1.8} color={colors.text.muted} />
            </Pressable>
          )}
        </View>

        {/* Completion */}
        <View style={s.row}>
          <Text style={s.label}>Job completed</Text>
          {completed ? (
            <Text style={s.value}>
              {completed}
              {project.completion_source
                ? ` · ${labelFor(project.completion_source)}`
                : ''}
            </Text>
          ) : (
            <Text style={s.valueMuted}>Not recorded</Text>
          )}
        </View>

        {/* Retention. Never invented locally — this is the server's number. */}
        <View style={s.row}>
          <Text style={s.label}>Records retained until</Text>
          {eligible ? (
            <Text style={s.value}>{eligible}</Text>
          ) : (
            <Text style={s.valueMuted}>Not computable</Text>
          )}
        </View>

        {!completed && (
          /* Stated plainly rather than left as a blank row. "Not computable"
             on its own reads like a bug; it is actually a missing fact, and
             one an admin on this screen can supply. */
          <Text style={s.note}>
            No completion date has been recorded, so the seven-year retention
            period cannot be calculated for this project.
          </Text>
        )}

        {/* Legal hold */}
        {held ? (
          <View style={s.holdBanner}>
            <Lock size={14} strokeWidth={2} color={semantic.attention} />
            <View style={s.holdTextWrap}>
              <Text style={s.holdTitle}>Legal hold in force</Text>
              {!!project.legal_hold_reason && (
                <Text style={s.holdReason}>{project.legal_hold_reason}</Text>
              )}
              <Text style={s.holdMeta}>
                This project cannot be deleted. A hold does not expire.
              </Text>
            </View>
          </View>
        ) : (
          <View style={s.row}>
            <Text style={s.label}>Legal hold</Text>
            <Text style={s.valueMuted}>None</Text>
          </View>
        )}
      </GlassCard>

      <Modal visible={editing} transparent animationType="fade">
        <View style={s.modalBackdrop}>
          <GlassCard variant="modal" style={s.modalCard}>
            <ScrollView contentContainerStyle={s.modalScroll}>
              <Text style={s.modalTitle}>Records & retention</Text>

              <Text style={s.fieldLabel}>Job completion date</Text>
              <Text style={s.fieldHelp}>
                The date the job actually finished — a final C of O is the
                record to go by. It is never guessed from activity, and it
                starts a seven-year retention period that blocks deletion.
              </Text>
              <GlassInput
                value={dateDraft}
                onChangeText={setDateDraft}
                placeholder="YYYY-MM-DD"
                autoCapitalize="none"
              />

              <Text style={s.fieldLabel}>How do we know?</Text>
              <View style={s.sourceRow}>
                {SOURCES.map((opt) => (
                  <Pressable
                    key={opt.key}
                    onPress={() => setSourceDraft(opt.key)}
                    style={[
                      s.sourceChip,
                      sourceDraft === opt.key && s.sourceChipOn,
                    ]}
                  >
                    <Text
                      style={[
                        s.sourceChipText,
                        sourceDraft === opt.key && s.sourceChipTextOn,
                      ]}
                    >
                      {opt.label}
                    </Text>
                  </Pressable>
                ))}
              </View>

              <GlassButton
                title={saving ? 'Saving…' : 'Save completion date'}
                onPress={saveCompletion}
                disabled={saving}
                style={s.saveBtn}
              />

              <View style={s.divider} />

              <Text style={s.fieldLabel}>Legal hold</Text>
              <Text style={s.fieldHelp}>
                Blocks deletion of this project's records regardless of the
                retention period. It never expires — someone has to lift it.
              </Text>

              {project.legal_hold ? (
                <>
                  <View style={s.holdBanner}>
                    <Lock size={14} strokeWidth={2} color={semantic.attention} />
                    <View style={s.holdTextWrap}>
                      <Text style={s.holdReason}>
                        {project.legal_hold_reason || 'No reason recorded'}
                      </Text>
                    </View>
                  </View>
                  <Pressable
                    onPress={liftHold}
                    disabled={saving}
                    style={s.liftBtn}
                  >
                    <LockOpen size={14} strokeWidth={2} color={colors.text.secondary} />
                    <Text style={s.liftText}>Lift legal hold</Text>
                  </Pressable>
                </>
              ) : (
                <>
                  <GlassInput
                    value={holdReasonDraft}
                    onChangeText={setHoldReasonDraft}
                    placeholder="Reason (e.g. Kaplan v. 588 Boyland)"
                    autoCapitalize="sentences"
                    multiline
                    numberOfLines={2}
                  />
                  <GlassButton
                    title={saving ? 'Saving…' : 'Place legal hold'}
                    onPress={placeHold}
                    disabled={saving}
                    style={s.saveBtn}
                  />
                </>
              )}

              <Pressable
                onPress={() => setEditing(false)}
                disabled={saving}
                style={s.closeBtn}
              >
                <Text style={s.closeText}>Close</Text>
              </Pressable>
            </ScrollView>
          </GlassCard>
        </View>
      </Modal>
    </>
  );
}

function labelFor(key) {
  return SOURCES.find((o) => o.key === key)?.label || key;
}

function buildStyles(colors) {
  return StyleSheet.create({
    card: { padding: spacing.md, gap: spacing.xs, marginBottom: spacing.md },
    headerRow: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.xs,
      marginBottom: spacing.xs,
    },
    title: {
      ...typography.label, flex: 1, fontSize: 11, letterSpacing: 0.8,
      color: colors.text.muted,
    },
    editBtn: { padding: 4 },
    row: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      gap: spacing.sm, paddingVertical: 3,
    },
    label: { fontSize: 13, color: colors.text.secondary },
    value: { fontSize: 13, fontWeight: '600', color: colors.text.primary },
    valueMuted: { fontSize: 13, color: colors.text.subtle },
    note: {
      fontSize: 12, lineHeight: 17, color: colors.text.muted,
      marginTop: spacing.xs,
    },
    holdBanner: {
      flexDirection: 'row', alignItems: 'flex-start', gap: spacing.xs,
      marginTop: spacing.sm, padding: spacing.sm,
      borderRadius: borderRadius.md,
      backgroundColor: semantic.attentionBg,
      borderWidth: 1, borderColor: semantic.attentionBorder,
    },
    holdTextWrap: { flex: 1, gap: 2 },
    holdTitle: { fontSize: 13, fontWeight: '700', color: semantic.attention },
    holdReason: { fontSize: 12, lineHeight: 17, color: colors.text.primary },
    holdMeta: { fontSize: 11, color: colors.text.muted },
    modalBackdrop: {
      flex: 1, backgroundColor: 'rgba(0,0,0,0.7)',
      alignItems: 'center', justifyContent: 'center', padding: spacing.lg,
    },
    modalCard: { width: '100%', maxWidth: 440, maxHeight: '85%' },
    modalScroll: { padding: spacing.lg, gap: spacing.sm },
    modalTitle: {
      fontSize: 16, fontWeight: '700', color: colors.text.primary,
      marginBottom: spacing.xs,
    },
    fieldLabel: {
      fontSize: 12, fontWeight: '600', color: colors.text.secondary,
      marginTop: spacing.sm,
    },
    fieldHelp: {
      fontSize: 11, lineHeight: 16, color: colors.text.muted,
      marginBottom: spacing.xs,
    },
    sourceRow: { flexDirection: 'row', gap: spacing.xs, flexWrap: 'wrap' },
    sourceChip: {
      paddingHorizontal: spacing.sm, paddingVertical: 6,
      borderRadius: borderRadius.lg, borderWidth: 1,
      borderColor: colors.border?.subtle || 'transparent',
    },
    sourceChipOn: {
      borderColor: semantic.attentionBorder,
      backgroundColor: semantic.attentionBg,
    },
    sourceChipText: { fontSize: 12, color: colors.text.secondary },
    sourceChipTextOn: { color: colors.text.primary, fontWeight: '600' },
    saveBtn: { marginTop: spacing.sm },
    divider: {
      height: 1, marginVertical: spacing.md,
      backgroundColor: colors.border?.subtle || 'transparent',
    },
    liftBtn: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
      gap: spacing.xs, marginTop: spacing.sm, paddingVertical: spacing.sm,
      borderRadius: borderRadius.lg, borderWidth: 1,
      borderColor: colors.border?.subtle || 'transparent',
    },
    liftText: { fontSize: 13, fontWeight: '600', color: colors.text.secondary },
    closeBtn: { alignItems: 'center', paddingVertical: spacing.sm, marginTop: spacing.xs },
    closeText: { fontSize: 13, color: colors.text.muted },
  });
}
