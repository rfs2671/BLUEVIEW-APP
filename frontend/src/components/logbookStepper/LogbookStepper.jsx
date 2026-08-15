import React from 'react';
import {
  View, Text, Pressable, ScrollView, ActivityIndicator,
  KeyboardAvoidingView, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft, ArrowRight, Check } from 'lucide-react-native';
import AnimatedBackground from '../AnimatedBackground';
import LogbookLockBar from '../LogbookLockBar';
import { outdoor } from '../../styles/theme';

/**
 * The chrome every logbook form wears.
 *
 * LIFTED VERBATIM from app/logbooks/daily_jobsite.jsx — header, progress pips,
 * scroll, the locked wrapper, the lock bar, the autosave note and the footer,
 * in that order, with the same props and the same conditions. That screen is
 * the only implementation an operator has device-tested and approved, so its
 * shape is the evidence; nothing here was redesigned during the extraction.
 *
 * WHY A COMPONENT RATHER THAN TEN COPIES. Ten forms rendering their own header
 * and footer is ten chances for one to lose the 56pt target, the single
 * primary action, or the amber pip. Asserted once here, it holds for all of
 * them.
 *
 * THE STEP CONTRACT is the one the reference settled on: an ordered list of
 * steps, one rendered at a time, indexed from 1. `steps[i].render()` is called
 * exactly where `STEPS[step]()` used to be.
 *
 * WHAT IT DOES NOT OWN: the steps themselves, the payload, and the decision of
 * what "complete" means. A form passes `incompleteSteps` because only the form
 * knows — see stepComplete in dailyJobsiteModel.
 */
export default function LogbookStepper({
  s,
  loading = false,
  title,
  subtitle,
  step,
  steps,
  onStepChange,
  onExit,
  locked = false,
  // Pip state. Numbers, 1-indexed, of steps the CP has LEFT incomplete —
  // never the one he is standing on, which is work in progress.
  incompleteSteps = [],
  a11yProgressLabel,
  // Footer.
  nextLabel,
  submitLabel,
  submitting = false,
  // THE SUBMIT GATE, client side. For an IMMEDIATE log type the signature IS
  // the freeze — the server locks the record on `status: "submitted"` alone —
  // so an unsigned submit must be UNREACHABLE, not merely discouraged. A form
  // whose signature is missing passes true here and the button cannot be
  // pressed at all. See src/utils/submitSignatureGate.test.cjs.
  //
  // Distinct from `incompleteSteps`, which only marks: an incomplete step
  // never disables anything, because a CP must be able to finish his day.
  submitDisabled = false,
  // Why Submit is unavailable. Rendered only when submitDisabled is true,
  // so a form that gates without explaining itself shows a bare button and
  // the gate test catches it.
  submitHint = '',
  // GATING *NEXT* — THE IDENTITY-FIELD EXCEPTION.
  //
  // THE RULE, unchanged: an incomplete step MARKS and never GATES, because a CP
  // must be able to finish his day. A step he cannot complete — because the
  // inspection has not happened, because the work is not done, because the
  // information does not exist yet — must never trap him. See incompleteSteps.
  //
  // THE EXCEPTION, ruled by the operator and scoped deliberately narrowly:
  // fields that IDENTIFY the record rather than describe the work. Today that
  // is toolbox_talk step 1 — where the talk happened, whose talk it was, what
  // work it covered, when, and for which company. Two of the five autofill and
  // the rest are things the CP is standing in the middle of; none of them can
  // be "not known yet" in the way an inspection result can.
  //
  // THE TEST FOR A FUTURE CALLER: gate only when every field is known at the
  // moment the screen opens. Gating a CP on work he has not done yet is the
  // thing the rule exists to prevent, and it is not what this is.
  //
  // `nextHint` is required in practice for the same reason submitHint is: a
  // dead button with no sentence is where a CP stops.
  nextDisabled = false,
  nextHint = '',
  onSubmit,
  // Lock bar.
  logType,
  logId,
  draftKey: draftKeyValue,
  onFinalized,
  onAmended,
  autosaveNote,
  // Anything that must sit OUTSIDE the SafeAreaView — a full-bleed camera
  // overlay, a modal. On native an absolute fill inside the safe area stops
  // at the inset instead of going full-bleed.
  overlays = null,
}) {
  const total = steps.length;

  if (loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <View style={s.loadingCenter}>
            <ActivityIndicator size="large" color={outdoor.text} />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  const current = steps[step - 1];

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <View style={s.header}>
          <Pressable
            style={s.headerBack}
            accessibilityRole="button"
            accessibilityLabel={a11yProgressLabel ? undefined : 'Back'}
            onPress={() => (step === 1 ? onExit() : onStepChange(step - 1))}
          >
            <ArrowLeft size={24} strokeWidth={2} color={outdoor.text} />
          </Pressable>
          <View style={s.headerText}>
            <Text style={s.headerTitle}>{title}</Text>
            <Text style={s.headerSub}>{subtitle}</Text>
          </View>
        </View>

        {/* Progress — marks only. It NEVER gates: a CP who cannot complete a
            step because the data is not there must still be able to finish and
            sign his day.

            THREE STATES, because position and completeness are different
            questions and one pip used to answer only the first:
              unfilled  not reached yet
              filled    reached
              amber     reached, LEFT, and still incomplete

            Amber is for a step he has MOVED PAST. The step he is standing on
            is not marked incomplete while he is filling it in — that would
            scold him for work in progress. */}
        <View
          style={s.progressRow}
          accessibilityRole="progressbar"
          accessibilityLabel={a11yProgressLabel}
        >
          {steps.map((_st, i) => {
            const n = i + 1;
            return (
              <View
                key={n}
                style={[
                  s.progressPip,
                  n <= step && s.progressPipOn,
                  incompleteSteps.includes(n) && s.progressPipWarn,
                ]}
              />
            );
          })}
        </View>

        {/* THE KEYBOARD MUST NOT SIT ON THE FIELD BEING TYPED INTO.
            Device round 4, finding 10: the general description on the daily
            jobsite log read as "not editable". It is the LAST multiline field
            on the longest step, directly above the signature pad, and this
            ScrollView had neither behaviour below — so on a phone the keyboard
            covered it and, with taps not persisting, the first tap on it while
            another field held focus only dismissed the keyboard. It types fine
            on web, which is why nothing in CI could see it.

            `keyboardShouldPersistTaps="handled"` — a tap on a control still
            reaches the control while the keyboard is up; a tap on nothing still
            dismisses it.

            Pure JS on both counts. A keyboard-aware scroll PACKAGE would carry
            a native module, and a native module ends OTA delivery — the same
            rule DateField and TimeField were hand-built under. */}
        <KeyboardAvoidingView
          style={s.flex1}
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        >
        <ScrollView
          style={s.scroll}
          contentContainerStyle={s.scrollContent}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
        >
          {/* A finalized log renders read-only. pointerEvents 'none' makes
              EVERY control below non-interactive — no per-field flags to miss.
              Scrolling still works; the LockBar stays interactive. */}
          <View pointerEvents={locked ? 'none' : 'auto'}>
            {current && current.render()}
          </View>

          <LogbookLockBar
            logType={logType}
            locked={locked}
            logId={logId}
            draftKey={draftKeyValue}
            canFinalize={false}
            onFinalized={onFinalized}
            onAmended={onAmended}
          />
          <Text style={s.autosaveNote}>{autosaveNote}</Text>
        </ScrollView>
        </KeyboardAvoidingView>

        {/* ONE PRIMARY ACTION, and it is the largest element on the screen. */}
        {!locked && (
          <View style={s.footer}>
            {/* A DISABLED SUBMIT MUST SAY WHY. The ported forms had no way to
                explain themselves — they do not own their footer, so the hint
                the five unported forms render above their own button had
                nowhere to live here and the CP met a dead grey button. Shown
                only on the submit step: a reason to finish is not a reason to
                stop paging. */}
            {step === total && submitDisabled && !!submitHint && (
              <Text style={s.submitHint}>{submitHint}</Text>
            )}
            {step < total && nextDisabled && !!nextHint && (
              <Text style={s.submitHint}>{nextHint}</Text>
            )}
            {step < total ? (
              <Pressable
                style={[s.primaryBtn, nextDisabled && s.primaryBtnDisabled]}
                accessibilityRole="button"
                accessibilityLabel={nextLabel}
                accessibilityState={{ disabled: nextDisabled }}
                disabled={nextDisabled}
                onPress={() => onStepChange(step + 1)}
              >
                <Text style={s.primaryBtnText}>{nextLabel}</Text>
                <ArrowRight size={26} strokeWidth={2.5} color={outdoor.textOnSelected} />
              </Pressable>
            ) : (
              <Pressable
                style={[s.primaryBtn, submitDisabled && s.primaryBtnDisabled]}
                accessibilityRole="button"
                accessibilityLabel={submitLabel}
                accessibilityState={{ disabled: submitting || submitDisabled }}
                disabled={submitting || submitDisabled}
                onPress={onSubmit}
              >
                {submitting
                  ? <ActivityIndicator size="small" color={outdoor.textOnSelected} />
                  : <Check size={26} strokeWidth={2.5} color={outdoor.textOnSelected} />}
                <Text style={s.primaryBtnText}>{submitLabel}</Text>
              </Pressable>
            )}
          </View>
        )}
      </SafeAreaView>

      {overlays}
    </AnimatedBackground>
  );
}
