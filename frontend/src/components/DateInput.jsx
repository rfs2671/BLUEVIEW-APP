import React, { useEffect, useRef, useState } from 'react';
import {
  View, Text, TextInput, StyleSheet, Platform,
} from 'react-native';
import {
  DATE_DISPLAY_FORMAT, entryState, initialEntryText, nextEntryText,
  storedDateNote, valueForHost,
} from '../utils/dateEntry';

/**
 * THE date field. Every date a person types in this app is typed here.
 *
 * Number pad, MM/DD/YYYY with the slashes inserted as the digits arrive, an
 * impossible date named inline while it is typed, and ISO handed to the host.
 * Every rule is in src/utils/dateEntry.js; this file only renders them.
 * dateInputCensus.test.cjs fails if a date field anywhere in app/ or src/
 * does not come through here.
 *
 * ── PROPS ───────────────────────────────────────────────────────────────────
 *
 *   value       the host's string: '' | 'YYYY-MM-DD' | text being typed |
 *               a stored value this app did not write ('07/212029').
 *   onChange    called with the next host value — ONLY on a keystroke or a
 *               paste, never on mount. See dateEntry.js for what it carries.
 *   palette     { error, hint } — REQUIRED, and read from the HOST. See below.
 *   as          the input to render: TextInput (default) or GlassInput.
 *   convertsOnSave  true (default) when the host's Save sends
 *               toStoredDate(value); false where nothing converts an untouched
 *               stored value (the steppers), so the note does not promise it.
 *   style       the wrapper around the input AND its message — spacing goes
 *               here, so the message stays under its own field.
 *   fieldStyle  the input's own `style` (a stepper's `s.input`).
 *   everything else is passed to the input (placeholderTextColor,
 *   accessibilityLabel, editable, leftIcon for GlassInput, ...).
 *
 * ── WHY `palette` IS A PROP AND NOT useTheme() ──────────────────────────────
 *
 * The logbook stepper editors pin a LIGHT card whatever theme the phone is
 * in. A shared control inside one that paints its message from the dark
 * theme draws near-white on white, and the mount smoke cannot see it because
 * the field sits behind a tap. So this component reads NO theme: a themed
 * screen passes its theme's colours, a stepper passes `outdoor`'s. The pinned
 * hosts today are the three that render DateField — fall_protection,
 * osha_log and scaffold_maintenance.
 *
 * ── WHAT IT IS NOT ──────────────────────────────────────────────────────────
 *
 * NOT A NATIVE PICKER. Every picker package carries a native module, and a
 * native module turns an over-the-air fix into a store build (the reason
 * DateField and TimeField were hand-built). This is a TextInput.
 *
 * NOT A WRITER. Opening a form that holds '07/212029' shows 07/21/2029 with a
 * note, and does not call onChange: the host's value is untouched, so nothing
 * is dirty and nothing is saved. The value reaches the database only through
 * the host's Save, via toStoredDate().
 *
 * DECLARED AT MODULE SCOPE, and must stay there. A component declared inside
 * a render body is a new type every render; React remounts the TextInput on
 * each keystroke and the keyboard closes after every digit (de2b330).
 */
export default function DateInput({
  value,
  onChange,
  palette,
  as: Input = TextInput,
  convertsOnSave = true,
  placeholder = DATE_DISPLAY_FORMAT,
  style,
  fieldStyle,
  ...inputProps
}) {
  const stored = value == null ? '' : String(value);
  const [text, setText] = useState(() => initialEntryText(stored));
  const [touched, setTouched] = useState(false);
  // THE LAST VALUE THIS FIELD HANDED UP. When the host's value comes back as
  // exactly that, it is our own echo and the text he is typing is left alone.
  // Anything else is the host speaking — a reset, a calendar tap, a different
  // record opened — and the field re-reads it.
  const emitted = useRef(stored);

  useEffect(() => {
    if (stored === emitted.current) return;
    emitted.current = stored;
    setText(initialEntryText(stored));
    setTouched(false);
  }, [stored]);

  const handleChange = (raw) => {
    const next = nextEntryText(text, raw);
    setText(next);
    setTouched(true);
    // ISO, '' WHEN THE FIELD IS EMPTY, OR THE TEXT AS TYPED. There is no
    // mode: a host that asked for a blank instead of the typed text is how a
    // filed logbook came to record '' for a date the CP had typed, and how a
    // good stored date was lost to an edit he never finished. See
    // valueForHost in src/utils/dateEntry.js.
    const out = valueForHost(next);
    emitted.current = out;
    if (out !== stored) onChange(out);
  };

  // UNTOUCHED, the field speaks about what was STORED; once he types, about
  // what he typed. An unfinished date is a hint, not an error — he is
  // mid-word — but an impossible one is named at once.
  let message = null;
  if (!touched) {
    message = storedDateNote(stored, { convertsOnSave });
  } else {
    const st = entryState(text);
    if (st.error) message = { tone: st.partial ? 'hint' : 'error', text: st.error };
  }
  const colour = message && (message.tone === 'error' ? palette.error : palette.hint);

  return (
    <View style={style}>
      <Input
        {...inputProps}
        style={fieldStyle}
        value={text}
        onChangeText={handleChange}
        placeholder={placeholder}
        keyboardType="number-pad"
        // RN-web renders keyboardType as nothing a phone browser honours;
        // inputMode is what brings up the digit pad there.
        {...(Platform.OS === 'web' ? { inputMode: 'numeric' } : {})}
        autoCapitalize="none"
        autoCorrect={false}
      />
      {message ? (
        <Text
          style={[styles.message, { color: colour }]}
          accessibilityLiveRegion="polite"
        >
          {message.text}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  message: { fontSize: 13, lineHeight: 18, marginTop: 4 },
});
