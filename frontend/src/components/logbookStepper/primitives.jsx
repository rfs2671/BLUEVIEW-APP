import React from 'react';
import {
  View, Text, Pressable, TextInput, Modal,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { outdoor } from '../../styles/theme';

/**
 * The four pieces every logbook form draws with.
 *
 * LIFTED VERBATIM from app/logbooks/daily_jobsite.jsx — the only
 * implementation an operator has device-tested and approved. Nothing was
 * redesigned during the extraction.
 *
 * They take `s` (the form's stylesheet, built on buildStepperStyles) rather
 * than importing one, so a form can add keys without forking these.
 *
 * DECLARED AT MODULE LEVEL, and that is load-bearing: a component declared
 * inside a screen's render function is a NEW type on every render, so React
 * unmounts and remounts every chip on the screen for each keystroke. On the
 * older phone these screens are built for, that is the difference between
 * usable and not.
 */
export function Card({ s, style, children }) {
  return (
    <View style={[s.cardShadow, style]}>
      <LinearGradient
        colors={[outdoor.cardTop, outdoor.cardBottom]}
        start={{ x: 0.5, y: 0 }}
        end={{ x: 0.5, y: 1 }}
        style={s.cardFill}
      >
        {children}
      </LinearGradient>
    </View>
  );
}

/**
 * One chip. Selection is carried on accessibilityState as well as in the
 * styling, so the state is available to a screen reader and to a test — not
 * only to someone who can see the colour.
 */
export function ChipBase({ s, label, selected, onPress }) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: !!selected }}
      accessibilityLabel={label}
      style={[s.chip, selected && s.chipSelected]}
    >
      <Text style={[s.chipText, selected && s.chipTextSelected]}>{label}</Text>
    </Pressable>
  );
}

export function StepHeaderBase({ s, count, title }) {
  return (
    <View style={s.stepHeader}>
      <Text style={s.stepCount}>{count}</Text>
      <Text style={s.stepTitle}>{title}</Text>
    </View>
  );
}

/** One text prompt, used by the company correction and both "Other" entries. */
export function PromptModal({
  visible, title, hint, value, placeholder, onChange, onCancel, onConfirm,
  confirmLabel, cancelLabel, s,
}) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <View style={s.modalOverlay}>
        <View style={s.modalCard}>
          <Text style={s.modalTitle}>{title}</Text>
          {!!hint && <Text style={s.noteText}>{hint}</Text>}
          <TextInput
            style={s.input}
            value={value}
            onChangeText={onChange}
            placeholder={placeholder}
            placeholderTextColor={outdoor.textDim}
            autoFocus
          />
          <View style={s.modalActions}>
            <Pressable style={s.secondaryBtn} accessibilityRole="button" onPress={onCancel}>
              <Text style={s.secondaryBtnText}>{cancelLabel}</Text>
            </Pressable>
            <Pressable style={s.primaryBtn} accessibilityRole="button" onPress={onConfirm}>
              <Text style={s.primaryBtnText}>{confirmLabel}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}
