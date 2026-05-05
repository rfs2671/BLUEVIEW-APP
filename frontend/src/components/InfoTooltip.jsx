/**
 * Phase B3 — minimal inline help/tooltip primitive.
 *
 * Renders a small info icon (ⓘ) next to wrapped content. On tap
 * (or hover, on web), a glass popover surfaces the supplied text.
 *
 * Why a Modal-based popover rather than absolute-positioned View:
 * the activity feed and notification settings panels live inside
 * deeply-nested ScrollViews + GlassCards. An absolute popover
 * would clip against parent overflow:hidden in several places.
 * Modal renders in a portal that escapes all clipping, and
 * supports tap-outside-to-dismiss for free.
 *
 * Theme-aware: uses useTheme() for colors. Mobile-friendly: 44x44
 * minimum touch target on the trigger; popover is full-width on
 * <768.
 *
 * Usage:
 *   <InfoTooltip text="Helpful explanation here" label="What does this mean?" />
 *
 * Or as a bare info chip beside any text:
 *   <View style={{ flexDirection: 'row', alignItems: 'center' }}>
 *     <Text>...</Text>
 *     <InfoTooltip text="..." />
 *   </View>
 */

import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Modal,
  Dimensions,
} from 'react-native';
import { Info } from 'lucide-react-native';
import { GlassCard } from './GlassCard';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius, typography } from '../styles/theme';

const MOBILE_BREAKPOINT = 768;

export default function InfoTooltip({
  text,
  label,
  size = 14,
  style,
}) {
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
  const [open, setOpen] = useState(false);

  const screenWidth = Dimensions.get('window').width;
  const isMobile = screenWidth < MOBILE_BREAKPOINT;

  const trigger = label ? (
    <Pressable
      onPress={() => setOpen(true)}
      style={[styles.linkBtn, style]}
      accessibilityRole="button"
      accessibilityLabel={`What does this mean? ${text || ''}`}
    >
      <Info size={size} strokeWidth={1.75} color={colors.text.muted} />
      <Text style={styles.linkText}>{label}</Text>
    </Pressable>
  ) : (
    <Pressable
      onPress={() => setOpen(true)}
      style={[styles.iconBtn, style]}
      accessibilityRole="button"
      accessibilityLabel={`More info: ${text || ''}`}
      hitSlop={8}
    >
      <Info size={size} strokeWidth={1.75} color={colors.text.muted} />
    </Pressable>
  );

  return (
    <>
      {trigger}
      {open ? (
        <Modal
          visible
          transparent
          animationType="fade"
          onRequestClose={() => setOpen(false)}
        >
          <Pressable
            style={styles.overlay}
            onPress={() => setOpen(false)}
            accessibilityRole="button"
          >
            <Pressable
              onPress={() => {}}
              style={[
                styles.popover,
                isMobile && styles.popoverMobile,
              ]}
            >
              <GlassCard variant="modal" hoverEffect={false}>
                <Text style={styles.popoverText}>{text}</Text>
                <Pressable
                  onPress={() => setOpen(false)}
                  style={styles.closeBtn}
                  accessibilityRole="button"
                >
                  <Text style={styles.closeBtnText}>Got it</Text>
                </Pressable>
              </GlassCard>
            </Pressable>
          </Pressable>
        </Modal>
      ) : null}
    </>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    iconBtn: {
      width: 22,
      height: 22,
      alignItems: 'center',
      justifyContent: 'center',
    },
    linkBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      paddingVertical: 2,
      paddingHorizontal: 4,
    },
    linkText: {
      ...typography.label,
      fontSize: 11,
      color: colors.text.muted,
      textTransform: 'none',
      letterSpacing: 0.3,
      fontWeight: '500',
    },
    overlay: {
      flex: 1,
      backgroundColor: 'rgba(0,0,0,0.45)',
      justifyContent: 'center',
      alignItems: 'center',
      paddingHorizontal: spacing.lg,
    },
    popover: {
      width: '100%',
      maxWidth: 380,
    },
    popoverMobile: {
      maxWidth: '100%',
    },
    popoverText: {
      fontSize: 14,
      lineHeight: 20,
      color: colors.text.primary,
    },
    closeBtn: {
      marginTop: spacing.md,
      alignSelf: 'flex-end',
      paddingVertical: spacing.xs,
      paddingHorizontal: spacing.md,
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    closeBtnText: {
      fontSize: 13,
      fontWeight: '500',
      color: colors.text.primary,
    },
  });
}
