import React, { useState } from 'react';
import { View, Text, Pressable, ActivityIndicator } from 'react-native';
import { FileEdit } from 'lucide-react-native';
import { logbooksAPI } from '../utils/api';
import { discardFinalizedDraft, clearPending } from '../utils/logbookDrafts';
import { WITHDRAWAL_ATTESTATION_STATEMENT } from '../utils/amendmentChain';
import { hasSignatureInk } from '../utils/signatureAffirmed';
import SignaturePad from './SignaturePad';
import { useToast } from './Toast';
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
 *
 * ── THE THIRD ANSWER ────────────────────────────────────────────────────────
 *
 * Until now this banner offered the CP exactly one way out of a correction he
 * is looking at: sign it. Production says what the other way was — seven
 * unsigned amendment drafts on one project, two of them FORKS (one parent, two
 * children, sixty and twenty-six seconds apart) made by a man who tapped Amend
 * and saw nothing happen. Every one of them warns on his card forever, and
 * signing one files a correction he may not intend.
 *
 * "I did not mean to make this" is a real answer and it had no button.
 *
 * IT IS SIGNED FOR. Operator ruling: "Signature required, as ruled. It is an
 * attested act." A withdrawal is a permanent statement about a compliance
 * record — that a proposed correction was abandoned, deliberately, by a named
 * person — so the same pad every other attested act uses stands in front of it.
 *
 * THE PAD IS REVEALED, NOT RESIDENT. This banner renders on TWELVE logbook
 * editors; a signature canvas sitting open under every corrected log the CP
 * merely opens would be noise on eleven of them and a mis-tap risk on the
 * twelfth. Tapping Withdraw reveals it, Cancel puts it away, and the confirm
 * is gated on `hasSignatureInk` — the app's own predicate, because presence is
 * not ink: `cp_signature: {}` satisfied every presence gate in this app while
 * the documents it signed printed UNAFFIRMED.
 *
 * STILL NO REQUIRED REASON. `amendment_reason` is gated hard because it
 * explains a CHANGE to a signed record; a withdrawal explains the ABSENCE of
 * one, and the amendment's own reason is still on the document saying what was
 * attempted. The sentence above the pad is the copy of record and comes from
 * amendmentChain, which mirrors the string the server stores beside the ink —
 * a signature over a sentence the server never heard of would put a claim in
 * the record about what a man was shown.
 *
 * THE LOCAL DRAFT GOES WITH IT. The parent and its amendment share ONE draft
 * key, so leaving the child's working copy behind would let syncPendingDrafts
 * PUT a withdrawn correction back at app startup with no user in the path.
 * `clearPending` first (it comes out of the push queue), then the draft — both
 * only after the SERVER has confirmed, which is the rule discardFinalizedDraft
 * states in its own docstring.
 */
export default function AmendmentBanner({
  amendment,
  // Withdrawal is offered only when the caller supplies the id of the
  // amendment on screen. Absent, this renders exactly what it always did.
  logId = null,
  draftKey = null,
  onWithdrawn = null,
}) {
  // `useToast` RETURNS NULL OUTSIDE A PROVIDER, by design — it stopped
  // throwing so consumers could call it unconditionally (React #310). So
  // every call below is guarded: a missing toast must never turn a
  // successful withdrawal into a crash on the screen it just fixed.
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  // The pad, revealed by the Withdraw button. `signing` is the panel; `sig` is
  // what the pad emitted; `signerName` is the pad's own name field, which
  // SignaturePad renders but does not own — its `canConfirm` needs both a
  // stroke and a name, so the Confirm below cannot be reached without them.
  const [signing, setSigning] = useState(false);
  const [sig, setSig] = useState(null);
  const [signerName, setSignerName] = useState('');

  if (!amendment) return null;

  const who = amendment.by ? ` by ${amendment.by}` : '';
  const when = amendment.at ? ` on ${amendment.at}` : '';
  const hasReason = !!(amendment.has_reason && amendment.reason);

  const doWithdraw = async () => {
    // NO INK, NO REQUEST. The server refuses it anyway (400
    // WITHDRAW_SIGNATURE_REQUIRED); this keeps the refusal off the wire and
    // out of a toast that would read like a fault.
    if (!logId || busy || !hasSignatureInk(sig)) return;
    setBusy(true);
    try {
      await logbooksAPI.withdraw(logId, sig);
      if (draftKey) {
        await clearPending(draftKey);
        await discardFinalizedDraft(draftKey);
      }
      toast?.success(
        'Correction withdrawn',
        'The log you signed is unchanged, and this correction is off your list.',
      );
      onWithdrawn?.();
    } catch (e) {
      // THE SERVER NAMES THE CONDITION; THIS OWNS THE WORDING — gateCopy's
      // rule, the same one doAmend follows in LogbookLockBar.
      const detail = e?.response?.data?.detail;
      const code = detail && typeof detail === 'object' ? detail.code : null;
      if (code === 'WITHDRAW_FILED_AMENDMENT') {
        toast?.error(
          'This correction is already filed',
          'It is part of the record now and cannot be taken back. Amend it '
          + 'again if something in it is wrong.',
        );
      } else if (code === 'WITHDRAW_NOT_AN_AMENDMENT') {
        toast?.error(
          'This is the log itself',
          'Only a correction can be withdrawn, not the day it corrects.',
        );
      } else if (code === 'WITHDRAW_SIGNATURE_REQUIRED') {
        // Reachable only if the pad emitted something this client called ink
        // and the server did not. It still teaches, because "Could not
        // withdraw" in front of a man who just signed reads as a fault in the
        // app rather than as a thing he can fix.
        toast?.error(
          'Sign to withdraw',
          'Withdrawing a correction is an attested act. Draw your signature '
          + 'and your name, then confirm.',
        );
      } else {
        toast?.error('Could not withdraw',
          (typeof detail === 'string' ? detail : null)
          || e?.message || 'Please try again');
      }
    } finally {
      setBusy(false);
    }
  };

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
        {/* THE OTHER ANSWER. Rendered only when the caller handed us the id of
            the correction on screen — a banner that cannot act must not offer
            an action. Secondary by construction: an outlined control under the
            sentence, never competing with Submit. */}
        {logId ? (
          <View style={{ marginTop: spacing.md }}>
            <Text style={{ color: semantic.attention, marginBottom: 6 }}>
              If this correction was not meant to be made, you can withdraw it.
              The log you signed stays exactly as it is.
            </Text>
            {!signing ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Withdraw this correction"
                onPress={() => setSigning(true)}
                disabled={busy}
                style={({ pressed }) => ({
                  alignSelf: 'flex-start',
                  paddingVertical: spacing.sm,
                  paddingHorizontal: spacing.md,
                  borderRadius: borderRadius.sm,
                  borderWidth: 1,
                  borderColor: semantic.attention,
                  backgroundColor: withAlpha(semantic.attention, pressed ? 0.18 : 0),
                  opacity: busy ? 0.6 : 1,
                })}
              >
                <Text style={{ color: semantic.attention, fontWeight: '700' }}>
                  Withdraw this correction
                </Text>
              </Pressable>
            ) : (
              <View>
                {/* THE SENTENCE HE IS SIGNING, ABOVE THE PAD AND NOT BESIDE
                    IT. It is the same string the server stores on the document
                    with the ink, so the record can say what he was told. */}
                <Text
                  style={{
                    color: semantic.attention,
                    fontWeight: '700',
                    marginBottom: spacing.sm,
                  }}
                >
                  {WITHDRAWAL_ATTESTATION_STATEMENT}
                </Text>
                {/* `pinned` for the same reason the ten logbook editors pass
                    it: a CP signs outdoors in direct sun, and the chrome
                    around a light-pinned canvas goes invisible without it. */}
                <SignaturePad
                  title="Sign to withdraw"
                  signerName={signerName}
                  onNameChange={setSignerName}
                  onSignatureCapture={setSig}
                  disabled={busy}
                  autoLock={false}
                  pinned
                />
                <View
                  style={{
                    flexDirection: 'row',
                    gap: spacing.sm,
                    marginTop: spacing.sm,
                  }}
                >
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="Confirm withdrawal"
                    onPress={doWithdraw}
                    // GATED ON INK, not on presence. `{}` is truthy in JS and
                    // is not a signature.
                    disabled={busy || !hasSignatureInk(sig)}
                    style={({ pressed }) => ({
                      paddingVertical: spacing.sm,
                      paddingHorizontal: spacing.md,
                      borderRadius: borderRadius.sm,
                      borderWidth: 1,
                      borderColor: semantic.attention,
                      backgroundColor: withAlpha(
                        semantic.attention, pressed ? 0.18 : 0),
                      opacity: (busy || !hasSignatureInk(sig)) ? 0.5 : 1,
                    })}
                  >
                    {busy ? (
                      <ActivityIndicator size="small" color={semantic.attention} />
                    ) : (
                      <Text style={{ color: semantic.attention, fontWeight: '700' }}>
                        Confirm withdrawal
                      </Text>
                    )}
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="Cancel withdrawal"
                    onPress={() => { setSigning(false); setSig(null); }}
                    disabled={busy}
                    style={{
                      paddingVertical: spacing.sm,
                      paddingHorizontal: spacing.md,
                      opacity: busy ? 0.5 : 1,
                    }}
                  >
                    <Text style={{ color: semantic.attention }}>Cancel</Text>
                  </Pressable>
                </View>
              </View>
            )}
          </View>
        ) : null}
      </View>
    </View>
  );
}
