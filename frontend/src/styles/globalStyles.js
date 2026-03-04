import { StyleSheet, Dimensions } from 'react-native';
import { colors, spacing, borderRadius, typography } from './theme';

const { width } = Dimensions.get('window');

/**
 * Global styles matching Base44 Glassmorphism aesthetic
 */
export const globalStyles = StyleSheet.create({
  // Container styles
  container: {
    flex: 1,
  },
  
  screenContainer: {
    flex: 1,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: 120, // Space for floating nav
  },
  
  // Glass card styles
  glassCard: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xxl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    overflow: 'hidden',
  },
  
  statCard: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.lg,
  },
  
  // Input styles
  inputGlass: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    color: colors.text.primary,
    fontSize: 16,
  },
  
  // Button styles
  btnGlass: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  
  btnIcon: {
    width: 44,
    height: 44,
    borderRadius: borderRadius.full,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  
  // Icon pod (circular icon container)
  // Light: bg-[#1565C0]/10, border-[#1565C0]/20
  // Dark:  transparent, border from glass
  iconPod: {
    width: 52,
    height: 52,
    borderRadius: borderRadius.full,
    backgroundColor: colors.iconPod.background,
    borderWidth: 1,
    borderColor: colors.iconPod.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  
  // Text styles
  textHero: {
    ...typography.hero,
    color: colors.text.primary,
  },
  
  textH1: {
    ...typography.h1,
    color: colors.text.primary,
  },
  
  textH2: {
    ...typography.h2,
    color: colors.text.primary,
  },
  
  textH3: {
    ...typography.h3,
    color: colors.text.primary,
  },
  
  textBody: {
    ...typography.body,
    color: colors.text.secondary,
  },
  
  textSmall: {
    ...typography.small,
    color: colors.text.muted,
  },
  
  textLabel: {
    ...typography.label,
    color: colors.text.muted,
  },
});

export default globalStyles;
