import React, { useEffect, useMemo, useRef, useState } from 'react';
import { View, Text, Pressable, Modal, ScrollView } from 'react-native';

/**
 * A time-of-day field — tapped, not typed.
 *
 * WHY HAND-BUILT, same reason as DateField: every picker package carries a
 * NATIVE MODULE, and a native module ends OTA delivery. src/i18n/index.js
 * refused expo-localization on exactly this ground and says so at :15-20.
 *
 * WHAT IT STORES: "hh:mm AM/PM", the format the field already held. The
 * toolbox talk seeded `meeting_time` from
 * `toLocaleTimeString('en-US', {hour:'2-digit', minute:'2-digit'})`, both PDF
 * renderers print it raw, and a filed record must not change shape because the
 * control did. A value this component did not produce is echoed as stored.
 *
 * THREE WHEELS, NOT 288 CHIPS. This was a wrapping grid of every five-minute
 * slot in the day -- 288 tappable pills in a scrolling modal, opened at
 * midnight whatever the value was, with the man's own time 92 rows down.
 *
 * AND AN OFF-GRID MINUTE WAS INVISIBLE. The grid selected the chip matching
 * {h24, m} exactly, so a stored 07:32 -- from an older build, a server
 * amendment, or the toolbox talk's original `toLocaleTimeString` seed --
 * selected nothing at all: the closed field read "07:32 AM" and the list he
 * was choosing from said he had chosen nothing. The minute wheel runs 0-59, so
 * every storable minute is now reachable and every stored minute is shown.
 *
 * NO NEW DEPENDENCY, AND THAT IS TESTED. siteSuperintendentSign.test.cjs reads
 * package.json and fails on any datetimepicker/date-picker/time-picker package.
 * Three ScrollViews and a settle handler need none.
 *
 * SETTLING IS DONE IN JS, NOT BY snapToInterval. This ships to the web
 * (react-native-web is a production dependency and the web export is the
 * deployed product), where `onMomentumScrollEnd` does not fire and
 * `snapToInterval` is not implemented. One `settle()` is called from
 * onMomentumScrollEnd, onScrollEndDrag AND a debounced onScroll, guarded
 * against the programmatic scrollTo re-entering it.
 */

const MINUTE_STEP = 5;
/** Wheel row height, and the visible half-window either side of the centre. */
const ROW_H = 44;
const PAD_ROWS = 2;

/** "09:30 AM" -> {h24, m}, or null. Never throws. */
export function parseClock(value) {
  const s = String(value || '').trim();
  const m = /^(\d{1,2}):(\d{2})\s*([AaPp])[Mm]?$/.exec(s);
  if (m) {
    let h = Number(m[1]) % 12;
    if (m[3].toLowerCase() === 'p') h += 12;
    const min = Number(m[2]);
    if (min > 59) return null;
    return { h24: h, m: min };
  }
  // 24-hour, for a value typed or stored by something else.
  const m24 = /^(\d{1,2}):(\d{2})$/.exec(s);
  if (m24) {
    const h = Number(m24[1]); const min = Number(m24[2]);
    if (h > 23 || min > 59) return null;
    return { h24: h, m: min };
  }
  return null;
}

/** {h24, m} -> "09:30 AM" — the format already on file. */
export function toClock(h24, m) {
  const period = h24 >= 12 ? 'PM' : 'AM';
  const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
  return `${String(h12).padStart(2, '0')}:${String(m).padStart(2, '0')} ${period}`;
}

/** What the field SHOWS. An unrecognised value is echoed, not reinterpreted. */
export function displayClock(value) {
  const p = parseClock(value);
  return p ? toClock(p.h24, p.m) : String(value || '');
}

/**
 * Every time on the FIVE-MINUTE grid, in order.
 *
 * NO LONGER WHAT THE PICKER OFFERS -- the minute wheel runs 0-59 -- and kept
 * deliberately at five. It is the grid `nowClock` floors a prefill onto on the
 * superintendent screen, and siteSuperintendentSign.test.cjs executes this
 * function to prove a 07:17 prefill lands on a row that can be selected.
 * Widening it to 1 would make that proof vacuous: every minute would trivially
 * be on the grid, and the floor it checks would stop being checked.
 */
export function timeOptions(step = MINUTE_STEP) {
  const out = [];
  for (let h = 0; h < 24; h += 1) {
    for (let m = 0; m < 60; m += step) out.push({ h24: h, m });
  }
  return out;
}

export default function TimeField({
  s, value, onChange, label, placeholder, clearLabel, doneLabel,
  // Marks the control itself when a gated step is missing this value — the
  // same red outline + "Required field" the text rows use, so one screen does
  // not mark two ways.
  required = false, requiredLabel = '',
}) {
  const [open, setOpen] = useState(false);
  const current = parseClock(value);
  const shown = displayClock(value);

  // THE THREE COLUMNS. Hours 1-12 and minutes 0-59, so every storable minute is
  // reachable -- the five-minute grid is still what `timeOptions` describes and
  // what a prefill is floored onto, but it is no longer what he may choose.
  const hours = useMemo(
    () => Array.from({ length: 12 }, (_, i) => {
      const h = i + 1;
      return { key: `h${h}`, label: String(h).padStart(2, '0') };
    }), [],
  );
  const minutes = useMemo(
    () => Array.from({ length: 60 }, (_, m) => (
      { key: `m${m}`, label: String(m).padStart(2, '0') }
    )), [],
  );
  const periods = useMemo(() => [{ key: 'AM', label: 'AM' }, { key: 'PM', label: 'PM' }], []);

  // AN UNSET FIELD OPENS AT 07:00 AM rather than midnight: the wheels must
  // start somewhere, and a construction day does not start at 12:00 AM. The
  // value is NOT written until he moves a wheel or taps a row -- opening the
  // picker and closing it changes nothing.
  const h24 = current ? current.h24 : 7;
  const hIdx = ((h24 % 12) === 0 ? 12 : h24 % 12) - 1;
  const mIdx = current ? current.m : 0;
  const pIdx = h24 >= 12 ? 1 : 0;

  const emit = (hi, mi, pi) => {
    const h12 = hi + 1;
    const h = (pi === 1 ? (h12 % 12) + 12 : h12 % 12);
    onChange(toClock(h, mi));
  };

  return (
    <View style={s.fieldBlock}>
      <Text style={s.reviewLabel}>{label}</Text>
      <Pressable
        style={[s.input, required && s.inputRequired]}
        accessibilityRole="button"
        accessibilityLabel={`${label}. ${shown || placeholder}`}
        onPress={() => setOpen(true)}
      >
        <Text style={shown ? s.fieldValueText : s.fieldPlaceholderText}>
          {shown || placeholder}
        </Text>
      </Pressable>
      {required && !!requiredLabel && (
        <Text style={s.requiredText}>{requiredLabel}</Text>
      )}

      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <View style={s.modalOverlay}>
          <View style={s.modalCard}>
            <Text style={s.modalTitle}>{label}</Text>
            <View style={{ flexDirection: 'row', gap: 8 }}>
              <Wheel s={s} label="HH" items={hours} index={hIdx}
                onIndex={(i) => emit(i, mIdx, pIdx)} />
              <Wheel s={s} label="MM" items={minutes} index={mIdx}
                onIndex={(i) => emit(hIdx, i, pIdx)} />
              <Wheel s={s} label="AM/PM" items={periods} index={pIdx}
                onIndex={(i) => emit(hIdx, mIdx, i)} />
            </View>
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

/*
 * `Wheel` LIVES BELOW THE DEFAULT EXPORT, DELIBERATELY.
 *
 * Two test files read this module as TEXT and re-evaluate it to run the four
 * pure helpers against the real parser -- siteSuperintendentSign.test.cjs and
 * portedFormPayloads.test.cjs both strip the imports, delete everything from
 * the first `export default` onward, and `new Function` the remainder. A
 * module-level component ABOVE that line survives the strip, and its JSX makes
 * the eval throw.
 *
 * A function declaration hoists, so TimeField can call this even though it is
 * written after it. Keep the four helpers above `export default`, and keep
 * anything containing JSX below it.
 */
/**
 * ONE COLUMN OF THE PICKER. Module scope, not nested in TimeField: a component
 * declared in a render body is a new TYPE every render, so React remounts the
 * whole column on every scroll tick and the wheel would fight the finger.
 * stepper.test.cjs states that rule for the chrome primitives and it is the
 * same rule here.
 */
function Wheel({ s, items, index, onIndex, label }) {
  const ref = useRef(null);
  const settling = useRef(false);
  const timer = useRef(null);

  // Position the wheel on the current value when it opens, without animating --
  // an animated jump on mount reads as the control moving on its own.
  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    const id = setTimeout(() => {
      settling.current = true;
      node.scrollTo({ y: index * ROW_H, animated: false });
      settling.current = false;
    }, 0);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const settle = (y) => {
    if (settling.current) return;
    const next = Math.max(0, Math.min(items.length - 1, Math.round(y / ROW_H)));
    if (next !== index) onIndex(next);
    settling.current = true;
    if (ref.current) ref.current.scrollTo({ y: next * ROW_H, animated: true });
    setTimeout(() => { settling.current = false; }, 120);
  };

  return (
    <View style={{ flex: 1 }}>
      <Text style={s.reviewLabel}>{label}</Text>
      <ScrollView
        ref={ref}
        style={{ height: ROW_H * (PAD_ROWS * 2 + 1) }}
        showsVerticalScrollIndicator={false}
        scrollEventThrottle={16}
        onMomentumScrollEnd={(e) => settle(e.nativeEvent.contentOffset.y)}
        onScrollEndDrag={(e) => settle(e.nativeEvent.contentOffset.y)}
        onScroll={(e) => {
          // THE WEB PATH. react-native-web fires neither momentum event, so a
          // debounced idle is the only reliable settle signal there. Harmless
          // on native: whichever fires first wins and the guard stops the echo.
          const y = e.nativeEvent.contentOffset.y;
          if (timer.current) clearTimeout(timer.current);
          timer.current = setTimeout(() => settle(y), 140);
        }}
      >
        <View style={{ height: ROW_H * PAD_ROWS }} />
        {items.map((it, i) => (
          <Pressable
            key={it.key}
            onPress={() => settle(i * ROW_H)}
            accessibilityRole="button"
            accessibilityState={{ selected: i === index }}
            accessibilityLabel={it.label}
            style={{ height: ROW_H, alignItems: 'center', justifyContent: 'center' }}
          >
            <Text style={[s.chipText, i === index && s.chipTextSelected]}>{it.label}</Text>
          </Pressable>
        ))}
        <View style={{ height: ROW_H * PAD_ROWS }} />
      </ScrollView>
    </View>
  );
}
