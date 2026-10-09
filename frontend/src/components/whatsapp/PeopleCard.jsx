/**
 * Project → WhatsApp → People. Admins and PMs.
 *
 * Group senders Levelog can't match to anyone on file (mostly WhatsApp
 * privacy ids). For each: their WhatsApp name when there is one, the group,
 * how many messages and when the last one was. Tap one to say who they are —
 * a name and their company on the job (a sub on this project, or the GC
 * team). The answer applies to every group of the company. Nobody is
 * messaged. Raw WhatsApp ids never reach this screen.
 *
 * Copy: src/utils/whatsappPeople.js.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator, Modal, TextInput, ScrollView,
} from 'react-native';
import { Check } from 'lucide-react-native';
import { GlassCard } from '../GlassCard';
import { useToast } from '../Toast';
import { useTheme } from '../../context/ThemeContext';
import { whatsappAPI } from '../../utils/api';
import { isOfflineError } from '../../utils/offlineState';
import { spacing, borderRadius } from '../../styles/theme';
import { semantic, withAlpha } from '../../styles/semanticColors';
import {
  PEOPLE_TITLE, PEOPLE_NOTE, emptyText, assignmentLine, detailLine,
  assignRequest, savedText, safeLabel,
} from '../../utils/whatsappPeople';

export default function PeopleCard({ projectId }) {
  const { colors } = useTheme();
  const s = useMemo(() => buildStyles(colors), [colors]);
  const toast = useToast();
  const [data, setData] = useState(null);
  const [state, setState] = useState('loading'); // loading | ok | error
  const [editing, setEditing] = useState(null);  // the row being assigned
  const [name, setName] = useState('');
  const [company, setCompany] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await whatsappAPI.getWhatsAppPeople(projectId));
      setState('ok');
    } catch (e) {
      setState('error');
    }
  }, [projectId]);

  useEffect(() => { if (projectId) load(); }, [projectId, load]);

  const open = (row) => {
    setEditing(row);
    setName(row.assigned ? row.assigned.person_name : (row.push_name || ''));
    setCompany(row.assigned ? row.assigned.sub_company : null);
  };

  const fail = (e) => toast.error('Not saved', isOfflineError(e)
    ? 'This needs a connection. Nothing changed.'
    : (e?.response?.data?.detail && typeof e.response.data.detail === 'string'
      ? e.response.data.detail : 'That could not be saved. Try again.'));

  const save = async () => {
    const req = assignRequest({ name, company }, (data && data.companies) || []);
    if (req.error) { toast.error('Almost', req.error); return; }
    setSaving(true);
    try {
      const res = await whatsappAPI.setWhatsAppPerson(
        projectId, editing.key, req.body.personName, req.body.subCompany);
      toast.success(req.body.personName, savedText(res));
      setEditing(null);
      await load();
    } catch (e) {
      fail(e);
    } finally {
      setSaving(false);
    }
  };

  const clear = async () => {
    setSaving(true);
    try {
      await whatsappAPI.clearWhatsAppPerson(projectId, editing.key);
      toast.success('Cleared', 'They show as not assigned again.');
      setEditing(null);
      await load();
    } catch (e) {
      fail(e);
    } finally {
      setSaving(false);
    }
  };

  const rows = (data && data.senders) || [];
  const companies = (data && data.companies) || [];

  return (
    <>
      <Text style={s.heading}>{PEOPLE_TITLE}</Text>
      <GlassCard style={s.card}>
        <Text style={s.muted}>{PEOPLE_NOTE}</Text>
        {state === 'loading' ? (
          <ActivityIndicator color={colors.text.muted} style={{ marginTop: spacing.sm }} />
        ) : state === 'error' ? (
          <Pressable onPress={load} accessibilityRole="button">
            <Text style={[s.muted, { marginTop: spacing.sm }]}>
              This list could not be loaded. Tap to try again.
            </Text>
          </Pressable>
        ) : rows.length === 0 ? (
          <Text style={[s.muted, { marginTop: spacing.sm }]}>{emptyText('none')}</Text>
        ) : rows.map((row) => (
          <Pressable
            key={row.key}
            onPress={() => open(row)}
            accessibilityRole="button"
            accessibilityLabel={`${safeLabel(row.label)}: ${assignmentLine(row)}. Change`}
            style={({ pressed }) => [s.row, pressed && s.pressed]}
          >
            <View style={s.rowText}>
              <Text style={s.name}>{safeLabel(row.label)}</Text>
              <Text style={s.muted}>{detailLine(row)}</Text>
            </View>
            <Text style={[s.assign, !row.assigned && s.assignOpen]}>
              {assignmentLine(row)}
            </Text>
          </Pressable>
        ))}
      </GlassCard>

      <Modal visible={!!editing} transparent animationType="fade"
        onRequestClose={() => setEditing(null)}>
        <View style={s.backdrop}>
          <GlassCard variant="modal" style={s.modal}>
            <Text style={s.modalTitle}>Who is {safeLabel(editing && editing.label)}?</Text>
            <Text style={s.muted}>{detailLine(editing)}</Text>
            <Text style={s.label}>Name</Text>
            <TextInput
              value={name}
              onChangeText={setName}
              placeholder="Their name"
              placeholderTextColor={colors.text.subtle}
              autoCapitalize="words"
              style={s.input}
              maxLength={80}
            />
            <Text style={s.label}>Company on this job</Text>
            <ScrollView style={s.choices}>
              {companies.map((c) => (
                <Pressable key={c} onPress={() => setCompany(c)}
                  accessibilityRole="radio"
                  accessibilityState={{ selected: company === c }}
                  style={({ pressed }) => [s.choice, company === c && s.choiceOn,
                    pressed && s.pressed]}>
                  <Text style={s.choiceText}>{c}</Text>
                  {company === c ? <Check size={16} color={semantic.verified} /> : null}
                </Pressable>
              ))}
            </ScrollView>
            <View style={s.actions}>
              <Pressable onPress={() => setEditing(null)} style={s.cancel}
                accessibilityRole="button">
                <Text style={s.cancelText}>Cancel</Text>
              </Pressable>
              <Pressable onPress={save} disabled={saving}
                style={[s.save, saving && s.disabled]} accessibilityRole="button">
                {saving ? <ActivityIndicator size="small" color="#fff" />
                  : <Text style={s.saveText}>Save</Text>}
              </Pressable>
            </View>
            {editing && editing.assigned ? (
              <Pressable onPress={clear} disabled={saving} style={s.clear}
                accessibilityRole="button">
                <Text style={s.clearText}>Clear assignment</Text>
              </Pressable>
            ) : null}
          </GlassCard>
        </View>
      </Modal>
    </>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    heading: {
      fontSize: 13, fontWeight: '600', color: colors.text.muted, letterSpacing: 0.6,
      textTransform: 'uppercase', marginTop: spacing.lg, marginBottom: spacing.sm,
    },
    card: { padding: spacing.md },
    muted: { color: colors.text.muted, fontSize: 13, marginTop: 4 },
    row: {
      flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.sm,
      marginTop: spacing.sm, paddingTop: spacing.sm, minHeight: 44,
      borderTopWidth: 1, borderTopColor: colors.glass.border,
    },
    rowText: { flex: 1, minWidth: 180 },
    name: { color: colors.text.primary, fontSize: 15, fontWeight: '600' },
    assign: { color: colors.text.secondary, fontSize: 13, marginLeft: 'auto' },
    assignOpen: { color: semantic.attention, fontWeight: '600' },
    backdrop: {
      flex: 1, backgroundColor: withAlpha('#000000', 0.6),
      alignItems: 'center', justifyContent: 'center', padding: spacing.lg,
    },
    modal: { padding: spacing.lg, gap: spacing.xs, width: '100%', maxWidth: 420, maxHeight: '90%' },
    modalTitle: { color: colors.text.primary, fontSize: 17, fontWeight: '700' },
    label: { color: colors.text.muted, fontSize: 12, fontWeight: '600', marginTop: spacing.sm },
    input: {
      borderWidth: 1, borderColor: colors.glass.border, borderRadius: borderRadius.lg,
      paddingHorizontal: spacing.sm, minHeight: 44, color: colors.text.primary, fontSize: 15,
    },
    choices: { maxHeight: 240 },
    choice: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      minHeight: 44, paddingHorizontal: spacing.sm, borderRadius: borderRadius.md,
    },
    choiceOn: { backgroundColor: colors.glass.background },
    choiceText: { color: colors.text.primary, fontSize: 15 },
    actions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md },
    cancel: {
      flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.glass.border,
    },
    cancelText: { color: colors.text.secondary, fontSize: 14 },
    save: {
      flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.lg, backgroundColor: colors.primary || '#2563eb',
    },
    saveText: { color: '#fff', fontSize: 14, fontWeight: '700' },
    clear: { minHeight: 44, alignItems: 'center', justifyContent: 'center' },
    clearText: { color: semantic.attention, fontSize: 14, fontWeight: '600' },
    disabled: { opacity: 0.5 },
    pressed: { opacity: 0.8 },
  });
}
