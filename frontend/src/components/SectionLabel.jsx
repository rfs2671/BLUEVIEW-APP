import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '../context/ThemeContext';
import { spacing, typography } from '../styles/theme';

/**
 * A ruled section label: a short tick, the label, then a rule that runs to the edge. It names a section the way a
 * drawing's title block does and replaces the box that used to enclose the section's contents. The tick and rule take
 * the other theme's tone (theme.js `ruled`): steel blue and navy on paper, beige on navy.
 *
 * The label is passed as a `label` prop (a string the caller owns), and is rendered unchanged, so anything that reads the page for that text still finds it.
 */
export default function SectionLabel({ label, style }) {
  const { colors } = useTheme();
  const r = colors.ruled;
  return (
    <View style={[styles.row, style]}>
      <View style={[styles.tick, { backgroundColor: r.tick }]} />
      <Text style={[typography.label, styles.text, { color: r.ink }]}>{label}</Text>
      <View style={[styles.rule, { backgroundColor: r.rule }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm + 2, marginBottom: spacing.sm, marginTop: spacing.md },
  tick: { width: 28, height: 2, borderRadius: 1 },
  text: { flexShrink: 1 },
  rule: { flex: 1, height: StyleSheet.hairlineWidth < 1 ? 1 : StyleSheet.hairlineWidth },
});
