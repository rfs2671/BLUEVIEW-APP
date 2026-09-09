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
 * IT WAS PROPOSED FOR REMOVAL AND KEPT, and the label is why it was proposed.
 * "Enter a competent person not on this list" reads as covering account
 * holders, so it looked like a redundant escape hatch beside a complete list
 * -- and a man without an account cannot use the app, so what would it be for?
 *
 * THE ANSWER IS THAT ITEM 8 DOES NOT RECORD WHO FILES. It records who was
 * DESIGNATED under BC 3301.13.12, and the designee never touches this app: the
 * superintendent files. A subcontractor's competent person, or a specialist in
 * for one day, is lawfully designatable and will never hold an account.
 * Removing this would leave him naming the wrong man or ticking "I was on site
 * at all times active work occurred" -- a false statement about his own
 * presence, on a signed record.
 *
 * So the label now says who it is for, in both mounters' own words.
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
import { spacing, borderRadius, typography, outdoor } from '../styles/theme';

/**
 * THE INK, WHEN THE CANVAS UNDER IT IS PINNED LIGHT.
 *
 * MEASURED, NOT EYEBALLED. On the superintendent log this component renders
 * inside a `Card`, whose fill is the `outdoor` gradient — a light card painted
 * whatever theme the CP has set, because a compliance log is filled outdoors
 * in direct sun. The picker asked `useTheme()`, and the app's default theme is
 * DARK, so every row was painted in dark-mode ink:
 *
 *   ink                          worst   best   AA 4.5:1
 *   text.primary  rgba(255,255,255,0.9)   1.02   1.26   FAIL   the names
 *   text.secondary rgba(255,255,255,0.6)  1.01   1.17   FAIL   role · email
 *   text.subtle   rgba(255,255,255,0.3)   1.01   1.08   FAIL   the border
 *
 *   outdoor.text     #0A1929              13.75  17.39  PASS
 *   outdoor.textSoft rgba(10,25,41,0.75)   6.84   7.82  PASS
 *   outdoor.textDim  rgba(10,25,41,0.65)   4.99   5.50  PASS
 *
 * 1.02:1 is not "low contrast". It is INVISIBLE — white on white, across all
 * six surfaces (two card gradient stops over three page gradient stops). The
 * operator could read the static paragraph BELOW the card and nothing inside
 * it, which is exactly the shape of a component that brought its own palette
 * onto somebody else's canvas.
 *
 * ── SAME PROP, SAME NAME, SAME REASONING AS SignaturePad ────────────────────
 *
 * `AnimatedBackground` and `SignaturePad` already carry `pinned` for this, and
 * both are mounted by the same twelve screens. This is the third, and it was
 * the one nobody passed it to — the picker arrived on the superintendent log
 * AFTER the pinning convention existed, from a screen (`subcontractor_
 * orientation`) that is correctly themed and where it therefore looked right.
 *
 * DEFAULT FALSE, so the orientation's two mounts render byte-identically.
 *
 * `text.tertiary` IS NOT IN EITHER PALETTE, and this table is where that
 * surfaced. `styles()` read `colors.text.tertiary` for the search
 * placeholder; neither `_dark` nor `_light` declares the key, so the value
 * handed to `placeholderTextColor` has always been `undefined` — on both
 * screens, in both themes, falling through to whatever the platform picks.
 * Fixed at the call site rather than by inventing a token: `text.subtle` is
 * the app's declared placeholder colour and says so in theme.js.
 *
 * outdoorMatchesLight.test.cjs already asserts `text.primary/secondary/muted`
 * and `border.subtle` are identical to `_light`'s, so on those four a pinned
 * picker renders EXACTLY what an unpinned one renders in light mode.
 *
 * `subtle` IS THE ONE THAT IS NOT A PAIR, and it is darkened on purpose.
 * `_light.text.subtle` is 0.50 alpha and `outdoor` has no counterpart, so this
 * maps it to `textDim` (0.65) — the same substitution SignaturePad makes, for
 * the same reason: the value is only ever a border here, and erring toward
 * more contrast on a screen read in direct sun is the right direction to be
 * wrong in.
 */
const PINNED_COLORS = {
  border: { subtle: outdoor.line },
  text: {
    primary: outdoor.text,
    secondary: outdoor.textSoft,
    muted: outdoor.textDim,
    subtle: outdoor.textDim,
  },
};

/**
 * THE ROLE FILTER IS GONE, AND IT WAS EXCLUDING NOBODY.
 *
 * It read `['cp', 'admin', 'owner', 'superintendent']` and argued, correctly,
 * that a laborer is not a competent person. MEASURED AGAINST PRODUCTION, every
 * account on the platform holds one of exactly three roles:
 *
 *     owner 3   admin 3   cp 3
 *     not in the eligible list: []
 *
 * The filing superintendent's own company holds three accounts and ALL THREE
 * were already listed. So the filter cost a fetch-time pass and removed
 * nothing, which is the shape the operator named: a filter that excludes
 * nothing is one nobody remembers when the first `worker` account appears --
 * and by then it is a silent exclusion rather than a decision.
 *
 * SO THE LIST IS EVERY ACCOUNT THE ROSTER RETURNS. `company-roster` already
 * scopes to the caller's company and drops deleted users; this component adds
 * only the blank-name rule below.
 *
 * ── AND `site_device` IS THE ONE CASE THIS NOW ADMITS ───────────────────────
 *
 * A `site_device` account is a PROVISIONED TABLET AT THE GATE, not a man, and
 * naming one in a BC 3301.13.12 designation would be false. ZERO such accounts
 * exist today, so nothing is live -- but the exclusion that used to cover it
 * is what has just been removed, and this is the note that says so rather than
 * a silent deviation from the ruling. If it should be excluded by name, that
 * is a one-line change here.
 */

/**
 * Human label for the row's second line, so the CP picks knowingly.
 *
 * `worker` and `site_device` ARE NAMED even though nothing holds them today.
 * Without a label the row falls back to the raw slug, and "site_device" under
 * a name is a worse thing to put in front of a superintendent choosing a
 * competent person than "Site device (tablet)".
 */
export const ROLE_LABELS = {
  cp: 'Competent Person',
  admin: 'Admin',
  owner: 'Owner',
  superintendent: 'Superintendent',
  worker: 'Worker',
  site_device: 'Site device (tablet)',
};

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

/**
 * THE TWO SENTENCES THAT ARE ABOUT THE ORIENTATION AND NOT ABOUT THE LIST.
 *
 * This component lists the company's competent persons, which is the same
 * population two different statutory questions need. Only the WORDS differ:
 *
 *   subcontractor_orientation   who DELIVERED the training (§3301.2)
 *   superintendent log item 8   who was DESIGNATED (BC 3301.13.12)
 *
 * Defaulted to the orientation's wording so that screen is untouched by this
 * change, and so a future third caller that forgets to pass them gets a
 * sentence that is merely imprecise rather than one that is blank.
 */
const TRAINER_MANUAL_LABEL =
  'A trainer from another company, with no account here';
const TRAINER_FAILED_NOTE =
  "Could not load your company's competent persons. Check your signal, or "
  + 'enter the trainer by hand below.';

export default function CompetentPersonPicker({
  onSelect,
  onManual,
  onCancel,
  autoFocus = true,
  manualLabel = TRAINER_MANUAL_LABEL,
  failedNote = TRAINER_FAILED_NOTE,
  // THE ROSTER, WHEN THE CALLER ALREADY HAS IT.
  //
  // The superintendent screen must resolve item 8's default BEFORE this
  // component is ever opened -- it needs a NAME to show on the closed control,
  // and only the roster maps the account id on the daily log to one. Letting
  // it hand the list down means one request instead of two on a screen used at
  // a gate with poor signal.
  //
  // OPTIONAL, so the orientation's two mounts keep self-fetching exactly as
  // they do today. `undefined` means "fetch it yourself"; an empty ARRAY is a
  // caller saying it looked and found nobody, which is a different fact and is
  // shown as the empty state rather than as a failure.
  rows: providedRows,
  // THE CANVAS UNDER THIS IS PINNED LIGHT — see PINNED_COLORS above.
  //
  // Passed by the superintendent log, whose Card fill is the `outdoor`
  // gradient whatever theme the CP has set. Default FALSE, so the
  // orientation's two mounts are unchanged.
  pinned = false,
}) {
  // THE HOOK STILL RUNS WHEN PINNED, for the reason AnimatedBackground states:
  // it is what re-renders this subtree on a theme toggle, and a pinned child
  // inside an unpinned tree must keep re-rendering with the rest of it.
  const { colors: liveColors } = useTheme();
  const colors = pinned ? PINNED_COLORS : liveColors;
  const [rows, setRows] = useState(providedRows || []);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(!providedRows);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (providedRows) { setRows(providedRows); return undefined; }
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
  }, [providedRows]);

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
          // `text.subtle`, NOT `text.tertiary`. The latter is in neither
          // palette, so this prop has always received `undefined` — see
          // PINNED_COLORS. `subtle` is the app's declared placeholder colour.
          placeholderTextColor={colors.text.subtle}
          style={s.input}
        />
        <Pressable onPress={onCancel} hitSlop={8} accessibilityLabel="Close">
          <X size={16} strokeWidth={1.5} color={colors.text.secondary} />
        </Pressable>
      </View>

      {loading ? <ActivityIndicator style={s.pad} /> : null}

      {!loading && failed ? (
        <Text style={s.note}>{failedNote}</Text>
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
        <Text style={s.manualText}>{manualLabel}</Text>
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
