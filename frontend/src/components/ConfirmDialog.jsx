import React from 'react';
import { Modal, View, Text, Pressable, StyleSheet, Platform } from 'react-native';
import { AlertTriangle } from 'lucide-react-native';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius, typography } from '../styles/theme';

/**
 * Themed confirm dialog for destructive actions.
 *
 * Props:
 *   visible          — bool, whether the dialog is showing
 *   title            — header text (e.g. "Delete file?")
 *   message          — body text describing what will happen
 *   details          — optional bullet list of specific consequences (array of strings)
 *   confirmLabel     — text on the destructive button (default "Delete")
 *   cancelLabel      — text on the cancel button (default "Cancel")
 *   destructive      — bool, renders the confirm button in red (default true)
 *   onConfirm        — () => void
 *   onCancel         — () => void
 */
export default function ConfirmDialog({
  visible,
  title = 'Are you sure?',
  message = '',
  details = [],
  confirmLabel = 'Delete',
  cancelLabel = 'Cancel',
  destructive = true,
  onConfirm,
  onCancel,
}) {
  const { colors, isDark } = useTheme();

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onCancel}
    >
      <View style={styles.backdrop}>
        <View style={[styles.card, { backgroundColor: isDark ? '#0f172a' : '#ffffff', borderColor: isDark ? '#1e293b' : '#e2e8f0' }]}>
          <View style={styles.header}>
            <View style={[styles.iconWrap, { backgroundColor: destructive ? 'rgba(239,68,68,0.15)' : 'rgba(59,130,246,0.15)' }]}>
              <AlertTriangle size={22} strokeWidth={2} color={destructive ? '#ef4444' : '#3b82f6'} />
            </View>
            <Text style={[styles.title, { color: colors.text.primary }]}>{title}</Text>
          </View>

          {!!message && (
            <Text style={[styles.message, { color: colors.text.secondary }]}>{message}</Text>
          )}

          {details && details.length > 0 && (
            <View style={styles.details}>
              {details.map((line, i) => (
                <View key={i} style={styles.detailRow}>
                  <Text style={[styles.detailBullet, { color: destructive ? '#ef4444' : '#3b82f6' }]}>•</Text>
                  <Text style={[styles.detailText, { color: colors.text.secondary }]}>{line}</Text>
                </View>
              ))}
            </View>
          )}

          <View style={styles.actions}>
            <Pressable
              onPress={onCancel}
              style={({ pressed }) => [
                styles.btn,
                styles.btnCancel,
                { borderColor: isDark ? '#334155' : '#cbd5e1', opacity: pressed ? 0.7 : 1 },
              ]}
            >
              <Text style={[styles.btnCancelText, { color: colors.text.primary }]}>{cancelLabel}</Text>
            </Pressable>
            <Pressable
              onPress={onConfirm}
              style={({ pressed }) => [
                styles.btn,
                styles.btnConfirm,
                { backgroundColor: destructive ? '#dc2626' : '#2563eb', opacity: pressed ? 0.85 : 1 },
              ]}
            >
              <Text style={styles.btnConfirmText}>{confirmLabel}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(2, 6, 23, 0.65)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.lg,
  },
  card: {
    width: '100%',
    maxWidth: 440,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    padding: spacing.xl,
    ...Platform.select({
      web: { boxShadow: '0 20px 40px rgba(0,0,0,0.45)' },
      default: { elevation: 12, shadowColor: '#000', shadowOpacity: 0.4, shadowRadius: 16, shadowOffset: { width: 0, height: 8 } },
    }),
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  iconWrap: {
    width: 40, height: 40, borderRadius: 20,
    alignItems: 'center', justifyContent: 'center',
    marginRight: spacing.md,
  },
  title: {
    fontSize: 18,
    fontWeight: '700',
    flex: 1,
  },
  message: {
    fontSize: 14,
    lineHeight: 20,
    marginBottom: spacing.md,
  },
  details: {
    marginBottom: spacing.md,
    paddingLeft: spacing.xs,
  },
  detailRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 4,
  },
  detailBullet: {
    fontSize: 16,
    lineHeight: 20,
    marginRight: 8,
    fontWeight: '700',
  },
  detailText: {
    flex: 1,
    fontSize: 13,
    lineHeight: 19,
  },
  actions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  btn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 2,
    borderRadius: borderRadius.md,
    minWidth: 100,
    alignItems: 'center',
    justifyContent: 'center',
  },
  btnCancel: {
    backgroundColor: 'transparent',
    borderWidth: 1,
  },
  btnCancelText: {
    fontSize: 14,
    fontWeight: '600',
  },
  btnConfirm: {},
  btnConfirmText: {
    color: '#ffffff',
    fontSize: 14,
    fontWeight: '700',
  },
});
