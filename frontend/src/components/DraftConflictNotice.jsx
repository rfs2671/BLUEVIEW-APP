import React from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';
import { AlertTriangle, Check } from 'lucide-react-native';
import { outdoor, spacing, borderRadius, touchTarget } from '../styles/theme';
import { titleCase } from '../utils/displayHelpers';
import { isOverridable } from '../utils/draftFreshness';

/**
 * THE DRAFT ON SCREEN IS NOT THE RECORD, AND HE IS TOLD SO — THEN HE DECIDES.
 *
 * The sibling of OfflineNotice, for the mirror-image lie. OfflineNotice exists
 * because a failed fetch used to render as a confident empty state ("no records
 * exist"). This exists because a stale local draft used to render as the filed
 * log — the editors returned before the server was ever asked, so device
 * content and server content were pixel-identical on screen, and a CP who
 * opened his log and pressed Submit reverted a correction he never saw.
 *
 * ── THE RULING THIS NOW IMPLEMENTS ────────────────────────────────────────
 *
 * THE CP'S DRAFT WINS. It is the most recent authorship and he is the one who
 * made it. The first version of this banner named the false inference and then
 * killed Submit outright, which was a placeholder for a decision nobody had
 * made yet. The decision has been made, so the dead end is gone: he is SHOWN
 * that the server copy changed, shown WHICH FIELDS changed where that can be
 * known, and then allowed to file his own work over it.
 *
 * ── WHAT THE WORDING HAS TO DO ────────────────────────────────────────────
 *
 * Name the FALSE INFERENCE, the way workers/[id].jsx does when it hides its
 * edit affordance on a cached read. The inference being prevented is precisely:
 * "what is on my screen is what is filed." Every branch says that sentence, and
 * says it in the SAME WORDS — the shared spine below is verbatim-identical
 * across all three verdicts, because a CP must not learn this two different
 * ways depending on which of the twelve logs he happened to open.
 *
 * Then the two promises a CP reading a red banner over his own day's work needs
 * answered in the same breath:
 *
 *   HIS WORK IS KEPT. Nothing here discards a draft, on any branch, including
 *   the two where he cannot file it. The local record is untouched and still on
 *   the device — that is why the screen still shows it rather than replacing it
 *   with the server's copy.
 *
 *   AND WHAT PRESSING SUBMIT WILL DO, stated before he presses it. On the
 *   overridable branch that sentence is the whole point: filing REPLACES the
 *   server copy. He is allowed to do that. He is not allowed to do it by
 *   accident, so the acknowledgement below is a separate press.
 *
 * ── WHY TWO OF THE THREE STILL REFUSE ─────────────────────────────────────
 *
 * `server-locked` and `server-filed` are not a competing draft — they are a
 * signed compliance record, and overwriting one with a stale local draft is the
 * exact 588 Thomas overwrite this line of work exists to stop. The server also
 * refuses the write (423 / 409), so re-enabling Submit there would hand him a
 * button that fails AFTER he signs. Those branches point him at Amend, which is
 * the mechanism that corrects a filed record while keeping both versions.
 *
 * PINNED TO `outdoor`, like every logbook editor that renders it — a CP fills a
 * compliance log in direct sun, and a theme-aware tint here would draw dark ink
 * on the dark canvas in the one place that must never be missed.
 */

/**
 * THE SHARED SPINE. Verbatim-identical on every verdict, and that is the
 * requirement rather than a saving: twelve editors render this component, and
 * the sentence that prevents the false inference must be the same sentence in
 * all twelve. Only what he can DO about it differs below, because that really
 * does differ.
 */
const SPINE = 'What you are looking at is your draft — NOT the copy on the '
  + 'server. Nothing of yours has been discarded; your draft is still saved on '
  + 'this device.';

/** The sentence for each verdict draftFreshness.compareStamps can reach. */
export function conflictCopy(reason) {
  switch (reason) {
    case 'server-locked':
      return {
        title: 'Finalized on the server',
        body: `This log was finalized on the server after this draft was saved. ${SPINE}`,
        // NOT OVERRIDABLE, and the reason is given in terms of the record
        // rather than in terms of the app: a finalized log is signed, and the
        // route that corrects one already exists.
        action: 'A finalized log is a signed record and cannot be replaced, so '
          + 'this draft cannot be filed over it. To correct the filed log, use '
          + 'Amend — that keeps both versions instead of destroying one.',
      };
    case 'server-filed':
      return {
        title: 'Already filed on the server',
        body: `This log was filed on the server after this draft was saved. ${SPINE}`,
        action: 'A filed log cannot be overwritten, so this draft cannot be '
          + 'filed over it. To correct the filed log, use Amend — that keeps '
          + 'both versions instead of destroying one.',
      };
    case 'server-newer':
    default:
      return {
        title: 'The server copy changed after this draft',
        body: 'This log was changed on the server after this draft was saved — '
          + `an amendment or a correction. ${SPINE}`,
        // THE CONSEQUENCE, IN PLAIN WORDS, BEFORE HE ACTS. `update_logbook`
        // applies `data` as a wholesale $set, so "replace" is literal and he
        // is owed the literal word.
        action: 'Your draft is the more recent work, so you may file it. Filing '
          + 'it will REPLACE the server copy of this log, including the change '
          + 'described above.',
      };
  }
}

/**
 * The changed-field line, or null when there is nothing honest to say.
 *
 * THREE ANSWERS, AND THEY ARE NOT THE SAME ANSWER. `changed` is null when no
 * comparison was possible (one side carried no `data`), `[]` when the two were
 * compared and no field differs, and a list otherwise. Collapsing null into
 * "nothing changed" would be a new instance of the original defect — a
 * confident statement about a comparison that never happened — so the null case
 * says nothing at all and the banner falls back to the plain statement of the
 * fact above, which is true regardless.
 *
 * CAPPED. A CP standing in the sun does not read a list of thirty field names;
 * the tail is counted rather than printed.
 */
const MAX_LISTED = 6;

export function changedFieldLine(changed) {
  if (!Array.isArray(changed)) return null;
  if (changed.length === 0) {
    return 'The fields on this form look the same — the server copy was '
      + 'updated without changing what you can see here.';
  }
  const labels = changed.map((k) => titleCase(k)).filter(Boolean);
  if (labels.length === 0) return null;
  const shown = labels.slice(0, MAX_LISTED).join(', ');
  const rest = labels.length - MAX_LISTED;
  return rest > 0
    ? `Different on the server: ${shown}, and ${rest} more.`
    : `Different on the server: ${shown}.`;
}

/**
 * `conflict` is the verdict object from compareDraftToServer. Renders nothing
 * unless it actually reported a conflict — a comparison that came back clean,
 * and an offline read where no comparison was possible, both draw no banner at
 * all. THAT IS THE OFFLINE GUARANTEE: a CP in a dead zone sees exactly the
 * screen he saw before this change.
 *
 * `onAcknowledge` is called with no arguments when he takes the override. It is
 * only ever rendered for a verdict `isOverridable` accepts, so a caller that
 * passes it cannot accidentally offer an override on a filed log.
 */
export default function DraftConflictNotice({ conflict, onAcknowledge, style }) {
  if (!conflict || !conflict.conflict) return null;
  const { title, body, action } = conflictCopy(conflict.reason);
  const fieldLine = changedFieldLine(conflict.changed);
  const canOverride = isOverridable(conflict);
  const acked = conflict.acknowledged === true;

  // THE FULL TEXT REACHES A SCREEN READER AS ONE ALERT. A CP using VoiceOver
  // must get the fact, the fields and the consequence together — the same
  // three things the sighted screen shows at once.
  const spoken = [title, body, fieldLine, action].filter(Boolean).join(' ');

  return (
    <View
      style={[s.wrap, style]}
      accessibilityRole="alert"
      accessibilityLabel={spoken}
    >
      <AlertTriangle size={22} strokeWidth={1.8} color={outdoor.danger} />
      <View style={s.textWrap}>
        <Text style={s.title}>{title}</Text>
        <Text style={s.body}>{body}</Text>
        {/* WHICH FIELDS, when both documents were in hand. Not a diff tool —
            the names of the top-level fields that disagree, which is what
            compareDraftToServer already holds and costs a loop to name. */}
        {!!fieldLine && <Text style={s.fields}>{fieldLine}</Text>}
        <Text style={s.body}>{action}</Text>

        {/* ── THE OVERRIDE, AND WHY IT IS A SEPARATE PRESS ──────────────────
            The ruling lets him file his draft over the server's change. It
            does not let that happen as a side effect of pressing the button he
            always presses, so acknowledging the fact and acting on it are two
            distinct acts. Submit stays dead until this is taken.

            RENDERED ONLY WHEN THE VERDICT IS OVERRIDABLE. On a finalized or
            filed log there is nothing to offer — the server refuses the write
            — and an override control there would be a lie about what the
            button will do. */}
        {canOverride && !acked && (
          <Pressable
            style={s.ackBtn}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: false }}
            accessibilityLabel="I have read what changed on the server. File my version of this log."
            hitSlop={8}
            onPress={onAcknowledge}
          >
            <View style={s.ackBox} />
            <Text style={s.ackText}>
              I have read what changed on the server. File my version.
            </Text>
          </Pressable>
        )}
        {canOverride && acked && (
          <View
            style={s.ackDone}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: true }}
            accessibilityLabel="Acknowledged. Submitting will replace the server copy of this log."
          >
            <Check size={18} strokeWidth={3} color={outdoor.ok} />
            <Text style={s.ackDoneText}>
              Acknowledged — submitting will replace the server copy.
            </Text>
          </View>
        )}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.md,
    borderWidth: 2,
    borderColor: outdoor.danger,
    backgroundColor: outdoor.warnBg,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  textWrap: { flex: 1, minWidth: 0 },
  title: { fontSize: 16, fontWeight: '800', color: outdoor.danger, marginBottom: 4 },
  body: { fontSize: 14, lineHeight: 20, color: outdoor.text, marginTop: 2 },
  // The field list is the one line he is meant to actually read, so it is set
  // apart from the prose around it rather than buried in it.
  fields: {
    fontSize: 14,
    lineHeight: 20,
    fontWeight: '700',
    color: outdoor.text,
    backgroundColor: outdoor.surfaceSunk,
    borderRadius: borderRadius.sm,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
  },
  // GLOVED, OUTDOORS, ONE-HANDED — the same reason the app pins a minimum
  // touch target everywhere else. This one re-enables a destructive write, so
  // it must be deliberately hit rather than brushed.
  ackBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    minHeight: touchTarget.min,
    marginTop: spacing.sm,
  },
  ackBox: {
    width: 26,
    height: 26,
    borderRadius: borderRadius.sm,
    borderWidth: 2,
    borderColor: outdoor.danger,
    backgroundColor: outdoor.textOnSelected,
  },
  ackText: { flex: 1, fontSize: 14, lineHeight: 20, fontWeight: '700', color: outdoor.danger },
  ackDone: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    minHeight: touchTarget.min,
    marginTop: spacing.sm,
  },
  ackDoneText: { flex: 1, fontSize: 14, lineHeight: 20, fontWeight: '700', color: outdoor.ok },
});
