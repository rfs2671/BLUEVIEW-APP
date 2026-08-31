import React from 'react';
import { View, Text } from 'react-native';
import { FileEdit } from 'lucide-react-native';
import { semantic, withAlpha } from '../styles/semanticColors';
import { spacing, borderRadius } from '../styles/theme';

/**
 * WHY IS THIS LOG DIFFERENT, AND WHY AM I SIGNING IT AGAIN.
 *
 * A CP opens a log he filed and finds it a different shape and unsigned. He did
 * not make the correction and, until this existed, nothing on the screen said
 * one had been made: `amendment_reason` was stored on the child by
 * amend_logbook and read back by NOTHING — not the app, not the report. The
 * sentence justifying a change to a signed 3301.2 record existed only in Mongo.
 *
 * IT RENDERS ABOVE THE FORM, NOT IN THE LOCK BAR. LogbookStepper puts
 * LogbookLockBar after the step content, at the bottom of the scroll — which is
 * the right place for "finalize / amend" and the wrong place for this. A banner
 * answering "why am I signing again" that sits below the thing he is being
 * asked to sign has already failed.
 *
 * WHO AND WHEN, NOT JUST WHY. "Filed by Roy Fishman on 2026-08-31" is the fact
 * that turns a record which changed shape into a record somebody changed. A
 * reason with no author is a mystery with an explanation attached.
 *
 * THREE STATES, and the middle one is not decorative:
 *
 *   has_reason true   → amended, and the reason is on the record
 *   has_reason false  → amended, and NO reason was recorded. Said plainly,
 *                       because an empty quotation rendered as though somebody
 *                       wrote it is worse than an admission that nobody did.
 *   no amendment      → renders nothing at all
 *
 * amend_logbook refuses a reasonless amendment (400), so nothing through that
 * endpoint reaches the middle state — but a script, a migration or a direct
 * write can, and this codebase spent 2026-08-31 on exactly that class of row.
 *
 * IT READS THE RECORD, NEVER THE CLOCK. `at` is the calendar day off the
 * amendment document. Nothing here is relative, so an amendment filed in
 * September for an August log reads the same in December.
 */
export default function AmendmentBanner({ amendment }) {
  if (!amendment) return null;

  const who = amendment.by ? ` by ${amendment.by}` : '';
  const when = amendment.at ? ` on ${amendment.at}` : '';
  const hasReason = !!(amendment.has_reason && amendment.reason);

  return (
    <View
      accessibilityRole="summary"
      style={{
        flexDirection: 'row',
        gap: spacing.sm,
        alignItems: 'flex-start',
        padding: spacing.md,
        marginBottom: spacing.md,
        borderRadius: borderRadius.md,
        borderLeftWidth: 3,
        borderLeftColor: semantic.attention,
        backgroundColor: withAlpha(semantic.attention, 0.08),
      }}
    >
      <FileEdit size={18} strokeWidth={1.75} color={semantic.attention} />
      <View style={{ flex: 1 }}>
        <Text style={{ fontWeight: '700', color: semantic.attention, marginBottom: 2 }}>
          This log was corrected
        </Text>
        <Text style={{ color: semantic.attention }}>
          {`A correction was filed${who}${when}. `}
          {hasReason
            ? amendment.reason
            : 'No reason was recorded for it.'}
        </Text>
        {/* THE ACTION, SEPARATED FROM THE EXPLANATION. He is being asked to
            re-sign work he already signed once, and the reason he is being
            asked has to come before the asking. */}
        <Text style={{ marginTop: 6, color: semantic.attention }}>
          Your signature was cleared by the correction. Review the log and sign
          it again.
        </Text>
      </View>
    </View>
  );
}
