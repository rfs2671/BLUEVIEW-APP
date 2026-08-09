import React, { useEffect, useState } from 'react';
import { View, Text, Pressable, Modal, TextInput, StyleSheet, ActivityIndicator } from 'react-native';
import { Lock, FileEdit, CheckCircle2, X, AlertTriangle } from 'lucide-react-native';
import { logbooksAPI } from '../utils/api';
import { finalizeErrorCode, readFinalizeError, clearFinalizeError } from '../utils/draftSync';
import { isImmediateLog } from '../utils/logbookTiming';
import { useT } from '../i18n';
import { useToast } from './Toast';
import { semantic, withAlpha } from '../styles/semanticColors';
import { spacing, borderRadius } from '../styles/theme';

/**
 * Tier 1 (1)b — the lock / finalize / amend control shared by every logbook
 * editor. It is the ONLY thing that can change a finalized log; the editor wraps
 * its form in `pointerEvents={locked ? 'none' : 'auto'}` so a finalized log has
 * genuinely no editable fields.
 *
 *   locked=true                → "FINALIZED — read-only" banner + Amend (requires
 *                                a Reason for Amendment; opens the editable child).
 *   locked=false, canFinalize  → Finalize (End of Day) — locks the log immutable.
 *
 * Props:
 *   locked       bool     — the loaded log's is_locked
 *   logId        string   — existing logbook id (null if unsaved)
 *   draftKey     string   — this log's local draft key. OPTIONAL, and only used
 *                           when logId is null: a push the server REFUSED before
 *                           the log existed has no logbook id to be recorded
 *                           against, so the drain records it against the draft
 *                           key instead. Without this the refusal is invisible
 *                           on exactly the logs that were never created.
 *   canFinalize  bool     — show the Finalize button (typically: saved && !locked)
 *   onFinalized  fn       — called after a successful finalize (editor sets locked)
 *   onAmended    fn       — called after a successful amend (editor re-loads; its
 *                           fetch prefers the non-locked child → becomes editable)
 */
export default function LogbookLockBar({ locked, logId, draftKey, canFinalize, onFinalized, onAmended, logType }) {
  // FREEZE MODEL: for an IMMEDIATE log the SIGNATURE is the freeze — submitting
  // finalizes it in one action, so a separate "Finalize" button must never
  // appear (offering it would imply the signed log is still open). The Amend
  // path below still applies once it is locked. The 2 daily-narrative logs keep
  // Finalize as their explicit end-of-day Submit & Sign.
  const signFreezes = isImmediateLog(logType);
  const toast = useToast();
  const t = useT('finalize');
  const [busy, setBusy] = useState(false);
  const [amendOpen, setAmendOpen] = useState(false);
  const [reason, setReason] = useState('');
  // A finalize the SERVER refused for THIS log on a background reconnect drain.
  const [refusedCode, setRefusedCode] = useState(undefined);
  const [refusedSource, setRefusedSource] = useState('drain');

  /**
   * COMPLETENESS GATE — the server names the condition, this owns the wording.
   *
   * /finalize rejects an empty or unsigned log with a machine code and no prose
   * (backend/server.py:14638-14645), so a known code maps to bilingual copy and
   * anything unrecognised falls back to the bilingual generic — the same shape
   * as BLOCK_LABELS in backend/checkin.html:1508-1518. `translate` returns the
   * KEY on a miss, which is how an unmapped code is detected. The server's
   * English `detail` is never rendered.
   */
  const gateCopy = (code) => {
    if (!code) return t('genericError');
    const key = `code_${code}`;
    const copy = t(key);
    return copy && copy !== key ? copy : t('genericError');
  };

  // Surfaced HERE because the drain that hits it has no screen: it runs off a
  // NetInfo transition with nothing mounted, so the refusal is recorded against
  // the logbook id and shown at the next interaction with that exact log.
  useEffect(() => {
    let alive = true;
    // logId first; the draft key only when there is no log. A refused CREATE
    // never produced an id, so the draft key is the only handle that exists.
    const handle = logId || draftKey;
    if (!handle) { setRefusedCode(undefined); return undefined; }
    readFinalizeError(handle)
      .then((rec) => {
        if (!alive) return;
        setRefusedCode(rec ? (rec.code || null) : undefined);
        // A DRAIN refusal is genuinely queued and will retry. A FOREGROUND
        // editor refusal left the draft editable with no pending key, so
        // nothing retries it. Same banner, different truth — the hint must
        // differ, or the app asserts a retry that cannot happen.
        setRefusedSource(rec ? (rec.source || 'drain') : 'drain');
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [logId, draftKey]);

  const doFinalize = async () => {
    if (!logId || busy) return;
    setBusy(true);
    try {
      await logbooksAPI.finalize(logId);
      await clearFinalizeError(logId);
      setRefusedCode(undefined);
      toast.success('Finalized', 'Log locked. Corrections now require an amendment.');
      onFinalized?.();
    } catch (e) {
      toast.error(t('errorTitle'), gateCopy(finalizeErrorCode(e)));
    } finally {
      setBusy(false);
    }
  };

  // NOT SAVED vs NOT LOCKED — two different facts, and saying the wrong one is
  // worse than saying nothing. With no logId the log was never created: nothing
  // is frozen anywhere and the work exists only on this device. With a logId the
  // content is on the server and only the LOCK was refused.
  const neverSaved = !logId;

  // `undefined` = no refusal on record; `null` = refused with no recognised code.
  const notLockedBanner = refusedCode === undefined ? null : (
    <View style={s.warnBanner}>
      <AlertTriangle size={16} strokeWidth={2} color={semantic.attention} />
      <View style={s.warnTextWrap}>
        <Text style={s.warnTitle}>{t(neverSaved ? 'notPushedTitle' : 'notLockedTitle')}</Text>
        <Text style={s.warnBody}>{gateCopy(refusedCode)}</Text>
        <Text style={s.warnBody}>
          {neverSaved
            ? t('notPushedHint')
            : t(refusedSource === 'editor' ? 'notLockedHintEditor' : 'notLockedHint')}
        </Text>
      </View>
    </View>
  );

  const doAmend = async () => {
    if (!logId || busy) return;
    if (!reason.trim()) {
      toast.warning('Reason required', 'Enter a reason for the amendment.');
      return;
    }
    setBusy(true);
    try {
      await logbooksAPI.amend(logId, reason.trim());
      setAmendOpen(false);
      setReason('');
      toast.success('Amendment created', 'Editable copy opened; the original stays locked.');
      onAmended?.();
    } catch (e) {
      toast.error('Could not amend', e?.response?.data?.detail || e?.message || 'Please try again');
    } finally {
      setBusy(false);
    }
  };

  if (locked) {
    return (
      <View style={s.wrap}>
        {notLockedBanner}
        <View style={s.banner}>
          <Lock size={16} strokeWidth={2} color={semantic.critical} />
          <Text style={s.bannerText}>FINALIZED — read-only. Corrections require an amendment.</Text>
        </View>
        <Pressable style={[s.btn, s.amendBtn]} onPress={() => setAmendOpen(true)} disabled={busy}>
          <FileEdit size={18} strokeWidth={2} color="#ffffff" />
          <Text style={s.btnText}>Amend</Text>
        </Pressable>

        <Modal visible={amendOpen} transparent animationType="fade" onRequestClose={() => setAmendOpen(false)}>
          <View style={s.modalOverlay}>
            <View style={s.modalCard}>
              <View style={s.modalHeader}>
                <Text style={s.modalTitle}>Reason for Amendment</Text>
                <Pressable hitSlop={12} onPress={() => { setAmendOpen(false); setReason(''); }}>
                  <X size={20} strokeWidth={2} color={semantic.neutral} />
                </Pressable>
              </View>
              <Text style={s.modalSub}>
                Required. The original log stays locked and intact; this creates a linked, re-signable copy.
              </Text>
              <TextInput
                style={s.input}
                value={reason}
                onChangeText={setReason}
                placeholder="e.g. Corrected worker count / fixed weather entry"
                placeholderTextColor={semantic.neutral}
                multiline
              />
              <View style={s.modalRow}>
                <Pressable style={[s.btn, s.cancelBtn]} onPress={() => { setAmendOpen(false); setReason(''); }} disabled={busy}>
                  <Text style={s.btnText}>Cancel</Text>
                </Pressable>
                <Pressable style={[s.btn, s.amendBtn, (!reason.trim() || busy) && s.btnDisabled]} onPress={doAmend} disabled={busy || !reason.trim()}>
                  {busy ? <ActivityIndicator size="small" color="#ffffff" /> : <Text style={s.btnText}>Create Amendment</Text>}
                </Pressable>
              </View>
            </View>
          </View>
        </Modal>
      </View>
    );
  }

  if (canFinalize && logId && !signFreezes) {
    return (
      <View style={s.wrap}>
        {notLockedBanner}
        <Pressable style={[s.btn, s.finalizeBtn, busy && s.btnDisabled]} onPress={doFinalize} disabled={busy}>
          {busy ? <ActivityIndicator size="small" color="#ffffff" /> : <CheckCircle2 size={18} strokeWidth={2} color="#ffffff" />}
          <Text style={s.btnText}>{busy ? 'Finalizing…' : 'Finalize (End of Day) — Lock'}</Text>
        </Pressable>
      </View>
    );
  }

  // A log with no lock control at all (an immediate type, or one that cannot be
  // finalized from here) still has to be able to say it is not locked on the
  // server — that is exactly the case the drain leaves behind.
  if (notLockedBanner) return <View style={s.wrap}>{notLockedBanner}</View>;

  return null;
}

const s = StyleSheet.create({
  wrap: { gap: spacing.sm, marginTop: spacing.md },
  banner: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    backgroundColor: semantic.criticalBg,
    borderColor: withAlpha('#ef4444', 0.4), borderWidth: 1,
    borderRadius: borderRadius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
  },
  bannerText: { color: semantic.critical, fontSize: 13, fontWeight: '700', flex: 1 },
  // Persistent, not a 4s toast: the drain that produced this had no screen, and
  // a vanishing notice on a compliance record is how it stayed invisible before.
  warnBanner: {
    flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm,
    backgroundColor: semantic.attentionBg,
    borderColor: semantic.attentionBorder, borderWidth: 1,
    borderRadius: borderRadius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
  },
  warnTextWrap: { flex: 1, gap: 2 },
  warnTitle: { color: semantic.attention, fontSize: 13, fontWeight: '700' },
  warnBody: { color: semantic.attention, fontSize: 12, lineHeight: 17 },
  btn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm,
    paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderRadius: borderRadius.md,
  },
  btnText: { color: '#ffffff', fontSize: 15, fontWeight: '700' },
  btnDisabled: { opacity: 0.6 },
  finalizeBtn: { backgroundColor: semantic.attention },
  amendBtn: { backgroundColor: semantic.critical },
  cancelBtn: { backgroundColor: withAlpha('#94a3b8', 0.35), flex: 1 },
  modalOverlay: {
    flex: 1, backgroundColor: withAlpha('#000000', 0.6),
    justifyContent: 'center', padding: spacing.lg,
  },
  modalCard: {
    backgroundColor: '#111827', borderRadius: borderRadius.lg, padding: spacing.lg, gap: spacing.md,
    borderColor: withAlpha('#ffffff', 0.1), borderWidth: 1,
  },
  modalHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  modalTitle: { color: '#ffffff', fontSize: 17, fontWeight: '700' },
  modalSub: { color: semantic.neutral, fontSize: 13, lineHeight: 18 },
  input: {
    backgroundColor: withAlpha('#ffffff', 0.06), borderColor: withAlpha('#ffffff', 0.12), borderWidth: 1,
    borderRadius: borderRadius.md, padding: spacing.md, color: '#ffffff', minHeight: 72, textAlignVertical: 'top',
  },
  modalRow: { flexDirection: 'row', gap: spacing.sm },
});
