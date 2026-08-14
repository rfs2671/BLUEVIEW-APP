import React, { useMemo, useState } from 'react';
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
 * FIVE-MINUTE GRANULARITY. A toolbox talk is minuted to the nearest few
 * minutes, not the second, and 288 tappable rows is a usable list where 1,440
 * is not.
 */

const MINUTE_STEP = 5;

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

/** Every selectable time, in order. Exported so a test can execute it. */
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
  const options = useMemo(() => timeOptions(), []);
  const current = parseClock(value);
  const shown = displayClock(value);

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
            <ScrollView style={s.calScroll}>
              <View style={s.chipWrap}>
                {options.map(({ h24, m }) => {
                  const text = toClock(h24, m);
                  const sel = !!current && current.h24 === h24 && current.m === m;
                  return (
                    <Pressable
                      key={text}
                      style={[s.chip, sel && s.chipSelected]}
                      accessibilityRole="button"
                      accessibilityState={{ selected: sel }}
                      accessibilityLabel={text}
                      onPress={() => { onChange(text); setOpen(false); }}
                    >
                      <Text style={[s.chipText, sel && s.chipTextSelected]}>{text}</Text>
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
