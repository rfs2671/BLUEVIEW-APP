/**
 * CompetentPersonPicker — choose the man who DELIVERED the orientation, or
 * type him.
 *
 * WHY IT EXISTS. On a subcontractor orientation `cp_name` is the TRAINER'S
 * ATTESTATION under §3301.2 — the competent person who actually gave the
 * orientation. It is the one log type of eleven where that name is not derived
 * server-side, because the trainer may legitimately differ from the man
 * filing, so it has been a free-text box. What came out of that box is on the
 * record: 219 filed documents carry the CP's name as the lowercase string
 * "michael" where his account holds "Michael Cespedes", and 25 more carry the
 * digit "2".
 *
 * "2" is the part worth staring at. That is not a misspelling a normaliser
 * could ever repair — it is a keystroke that landed in a name field and was
 * filed as an attestation that a named competent person delivered safety
 * training. The fix is the same one `+ Add Row` got on the pre-shift sheet:
 * pick the man, and let the name come off a record instead of the keyboard.
 *
 * ── WHAT THIS LISTS, AND WHAT IT DOES NOT ──────────────────────────────────
 *
 * THE COMPANY'S COMPETENT PERSONS, NOT THE PROJECT'S. That is a real
 * limitation and it is stated here rather than papered over. Three sources
 * were considered:
 *
 *   GET /api/projects/{id}/roster    WORKERS — the men who tapped the gate.
 *                                    A laborer is not a competent person, and
 *                                    feeding that list into a §3301.2 trainer
 *                                    attestation would be a worse defect than
 *                                    the typing it replaces.
 *
 *   GET /api/projects/{id}/safety-staff
 *                                    SSC/SSM registrations only (the endpoint
 *                                    refuses any other role), which are the
 *                                    S-56/S-57 site safety licences required
 *                                    on Major A/B jobs. A different statutory
 *                                    designation, admin-created, and empty on
 *                                    most projects.
 *
 *   GET /api/users/company-roster    Company user accounts with their roles.
 *                                    `role === 'cp'` is already how this app
 *                                    renders "Competent Person"
 *                                    (utils/signatureAudit.js). This one.
 *
 * Nothing reachable by a filing CP is scoped to the PROJECT. Users carry
 * `assigned_projects` and projects carry assigned users, but the only endpoint
 * that projects that field is GET /admin/users, which is admin-only — a CP at
 * the gate cannot call it. So this over-includes: a competent person at the
 * same company who has never set foot on this job appears in the list.
 *
 * OVER-INCLUSION IS THE SAFE DIRECTION HERE, and deliberately chosen over
 * narrowing by hand. Every name shown is a real account, spelled the way the
 * account spells it; the failure it admits is the CP picking a colleague who
 * was not there, which he can see and would have to do on purpose. The failure
 * it removes is "2". Narrowing to a project would need a new endpoint, and one
 * was not forked for this.
 *
 * NO IDENTITY REFERENCE IS CARRIED ONTO THE DOCUMENT, and this is where it
 * differs from WorkerPicker. That component puts `worker_id` on the row, which
 * is what makes the row a reference to a man rather than a string resembling
 * one. Here the picked account's id STAYS IN COMPONENT STATE: `cp_name` is a
 * top-level string on a filed compliance record, the 244 documents already
 * filed could never carry a `cp_user_id`, and an absent one would mean either
 * "typed by hand" or "filed before the field existed" with nothing able to
 * tell them apart. That is the absent-versus-empty shape, declined here for
 * the same reason it was declined on the pre-shift row. What this delivers is
 * therefore SPELLING FROM A RECORD, not a foreign key.
 *
 * MANUAL ENTRY IS BEHIND A SECOND TAP, AND CARRIES NO FLAG, for that same
 * reason. Nothing blocks a filing: a competent person from a subcontractor
 * with no account here can have delivered the orientation.
 *
 * Same structure and the same refusals as WorkerPicker, including the one that
 * matters most: A FAILED READ IS NOT AN EMPTY LIST.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, TextInput, Pressable, FlatList, ActivityIndicator,
} from 'react-native';
import { Search, UserPlus, X } from 'lucide-react-native';

import { usersAPI } from '../utils/api';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius, typography } from '../styles/theme';

/**
 * WHO MAY BE NAMED AS THE TRAINER.
 *
 * The same four roles backend/server.py already treats as one class for acting
 * on a logbook. `worker` is excluded because a laborer is not a competent
 * person, and `site_device` because it is a provisioned tablet, not a man —
 * naming either in a §3301.2 attestation would be worse than the free text.
 */
export const TRAINER_ELIGIBLE_ROLES = ['cp', 'admin', 'owner', 'superintendent'];

/** Human label for the row's second line, so the CP picks knowingly. */
export const ROLE_LABELS = {
  cp: 'Competent Person',
  admin: 'Admin',
  owner: 'Owner',
  superintendent: 'Superintendent',
};

export function isTrainerEligible(row) {
  return TRAINER_ELIGIBLE_ROLES.includes(String(row?.role || '').toLowerCase());
}

/**
 * Fetch the company's competent persons. Exported so a caller can warm it and
 * so the test can drive it without a component tree.
 *
 * A ROW WITH NO NAME IS DROPPED, and only a row with no name. company-roster
 * falls back to the email address when an account has none, so "no name" here
 * means the account is genuinely blank — and an entry that reads as a blank
 * line is not something a CP can attest to having picked.
 */
export async function fetchCompetentPersons() {
  const rows = await usersAPI.companyRoster();
  return (Array.isArray(rows) ? rows : [])
    .filter(isTrainerEligible)
    .filter((r) => String(r?.name || '').trim().length > 0);
}

/**
 * IS THE PICKED COMPETENT PERSON THE ACCOUNT HOLDING THE PHONE?
 *
 * ONE RULE, IN ONE PLACE, because both mounters on the orientation screen ask
 * it and a screen whose two halves disagreed about "is this me" would write the
 * profile on one path and not the other.
 *
 * WHAT IT GUARDS. After a successful file, `autoSave` writes cp_name AND the
 * signature CREDENTIAL back as this device user's saved profile, and that
 * profile pre-fills every logbook he opens next. Before this screen had a
 * picker, naming another man was something a CP had to type on purpose;
 * making it the easy default without this question would take a trainer's
 * name — and a signature drawn by the trainer's hand — and store them as the
 * filer's reusable credential, with nothing on screen saying so.
 *
 * THREE KEYS, BECAUSE ONE IS NOT RELIABLE. company-roster returns `id` as the
 * stringified Mongo `_id`; the authenticated user object is whatever /auth/me
 * returned and is read elsewhere in this app as BOTH `id` and `_id`
 * (app/admin/users.jsx does exactly that comparison). Email is carried as the
 * third because it is the one field both sides always have, and a CP who picks
 * HIMSELF off the list must not quietly stop getting his own profile saved
 * because two id spellings did not line up.
 *
 * IT FAILS CLOSED, and that asymmetry is deliberate. Unsure means "do not
 * write the profile": the cost is one missed convenience refresh, where the
 * cost in the other direction is another man's name and signature stored as
 * this user's own.
 */
export function isSamePerson(picked, account) {
  if (!picked || !account) return false;
  const pid = String(picked.id || '').trim();
  for (const k of ['id', '_id']) {
    const v = String(account[k] || '').trim();
    if (pid && v && pid === v) return true;
  }
  const pe = String(picked.email || '').trim().toLowerCase();
  const ae = String(account.email || '').trim().toLowerCase();
  return !!pe && pe === ae;
}

/**
 * Substring match on name and email, case-insensitive.
 *
 * NOT a normaliser, for the same reason WorkerPicker's is not. This decides
 * what to SHOW while the CP types; it never decides that two accounts are one
 * man. Two accounts for one person both survive a query matching both — the CP
 * is the only person who knows they are the same man, and collapsing them here
 * would perform in the UI a merge that nothing downstream is allowed to make.
 */
export function filterCompetentPersons(rows, query) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return Array.isArray(rows) ? rows : [];
  return (Array.isArray(rows) ? rows : []).filter((r) => {
    const name = String(r?.name || '').toLowerCase();
    const email = String(r?.email || '').toLowerCase();
    return name.includes(q) || email.includes(q);
  });
}

export default function CompetentPersonPicker({
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
        const list = await fetchCompetentPersons();
        if (alive) setRows(list);
      } catch (_e) {
        // A FAILED READ IS NOT AN EMPTY LIST. Offline or a 403 must not
        // present as "no competent persons exist" — that reads as a fact
        // about the company and pushes the CP straight to the keyboard,
        // which is the exact thing this component exists to stop him doing
        // by accident. Say the list could not be loaded and leave manual
        // entry as the deliberate choice it already is.
        if (alive) setFailed(true);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  const matches = useMemo(() => filterCompetentPersons(rows, query), [rows, query]);

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
          placeholder="Search your company's competent persons"
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
          Could not load your company&apos;s competent persons. Check your
          signal, or enter the trainer by hand below.
        </Text>
      ) : null}

      {!loading && !failed && rows.length === 0 ? (
        <Text style={s.note}>
          No competent persons are registered for your company yet.
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
          keyExtractor={(item, i) => String(item?.id || i)}
          renderItem={({ item }) => (
            <Pressable style={s.row} onPress={() => choose(item)}>
              <Text style={s.rowName}>{item.name}</Text>
              <Text style={s.rowMeta}>
                {[ROLE_LABELS[item.role] || item.role, item.email]
                  .filter(Boolean).join(' · ') || ' '}
              </Text>
            </Pressable>
          )}
        />
      ) : null}

      {/* THE SECOND TAP. Present always — the orientation may have been
          delivered by a subcontractor's competent person who has no account
          here, and nothing blocks a filing. It is a deliberate choice rather
          than the default one. */}
      <Pressable style={s.manual} onPress={onManual}>
        <UserPlus size={14} strokeWidth={1.5} color={colors.text.secondary} />
        <Text style={s.manualText}>Enter a trainer not on this list</Text>
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
