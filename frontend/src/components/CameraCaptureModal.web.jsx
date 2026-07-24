import React from 'react';
import { Modal, View, Text, Pressable, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { X, Smartphone } from 'lucide-react-native';
import { chrome, border, surface, text } from '../styles/semanticColors';
import { colors, spacing, borderRadius, typography } from '../styles/theme';

/**
 * Web stub for CameraCaptureModal.
 *
 * Metro resolves platform extensions before the bare specifier, so on web this
 * file wins over CameraCaptureModal.jsx and the native module graph is never
 * entered. It is NOT resolvable on native — iOS/Android keep resolving the
 * `.jsx` sibling, and this stub never enters the native bundle.
 *
 * WHY THIS EXISTS
 * `react-native-vision-camera` throws at MODULE SCOPE on web —
 * node_modules/react-native-vision-camera/lib/commonjs/NativeCameraModule.js:14-17
 * runs a top-level `if (CameraModule == null) throw ...` because
 * Platform.OS ('web') is not in ['ios','android','macos']. The native
 * component imports it at module scope (CameraCaptureModal.jsx:6), so merely
 * *evaluating* that module on web crashed the app. Production was affected:
 * expo-router lazily evaluates route modules, so `/` was fine but navigating
 * to /logbooks/daily_jobsite hit the app's ErrorBoundary crash screen.
 *
 * Note the native component already guards RENDERING with
 * `Platform.OS !== 'web'`; without this stub the web experience would still be
 * an empty black modal with no way out. This gives an explicit exit instead.
 *
 * INTERFACE PARITY — identical props and default export to the native
 * component (`{ visible, onClose, onCapture }`), so daily_jobsite.jsx needs no
 * change. `onCapture` is accepted and intentionally unused here: on web there
 * is no capture path, and the parent treats photos as optional (it appends to
 * an optional `photos[]`; nothing gates submission on it), so dismissing this
 * modal returns the user to a fully usable form rather than a dead end.
 */
export default function CameraCaptureModal({ visible, onClose, onCapture }) { // eslint-disable-line no-unused-vars
  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <SafeAreaView
        style={[styles.container, { backgroundColor: colors.background.middle }]}
      >
        <View style={styles.header}>
          <Pressable
            onPress={onClose}
            hitSlop={8}
            accessibilityRole="button"
            accessibilityLabel="Close"
            style={({ pressed }) => [styles.closeBtn, pressed && styles.pressed]}
          >
            <X size={22} strokeWidth={1.5} color={text.secondary} />
          </Pressable>
        </View>

        <View style={styles.body}>
          <View
            style={[
              styles.iconPod,
              { backgroundColor: surface.card, borderColor: border.subtle },
            ]}
          >
            <Smartphone size={28} strokeWidth={1.5} color={chrome.brand} />
          </View>

          <Text style={[styles.title, { color: text.primary }]}>
            Photo capture is mobile-only
          </Text>

          <Text style={[styles.message, { color: text.secondary }]}>
            Jobsite photos are taken in the LeveLog app on your phone or tablet.
            You can keep filling in this log here — photos are optional and
            aren&apos;t required to submit.
          </Text>

          <Pressable
            onPress={onClose}
            accessibilityRole="button"
            style={({ pressed }) => [
              styles.primaryBtn,
              { backgroundColor: chrome.brand },
              pressed && styles.pressed,
            ]}
          >
            <Text style={[styles.primaryBtnText, { color: colors.white }]}>
              Continue without a photo
            </Text>
          </Pressable>
        </View>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
  },
  closeBtn: { padding: spacing.sm },
  pressed: { opacity: 0.7 },
  body: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.xl,
    paddingBottom: spacing.xxl,
  },
  iconPod: {
    width: 64,
    height: 64,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.lg,
  },
  title: {
    fontSize: typography.sizes.lg,
    fontWeight: '600',
    textAlign: 'center',
    marginBottom: spacing.sm,
  },
  message: {
    fontSize: typography.sizes.sm,
    lineHeight: 21,
    textAlign: 'center',
    maxWidth: 420,
    marginBottom: spacing.xl,
  },
  primaryBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 2,
    borderRadius: borderRadius.md,
  },
  primaryBtnText: {
    fontSize: typography.sizes.sm,
    fontWeight: '600',
  },
});
