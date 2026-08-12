import React, { useMemo, useState } from 'react';
import {
  View, Text, Pressable, Modal, ScrollView,
} from 'react-native';
import { ChevronLeft, ChevronRight } from 'lucide-react-native';
import { outdoor } from '../../styles/theme';

/**
 * A date field for the logbook forms — a tapped calendar, not a typed string.
 *
 * WHY IT IS HAND-BUILT. @react-native-community/datetimepicker and every other
 * picker package carries a NATIVE MODULE, and a native module forces a rebuild:
 * the app would stop being updatable over the air for what is a control
 * change. src/i18n/index.js refused expo-localization for exactly this reason
 * and says so at :15-20. Pure JS keeps this shippable as an OTA update.
 *
 * WHAT IT STORES. `YYYY-MM-DD`, always, or '' when cleared. Unambiguous on a
 * legal document: a CP typing "8/12" meant August 12 and a reader outside the
 * US reads December 8, and both of them are looking at a filed DOB record.
 *
 * WHAT IT ACCEPTS. Anything. The value is a plain string and a log filed before
 * this control existed holds whatever was typed into the old free-text field —
 * that renders as-is and is NEVER rewritten. Only a date the CP taps from here
 * is normalised. Historical records are not migrated.
 *
 * DECLARED AT MODULE LEVEL, like the other primitives: a component declared
 * inside a screen's render function is a new type every render, so React
 * remounts it on each keystroke.
 */

const DAY_LABELS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
const MONTH_LABELS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/** '2026-08-12' -> {y, m, d}, or null for anything else. Never throws. */
export function parseISO(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || '').trim());
  if (!m) return null;
  const y = Number(m[1]); const mo = Number(m[2]); const d = Number(m[3]);
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  return { y, m: mo, d };
}

export function toISO(y, m, d) {
  return `${String(y).padStart(4, '0')}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}

/**
 * What the field SHOWS. A parseable ISO date is rendered long-form; anything
 * else is echoed exactly as stored, because a value this control did not
 * produce is a value it must not reinterpret.
 */
export function displayDate(value) {
  const p = parseISO(value);
  if (!p) return String(value || '');
  return `${MONTH_LABELS[p.m - 1]} ${p.d}, ${p.y}`;
}

/** Days in a month. Month is 1-indexed. */
export function daysInMonth(y, m) {
  return new Date(Date.UTC(y, m, 0)).getUTCDate();
}

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
  s, value, onChange, label, placeholder, clearLabel, doneLabel, today,
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
  const shown = displayDate(value);

  return (
    <View style={s.fieldBlock}>
      <Text style={s.reviewLabel}>{label}</Text>
      <Pressable
        style={s.input}
        accessibilityRole="button"
        accessibilityLabel={`${label}. ${shown || placeholder}`}
        onPress={openPicker}
      >
        <Text style={shown ? s.fieldValueText : s.fieldPlaceholderText}>
          {shown || placeholder}
        </Text>
      </Pressable>

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
