import React, { useMemo, useState } from 'react';
import {
  View, Text, Pressable, Modal, ScrollView,
} from 'react-native';
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react-native';
import { outdoor } from '../../styles/theme';
import DateInput from '../DateInput';
import {
  DATE_DISPLAY_FORMAT, daysInMonth as calendarDaysInMonth, isoFromParts,
  parseStoredDate,
} from '../../utils/dateEntry';

/**
 * A date field for the logbook forms — TYPED on a number pad, with the
 * calendar one tap away beside it.
 *
 * ── TYPED FIRST, BY RULING ──────────────────────────────────────────────────
 *
 * This was a tapped calendar only. The operator's ruling is that every date
 * field in the app is typed on a numeric keypad as MM/DD/YYYY with the
 * slashes inserted as he types, so the field itself is the shared DateInput
 * (src/components/DateInput.jsx). The calendar is kept as the button beside
 * it: a manufacture date off a harness label is quicker typed, a date "last
 * Tuesday" is quicker tapped, and both land in the same stored value.
 *
 * ── THE CANVAS IS PINNED, SO THE COLOURS ARE HANDED IN ──────────────────────
 *
 * Every host of this field (fall_protection, osha_log, scaffold_maintenance)
 * renders inside the stepper's pinned LIGHT card. DateInput reads no theme;
 * this passes it `outdoor`'s ink, so its message cannot go white-on-white on
 * a phone set to dark.
 *
 * ── NOTHING HALF-TYPED IS DISCARDED ─────────────────────────────────────────
 *
 * THIS FIELD PASSED `invalid="blank"` AND THAT BLANKED FILED RECORDS. The
 * argument was that the steppers MARK incomplete steps and never gate them, so
 * there is no Save here to refuse '13/45/2029' — and the conclusion drawn was
 * to record nothing. On a legal record that is a silent loss: the CP saw his
 * text and the reason it is not a date, and the filed document said the date
 * was blank. A field already holding a good 2029-07-21 was blanked outright by
 * an edit he began and left unfinished.
 *
 * So the value is whatever the shared field decides — ISO, or THE TEXT AS
 * TYPED — and the refusal lives at FILING instead, where a draft becomes a
 * legal record: server.py's SUBMIT_INVALID_DATE, anticipated on the device by
 * src/utils/logbookDateGate.js so the CP is told on the screen that can fix
 * it. Mid-entry he is still never blocked; that part was right.
 *
 * WHY IT IS HAND-BUILT. @react-native-community/datetimepicker and every other
 * picker package carries a NATIVE MODULE, and a native module forces a rebuild:
 * the app would stop being updatable over the air for what is a control
 * change. src/i18n/index.js refused expo-localization for exactly this reason
 * and says so at :15-20. Pure JS keeps this shippable as an OTA update.
 *
 * WHAT IT STORES. `YYYY-MM-DD` for a real day, '' when cleared, and otherwise
 * exactly what he typed. Only the ISO form may be FILED — that is the gate
 * above — because "8/12" is August 12 to the CP who typed it and December 8 to
 * a reader outside the US, and both of them are looking at a filed DOB record.
 * Keeping the string is not accepting it; it is refusing to throw it away.
 *
 * WHAT IT ACCEPTS. Anything, and it rewrites nothing on its own. A log from
 * before this control holds whatever was typed into the old free-text field.
 * A value the shared reader can read unambiguously ('07/21/2029') is SHOWN
 * read, with a note naming what is stored; anything else leaves the field
 * empty with a note quoting it. Either way the stored string is untouched
 * until the CP types or taps. Historical records are not migrated.
 *
 * DECLARED AT MODULE LEVEL, like the other primitives: a component declared
 * inside a screen's render function is a new type every render, so React
 * remounts it on each keystroke.
 */

const DAY_LABELS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

// The pinned card's ink, not the phone theme's. See the header.
const PINNED_PALETTE = { error: outdoor.danger, hint: outdoor.textDim };
// The field takes the row; the calendar button keeps its 56pt square. Top-
// aligned so a two-line message under the field does not drag the button down.
const ROW = { flexDirection: 'row', alignItems: 'flex-start', gap: 8 };
const GROW = { flex: 1, minWidth: 0 };
const MONTH_LABELS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/**
 * A stored value as {y, m, d}, or null. The shared reader, so the calendar
 * opens on the same day the typed field shows — including a stored
 * '07/212029', which the field reads as 07/21/2029.
 */
export function parseISO(value) {
  const p = parseStoredDate(value);
  if (!p.iso) return null;
  const [y, m, d] = p.iso.split('-').map(Number);
  return { y, m, d };
}

export const toISO = isoFromParts;

/** Days in a month. Month is 1-indexed. Arithmetic, from the shared module. */
export const daysInMonth = calendarDaysInMonth;

/** Weekday (0=Sun) the 1st of this month falls on. */
function firstWeekday(y, m) {
  return new Date(Date.UTC(y, m - 1, 1)).getUTCDay();
}

/**
 * The grid for one month: leading blanks, then the days. Exported so the test
 * can execute the arithmetic rather than grep the JSX for it.
 */
export function monthGrid(y, m) {
  const cells = new Array(firstWeekday(y, m)).fill(null);
  for (let d = 1; d <= daysInMonth(y, m); d += 1) cells.push(d);
  return cells;
}

export default function DateField({
  s, value, onChange, label, placeholder = DATE_DISPLAY_FORMAT,
  clearLabel = 'Clear', doneLabel = 'Done', today,
}) {
  const [open, setOpen] = useState(false);
  // Where the calendar OPENS. The stored date when there is one, otherwise the
  // log's own date — never the device clock, which on a back-filled log is the
  // wrong month and makes the CP page backwards to reach the day he is filing.
  const anchor = useMemo(
    () => parseISO(value) || parseISO(today) || { y: 2000, m: 1, d: 1 },
    [value, today],
  );
  const [view, setView] = useState({ y: anchor.y, m: anchor.m });

  const openPicker = () => {
    setView({ y: anchor.y, m: anchor.m });
    setOpen(true);
  };

  const shift = (delta) => setView((v) => {
    const n = v.m + delta;
    if (n < 1) return { y: v.y - 1, m: 12 };
    if (n > 12) return { y: v.y + 1, m: 1 };
    return { y: v.y, m: n };
  });

  const selected = parseISO(value);

  return (
    <View style={s.fieldBlock}>
      <Text style={s.reviewLabel}>{label}</Text>
      <View style={ROW}>
        <DateInput
          value={value}
          onChange={onChange}
          convertsOnSave={false}
          placeholder={placeholder}
          placeholderTextColor={outdoor.textDim}
          accessibilityLabel={`${label}, month day year`}
          palette={PINNED_PALETTE}
          style={GROW}
          fieldStyle={s.input}
        />
        <Pressable
          style={s.headerBack}
          accessibilityRole="button"
          accessibilityLabel={`${label}: choose on a calendar`}
          onPress={openPicker}
        >
          <CalendarDays size={24} strokeWidth={2} color={outdoor.text} />
        </Pressable>
      </View>

      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <View style={s.modalOverlay}>
          <View style={s.modalCard}>
            <Text style={s.modalTitle}>{label}</Text>

            <View style={s.calHead}>
              <Pressable
                style={s.headerBack}
                accessibilityRole="button"
                accessibilityLabel="Previous month"
                onPress={() => shift(-1)}
              >
                <ChevronLeft size={24} strokeWidth={2} color={outdoor.text} />
              </Pressable>
              <Text style={s.calMonth}>{`${MONTH_LABELS[view.m - 1]} ${view.y}`}</Text>
              <Pressable
                style={s.headerBack}
                accessibilityRole="button"
                accessibilityLabel="Next month"
                onPress={() => shift(1)}
              >
                <ChevronRight size={24} strokeWidth={2} color={outdoor.text} />
              </Pressable>
            </View>

            <View style={s.calRow}>
              {DAY_LABELS.map((d, i) => (
                <Text key={`${d}${i}`} style={s.calDayLabel}>{d}</Text>
              ))}
            </View>

            <ScrollView style={s.calScroll}>
              <View style={s.calGrid}>
                {monthGrid(view.y, view.m).map((d, i) => {
                  if (d === null) return <View key={`b${i}`} style={s.calCell} />;
                  const isSel = !!selected && selected.y === view.y
                    && selected.m === view.m && selected.d === d;
                  return (
                    <Pressable
                      key={`d${d}`}
                      style={[s.calCell, s.calCellDay, isSel && s.calCellSelected]}
                      accessibilityRole="button"
                      accessibilityState={{ selected: isSel }}
                      accessibilityLabel={`${MONTH_LABELS[view.m - 1]} ${d}, ${view.y}`}
                      onPress={() => { onChange(toISO(view.y, view.m, d)); setOpen(false); }}
                    >
                      <Text style={[s.calCellText, isSel && s.calCellTextSelected]}>{d}</Text>
                    </Pressable>
                  );
                })}
              </View>
            </ScrollView>

            <View style={s.modalActions}>
              <Pressable
                style={s.secondaryBtn}
                accessibilityRole="button"
                onPress={() => { onChange(''); setOpen(false); }}
              >
                <Text style={s.secondaryBtnText}>{clearLabel}</Text>
              </Pressable>
              <Pressable
                style={s.secondaryBtn}
                accessibilityRole="button"
                onPress={() => setOpen(false)}
              >
                <Text style={s.secondaryBtnText}>{doneLabel}</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}
