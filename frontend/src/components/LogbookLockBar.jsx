import React, { useState } from 'react';
import { View, Text, Pressable, Modal, TextInput, StyleSheet, ActivityIndicator } from 'react-native';
import { Lock, FileEdit, CheckCircle2, X } from 'lucide-react-native';
import { logbooksAPI } from '../utils/api';
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
 *   canFinalize  bool     — show the Finalize button (typically: saved && !locked)
 *   onFinalized  fn       — called after a successful finalize (editor sets locked)
 *   onAmended    fn       — called after a successful amend (editor re-loads; its
 *                           fetch prefers the non-locked child → becomes editable)
 */
export default function LogbookLockBar({ locked, logId, canFinalize, onFinalized, onAmended }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [amendOpen, setAmendOpen] = useState(false);
  const [reason, setReason] = useState('');

  const doFinalize = async () => {
    if (!logId || busy) return;
    setBusy(true);
    try {
      await logbooksAPI.finalize(logId);
      toast.success('Finalized', 'Log locked. Corrections now require an amendment.');
      onFinalized?.();
    } catch (e) {
      toast.error('Could not finalize', e?.response?.data?.detail || e?.message || 'Please try again');
    } finally {
      setBusy(false);
    }
  };

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

  if (canFinalize && logId) {
    return (
      <View style={s.wrap}>
        <Pressable style={[s.btn, s.finalizeBtn, busy && s.btnDisabled]} onPress={doFinalize} disabled={busy}>
          {busy ? <ActivityIndicator size="small" color="#ffffff" /> : <CheckCircle2 size={18} strokeWidth={2} color="#ffffff" />}
          <Text style={s.btnText}>{busy ? 'Finalizing…' : 'Finalize (End of Day) — Lock'}</Text>
        </Pressable>
      </View>
    );
  }

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
