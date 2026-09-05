/**
 * WorkerPicker — choose a man who has been on this site, or type one.
 *
 * WHY IT EXISTS. `+ Add Row` on the pre-shift sign-in sheet took a hand-typed
 * name into a document where the gate already knows who is on site. That is
 * how one man came to appear twice on one filed report — "Jose Castaneda"
 * typed by a CP beside "Jose Julio Castaneda" from his orientation — and no
 * downstream matching rule can undo it: every rule that would unify those two
 * is asserted AGAINST by a regression guard written after a production failure
 * in that direction. Collapsing them deletes a man from the record of who was
 * on site, and a deletion is invisible where a duplicate is not.
 *
 * So the fix is upstream. Pick the man; his name, company, OSHA number and
 * worker_id come from the record rather than from the keyboard. That also
 * closes the free-text COMPANY field, which is where "Arkon" and "Arkon
 * Builders" came from.
 *
 * DUPLICATES ARE SHOWN, DELIBERATELY. A man who exists as two worker documents
 * appears twice in this list. The CP is the only person who knows they are the
 * same man; hiding one here would perform in the UI exactly the merge the
 * normalisers are forbidden to perform.
 *
 * MANUAL ENTRY IS BEHIND A SECOND TAP, AND CARRIES NO FLAG. A flag on the row
 * would be a field on a filed compliance document — `workers` is posted
 * verbatim as `data.workers[]` — and the 329 rows already filed could never
 * carry it, so an absent flag would mean either "gate-verified" or "filed
 * before the field existed" with nothing able to tell them apart. That is the
 * absent-versus-empty shape, and it was declined rather than introduced into a
 * document four renderers read.
 *
 * Cloned from GCAutocomplete/AddressAutocomplete — same debounce, same list,
 * same onSelect-returns-a-record contract.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, TextInput, Pressable, FlatList, ActivityIndicator,
} from 'react-native';
import { Search, UserPlus, X } from 'lucide-react-native';

import apiClient from '../utils/api';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius, typography } from '../styles/theme';

/**
 * Fetch the project's roster once. Exported so a caller can warm it and so the
 * test can drive it without a component tree.
 */
export async function fetchProjectRoster(projectId) {
  if (!projectId) return [];
  const res = await apiClient.get(`/api/projects/${projectId}/roster`);
  const rows = res?.data?.workers;
  return Array.isArray(rows) ? rows : [];
}

/**
 * Substring match on name and company, case-insensitive.
 *
 * NOT a normaliser. This decides what to SHOW while the CP types; it never
 * decides that two records are one man. Exported for the test, which asserts
 * exactly that: two spellings of one name both survive a query that matches
 * both.
 */
export function filterRoster(rows, query) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return Array.isArray(rows) ? rows : [];
  return (Array.isArray(rows) ? rows : []).filter((r) => {
    const name = String(r?.name || '').toLowerCase();
    const company = String(r?.company || '').toLowerCase();
    return name.includes(q) || company.includes(q);
  });
}

export default function WorkerPicker({
  projectId,
  onSelect,
  onManual,
  onCancel,
  autoFocus = true,
}) {
  const { colors } = useTheme();
  const [rows, setRows] = useState([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const list = await fetchProjectRoster(projectId);
        if (alive) setRows(list);
      } catch (_e) {
        // A FAILED READ IS NOT AN EMPTY ROSTER. Offline or a 403 must not
        // present as "nobody has ever worked here" — that would push the CP
        // to type, which is the thing this component exists to stop him
        // doing by accident. Say the list could not be loaded and leave
        // manual entry as the deliberate choice it already is.
        if (alive) setFailed(true);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [projectId]);

  const matches = useMemo(() => filterRoster(rows, query), [rows, query]);

  const choose = useCallback((row) => {
    if (typeof onSelect === 'function') onSelect(row);
  }, [onSelect]);

  const s = styles(colors);

  return (
    <View style={s.wrap}>
      <View style={s.searchRow}>
        <Search size={16} strokeWidth={1.5} color={colors.text.secondary} />
        <TextInput
          value={query}
          onChangeText={setQuery}
          autoFocus={autoFocus}
          placeholder="Search this site's workers"
          placeholderTextColor={colors.text.tertiary}
          style={s.input}
        />
        <Pressable onPress={onCancel} hitSlop={8} accessibilityLabel="Close">
          <X size={16} strokeWidth={1.5} color={colors.text.secondary} />
        </Pressable>
      </View>

      {loading ? <ActivityIndicator style={s.pad} /> : null}

      {!loading && failed ? (
        <Text style={s.note}>
          Could not load this site&apos;s workers. Check your signal, or add the
          worker by hand below.
        </Text>
      ) : null}

      {!loading && !failed && rows.length === 0 ? (
        <Text style={s.note}>
          Nobody has checked in on this site yet.
        </Text>
      ) : null}

      {!loading && !failed && rows.length > 0 && matches.length === 0 ? (
        <Text style={s.note}>No match for &ldquo;{query}&rdquo;.</Text>
      ) : null}

      {matches.length > 0 ? (
        <FlatList
          data={matches}
          keyboardShouldPersistTaps="handled"
          style={s.list}
          keyExtractor={(item, i) => String(item?.worker_id || i)}
          renderItem={({ item }) => (
            <Pressable style={s.row} onPress={() => choose(item)}>
              <Text style={s.rowName}>{item.name || '(no name on file)'}</Text>
              <Text style={s.rowMeta}>
                {[item.company, item.trade].filter(Boolean).join(' · ') || ' '}
              </Text>
            </Pressable>
          )}
        />
      ) : null}

      {/* THE SECOND TAP. Present always — a man can be on site who has never
          checked in here, and the standing rule is that nothing blocks a
          worker. It is a deliberate choice rather than the default one. */}
      <Pressable style={s.manual} onPress={onManual}>
        <UserPlus size={14} strokeWidth={1.5} color={colors.text.secondary} />
        <Text style={s.manualText}>Add someone not on this list</Text>
      </Pressable>
    </View>
  );
}

const styles = (colors) => ({
  wrap: {
    borderWidth: 1,
    borderColor: colors.border?.subtle || 'rgba(255,255,255,0.12)',
    borderRadius: borderRadius.md,
    padding: spacing.sm,
    marginTop: spacing.sm,
  },
  searchRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  input: {
    flex: 1,
    color: colors.text.primary,
    paddingVertical: spacing.xs,
    ...typography.body,
  },
  list: { maxHeight: 220, marginTop: spacing.xs },
  row: { paddingVertical: spacing.sm },
  rowName: { color: colors.text.primary, ...typography.body },
  rowMeta: { color: colors.text.secondary, ...typography.caption },
  note: { color: colors.text.secondary, padding: spacing.sm, ...typography.caption },
  pad: { padding: spacing.sm },
  manual: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.xs,
    marginTop: spacing.xs, paddingVertical: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border?.subtle || 'rgba(255,255,255,0.12)',
  },
  manualText: { color: colors.text.secondary, ...typography.caption },
});
