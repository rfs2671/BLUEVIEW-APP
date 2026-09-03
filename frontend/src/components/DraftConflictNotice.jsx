import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { AlertTriangle } from 'lucide-react-native';
import { outdoor, spacing, borderRadius } from '../styles/theme';

/**
 * THE DRAFT ON SCREEN IS NOT THE RECORD, AND HE IS TOLD SO.
 *
 * The sibling of OfflineNotice, for the mirror-image lie. OfflineNotice exists
 * because a failed fetch used to render as a confident empty state ("no records
 * exist"). This exists because a stale local draft used to render as the filed
 * log — the editors returned before the server was ever asked, so device
 * content and server content were pixel-identical on screen, and a CP who
 * opened his log and pressed Submit reverted a correction he never saw.
 *
 * ── WHAT THE WORDING HAS TO DO ────────────────────────────────────────────
 *
 * Name the FALSE INFERENCE, the way workers/[id].jsx does when it hides its
 * edit affordance on a cached read. The inference being prevented here is
 * precisely: "what is on my screen is what is filed." Every branch below says
 * that sentence in its own terms before it says anything else.
 *
 * Then two promises, because a CP reading a red banner over his own day's work
 * needs both answered in the same breath:
 *
 *   HIS WORK IS KEPT. Nothing here discards a draft. The local record is
 *   untouched and it is still on the device after this banner appears — that is
 *   the whole reason the screen still shows it rather than replacing it with
 *   the server's copy.
 *
 *   AND SUBMIT IS STOPPED, so the newer server document cannot be overwritten
 *   by a wholesale `$set` from a draft that predates it. That is the one
 *   save-path change: a refusal, not a resolution.
 *
 * ── AND WHAT IT DELIBERATELY DOES NOT DO ──────────────────────────────────
 *
 * It does not offer a way to choose. There is no merge, no diff, no
 * pick-a-side, and no "use the server copy" button — THE CONFLICT UI IS OUT OF
 * SCOPE AND AWAITS ITS OWN DESIGN. Rather than dress that gap up, the last line
 * says it: the two copies cannot yet be reconciled in the app, so the CP is
 * pointed at a person. A dead end that admits it is a dead end is recoverable;
 * one that pretends to offer a path is not.
 *
 * PINNED TO `outdoor`, like every logbook editor that renders it — a CP fills a
 * compliance log in direct sun, and a theme-aware tint here would draw dark ink
 * on the dark canvas in the one place that must never be missed.
 */

/** The sentence for each verdict draftFreshness.compareStamps can reach. */
export function conflictCopy(reason) {
  switch (reason) {
    case 'server-locked':
      return {
        title: 'Filed and finalized on the server',
        body: 'This log was finalized on the server after this draft was saved. '
          + 'What you are looking at is your unsent draft — NOT the record. '
          + 'Your draft is kept on this device and nothing has been discarded, '
          + 'but it cannot be submitted over a finalized log.',
      };
    case 'server-filed':
      return {
        title: 'Already filed on the server',
        body: 'This log has already been filed on the server. '
          + 'What you are looking at is your unsent draft — NOT the record. '
          + 'Your draft is kept on this device and nothing has been discarded, '
          + 'but submitting it would overwrite what was filed, so it is blocked.',
      };
    case 'server-newer':
    default:
      return {
        title: 'The server copy is newer than this draft',
        body: 'The copy on the server changed after this draft was saved — an '
          + 'amendment or a correction. What you are looking at is your draft '
          + '— NOT the record. Your draft is kept on this device and nothing '
          + 'has been discarded, but submitting it would replace the newer '
          + 'server copy, so it is blocked.',
      };
  }
}

/**
 * `conflict` is the verdict object from compareDraftToServer. Renders nothing
 * unless it actually reported a conflict — a comparison that came back clean,
 * and an offline read where no comparison was possible, both draw no banner at
 * all. THAT IS THE OFFLINE GUARANTEE: a CP in a dead zone sees exactly the
 * screen he saw before this change.
 */
export default function DraftConflictNotice({ conflict, style }) {
  if (!conflict || !conflict.conflict) return null;
  const { title, body } = conflictCopy(conflict.reason);

  return (
    <View
      style={[s.wrap, style]}
      accessibilityRole="alert"
      accessibilityLabel={`${title}. ${body}`}
    >
      <AlertTriangle size={22} strokeWidth={1.8} color={outdoor.danger} />
      <View style={s.textWrap}>
        <Text style={s.title}>{title}</Text>
        <Text style={s.body}>{body}</Text>
        {/* THE GAP, STATED. Reconciling the two copies is the conflict UI and
            it is not built; saying so is more use to him than a button that
            picks a side on his behalf. */}
        <Text style={s.body}>
          The two copies cannot be merged in the app yet. Do not re-enter the
          day — send this log to your safety admin so the server copy can be
          checked against your draft.
        </Text>
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
});
