/**
 * Job completion, legal hold, and what they mean for this project's records.
 *
 * WHY THIS IS ON THE PROJECT SCREEN. The two fields it shows are the only
 * things standing between a project's compliance history and the owner's
 * irreversible purge. ESRA BB2024-007 §V.4 wants seven years past job
 * completion; until a completion date is recorded here, that period is not
 * computable for this project and nothing is checking it.
 *
 * THE ABSENT CASE IS NOT A CLEARANCE — IT IS A REFUSAL. A project with no
 * completion recorded shows "Not recorded" and says the records CANNOT be
 * deleted, because that is now what the server does. A date nobody asserted is
 * an open question, not a negative answer, and the purge refuses on the open
 * question. See backend/lib/project_retention.py — the dob_logs TTL incident is
 * what happens when a retention clock is allowed to guess.
 *
 * THE COMPLETION IS A PAIR. The CO number and the date are one control with one
 * button: the server refuses a half entry with a 400, so offering two separate
 * save actions would be offering one the server will always reject. A claim
 * about a legal event carries the event's identifier.
 *
 * NOTHING HERE VERIFIES THE CO NUMBER, and the editor says so out loud rather
 * than implying a check happened. The app does ingest DOB certificate-of-
 * occupancy rows, but nothing compares them against this field — see
 * docs/design/completion-co-reconciliation.md. An admin typing a number into a
 * box that looks validated will trust it more than one that admits it is an
 * attestation, and this field governs when records may be destroyed.
 *
 * `purge_eligible_at` arrives COMPUTED from the server on every read and is
 * stored nowhere. This component must never derive it locally: a second
 * implementation of the seven-year arithmetic is a second answer.
 */

import React, { useMemo, useState } from 'react';
import { View, Text, StyleSheet, Pressable, Modal, ScrollView } from 'react-native';
import {
  CalendarCheck, Lock, LockOpen, Pencil, FileWarning, Undo2,
} from 'lucide-react-native';

import { GlassCard } from './GlassCard';
import GlassButton from './GlassButton';
import GlassInput from './GlassInput';
import { useTheme } from '../context/ThemeContext';
import { useToast } from './Toast';
import { projectsAPI } from '../utils/api';
import { isOfflineError } from '../utils/offlineState';
import { spacing, borderRadius, typography } from '../styles/theme';
import { semantic } from '../styles/semanticColors';

// READ vocabulary only. `completion_source` is stamped by the server and is no
// longer accepted from the request body — every completion this app holds is an
// attestation, because nothing in it verifies a CO number. A legacy document
// may still carry a stronger value, so the labels stay for rendering; there is
// deliberately no picker any more, because offering one would let an admin
// claim a verification the app never performs.
const SOURCE_LABELS = {
  final_co: 'Final C of O',
  final_signoff: 'DOB sign-off',
  admin_attested: 'Attested',
};

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
// Mirrors CO_NUMBER_MAX_LEN in backend/lib/project_retention.py. Length is the
// ONLY bound either side applies — see co_number_problem() for why no format is
// enforced and why inventing one here would be worse than useless.
const CO_MAX_LEN = 64;

export default function ProjectRetentionCard({ project, canEdit, onUpdated }) {
  const { colors } = useTheme();
  const toast = useToast();
  const s = useMemo(() => buildStyles(colors), [colors]);

  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dateDraft, setDateDraft] = useState('');
  const [coDraft, setCoDraft] = useState('');
  const [holdReasonDraft, setHoldReasonDraft] = useState('');
  const [noCompletionDraft, setNoCompletionDraft] = useState('');

  if (!project) return null;

  const completed = project.job_completion_date;
  const coNumber = project.job_completion_co_number;
  const eligible = project.purge_eligible_at;
  const held = !!project.legal_hold;
  const attested = !!project.no_completion_attested;

  const openEditor = () => {
    setDateDraft(completed || '');
    setCoDraft(coNumber || '');
    setHoldReasonDraft(project.legal_hold_reason || '');
    setNoCompletionDraft(project.no_completion_reason || '');
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
    const co = coDraft.trim();
    // Checked here ONLY to give an immediate message; the server validates the
    // same rules and is the one that decides. Both halves are checked before
    // either is sent, because the server refuses a partial entry outright and
    // a request that cannot succeed should not leave this screen.
    if (!co) {
      toast.error('Enter the C of O number',
                  'A completion is recorded as a number and a date, together.');
      return;
    }
    if (co.length > CO_MAX_LEN) {
      toast.error('That number is too long', `Up to ${CO_MAX_LEN} characters.`);
      return;
    }
    if (!DATE_RE.test(v)) {
      toast.error('Check the date', 'Use YYYY-MM-DD, e.g. 2026-08-15.');
      return;
    }
    // Sent as ONE patch. Two requests would leave a window in which half a
    // completion is on record, which is the state the pair rule exists to
    // make unreachable.
    if (await save({ job_completion_date: v, job_completion_co_number: co })) {
      toast.success('Completion recorded', `Records retained 7 years from ${v}.`);
    }
  };

  const attestNoCompletion = async () => {
    const reason = noCompletionDraft.trim();
    if (!reason) {
      toast.error('This needs a reason',
                  'It is what permits these records to be deleted.');
      return;
    }
    if (await save({ no_completion_attested: true,
                     no_completion_reason: reason })) {
      toast.success('Attestation recorded',
                    'Recorded against your account. This project can now be deleted.');
    }
  };

  const withdrawNoCompletion = async () => {
    if (await save({ no_completion_attested: false })) {
      toast.success('Attestation withdrawn',
                    'This project can no longer be deleted.');
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

        {/* The certificate's own number, beside its date. Shown as its own row
            rather than appended to the date, because it is the identifier that
            makes the date a claim about a DOCUMENT — and because an admin
            checking this project against a paper certificate is looking for
            exactly this string. */}
        {!!coNumber && (
          <View style={s.row}>
            <Text style={s.label}>C of O number</Text>
            <Text style={s.value} selectable>{coNumber}</Text>
          </View>
        )}

        {/* Retention. Never invented locally — this is the server's number. */}
        <View style={s.row}>
          <Text style={s.label}>Records retained until</Text>
          {eligible ? (
            <Text style={s.value}>{eligible}</Text>
          ) : (
            <Text style={s.valueMuted}>Not computable</Text>
          )}
        </View>

        {!completed && !attested && (
          /* NOT a blank row and NOT a clearance. This says what the server
             actually does now: with no completion on record the retention
             period is unknown, and the purge REFUSES on the unknown. Saying
             only "cannot be calculated" would leave a reader assuming the
             deletion is unaffected, which is the opposite of the truth. */
          <View style={s.holdBanner}>
            <FileWarning size={14} strokeWidth={2} color={semantic.attention} />
            <View style={s.holdTextWrap}>
              <Text style={s.holdTitle}>No completion on record</Text>
              <Text style={s.holdMeta}>
                The seven-year period cannot be calculated, so this project's
                records cannot be deleted. Record the final C of O, or attest
                that the job was never completed.
              </Text>
            </View>
          </View>
        )}

        {/* The attestation, WITH ITS AUTHOR. This is the only thing that lets
            a project with no completion be destroyed, so a bare "cleared"
            badge would be an anonymous permission slip. */}
        {attested && !completed && (
          <View style={s.attestBanner}>
            <FileWarning size={14} strokeWidth={2} color={colors.text.secondary} />
            <View style={s.holdTextWrap}>
              <Text style={s.attestTitle}>Attested: never completed</Text>
              {!!project.no_completion_reason && (
                <Text style={s.holdReason}>{project.no_completion_reason}</Text>
              )}
              <Text style={s.holdMeta}>
                Recorded by {project.no_completion_attested_by || 'an admin'}.
                These records may be permanently deleted.
              </Text>
            </View>
          </View>
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

              <Text style={s.fieldLabel}>Final certificate of occupancy</Text>
              <Text style={s.fieldHelp}>
                The number and the date, both required — a claim about a legal
                event carries the event's identifier. It is never guessed from
                activity, and it starts a seven-year retention period that
                blocks deletion.
              </Text>
              <GlassInput
                value={coDraft}
                onChangeText={setCoDraft}
                placeholder="C of O number"
                autoCapitalize="characters"
                autoCorrect={false}
                maxLength={CO_MAX_LEN}
              />
              <GlassInput
                value={dateDraft}
                onChangeText={setDateDraft}
                placeholder="YYYY-MM-DD"
                autoCapitalize="none"
              />
              {/* SAID OUT LOUD. The app ingests DOB certificate-of-occupancy
                  records but compares none of them to this field, so an admin
                  should know the number is taken on their word — a box that
                  looks validated is trusted more than one that admits it is
                  not, and this field governs destruction. */}
              <Text style={s.fieldHelp}>
                Recorded as your attestation. The number is stored exactly as
                you enter it and is not checked against DOB records.
              </Text>

              <GlassButton
                title={saving ? 'Saving…' : 'Record completion'}
                onPress={saveCompletion}
                disabled={saving}
                style={s.saveBtn}
              />

              <View style={s.divider} />

              {/* ── THE OTHER WAY THROUGH ───────────────────────────────────
                  Offered ONLY when there is no completion on record, because
                  that is the only case it answers — the server refuses an
                  attestation against a recorded completion with a 400, and a
                  control that is always going to be refused should not be
                  drawn. */}
              {!completed && (
                <>
                  <Text style={s.fieldLabel}>Never completed</Text>
                  <Text style={s.fieldHelp}>
                    If this job has no certificate of occupancy and never will
                    — withdrawn, cancelled, or no work performed — say so here.
                    Without either this or a completion above, these records
                    cannot be deleted at all.
                  </Text>

                  {attested ? (
                    <>
                      <View style={s.attestBanner}>
                        <FileWarning
                          size={14}
                          strokeWidth={2}
                          color={colors.text.secondary}
                        />
                        <View style={s.holdTextWrap}>
                          <Text style={s.holdReason}>
                            {project.no_completion_reason || 'No reason recorded'}
                          </Text>
                        </View>
                      </View>
                      <Pressable
                        onPress={withdrawNoCompletion}
                        disabled={saving}
                        style={s.liftBtn}
                      >
                        <Undo2
                          size={14}
                          strokeWidth={2}
                          color={colors.text.secondary}
                        />
                        <Text style={s.liftText}>Withdraw attestation</Text>
                      </Pressable>
                    </>
                  ) : (
                    <>
                      <GlassInput
                        value={noCompletionDraft}
                        onChangeText={setNoCompletionDraft}
                        placeholder="Reason (e.g. permit withdrawn, no work performed)"
                        autoCapitalize="sentences"
                        multiline
                        numberOfLines={2}
                      />
                      <GlassButton
                        title={saving ? 'Saving…' : 'Attest never completed'}
                        onPress={attestNoCompletion}
                        disabled={saving}
                        style={s.saveBtn}
                      />
                    </>
                  )}

                  <View style={s.divider} />
                </>
              )}

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
  // Falls back to the raw key rather than to a friendly guess: an unrecognised
  // source is better shown as itself than relabelled into one of ours.
  return SOURCE_LABELS[key] || key;
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
    holdMeta: { fontSize: 11, lineHeight: 16, color: colors.text.muted },
    // A STANDING STATEMENT, NOT AN ALARM. Deliberately neutral rather than
    // wearing the attention colour the hold and the missing-completion warning
    // use: this one is a recorded fact that RESOLVES a block, and painting it
    // like a problem would misread the screen for whoever scans it next.
    attestBanner: {
      flexDirection: 'row', alignItems: 'flex-start', gap: spacing.xs,
      marginTop: spacing.sm, padding: spacing.sm,
      borderRadius: borderRadius.md,
      borderWidth: 1, borderColor: colors.border?.subtle || 'transparent',
    },
    attestTitle: {
      fontSize: 13, fontWeight: '700', color: colors.text.secondary,
    },
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
