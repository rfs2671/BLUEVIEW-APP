import React, { useState } from 'react';
import { View, StyleSheet, Pressable, Text, Platform } from 'react-native';
import { BlurView } from 'expo-blur';
import { LinearGradient } from 'expo-linear-gradient';
import { colors, borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';

/**
 * Helper: returns platform shadow styles from the colors.shadow token.
 */
function glassShadow() {
  if (!colors.shadow) return {};
  const s = colors.shadow;
  if (Platform.OS === 'web') {
    return {
      boxShadow: `${s.offset.width}px ${s.offset.height}px ${s.radius}px ${s.color}`,
    };
  }
  return {
    shadowColor:   s.color,
    shadowOffset:  s.offset,
    shadowOpacity: s.opacity,
    shadowRadius:  s.radius,
    elevation:     6,
  };
}

/* ── Light-mode gradient colours ────────────────────────────────────────────── */
const LIGHT_GRADIENT = [
  'rgba(255, 255, 255, 0.92)',           // white-ish at top
  'rgba(219, 234, 254, 0.65)',           // blue-100 at bottom
];

/* ═══════════════════════════════════════════════════════════════════════════════
   GlassCard
   ═══════════════════════════════════════════════════════════════════════════════ */
export const GlassCard = ({
  children,
  style,
  onPress,
  intensity = 20,
  hoverEffect = true,
  variant = 'default',
}) => {
  const [isHovered, setIsHovered] = useState(false);
  const { isDark } = useTheme();
  const CardWrapper = onPress ? Pressable : View;

  const cardProps = onPress
    ? {
        onPress,
        onHoverIn: () => setIsHovered(true),
        onHoverOut: () => setIsHovered(false),
      }
    : {
        onMouseEnter: () => hoverEffect && setIsHovered(true),
        onMouseLeave: () => hoverEffect && setIsHovered(false),
      };

  const blurIntensity = variant === 'modal' ? 80 : intensity;

  if (isDark) {
    /* ── DARK MODE — original implementation, unchanged ─────────────────── */
    return (
      <CardWrapper
        {...cardProps}
        style={[
          styles.containerDark,
          glassShadow(),
          style,
          isHovered && hoverEffect && styles.cardHovered,
        ]}
      >
        <BlurView
          intensity={blurIntensity}
          tint="dark"
          style={styles.blurDark}
        >
          <View
            style={[
              styles.contentPadded,
              {
                backgroundColor:
                  variant === 'modal' ? 'transparent' : colors.glass.background,
              },
            ]}
          >
            {children}
          </View>
        </BlurView>
        {/* Border overlay */}
        <View
          style={[
            styles.borderOverlay,
            isHovered &&
              hoverEffect && { borderColor: colors.glass.borderHover },
          ]}
        />
      </CardWrapper>
    );
  }

  /* ── LIGHT MODE — gradient fills the entire card, no border ──────────── */
  return (
    <CardWrapper
      {...cardProps}
      style={[
        styles.containerLight,
        glassShadow(),
        style,
        isHovered && hoverEffect && styles.cardHovered,
      ]}
    >
      <LinearGradient
        colors={LIGHT_GRADIENT}
        start={{ x: 0.5, y: 0 }}
        end={{ x: 0.5, y: 1 }}
        style={StyleSheet.absoluteFillObject}
      />
      <BlurView
        intensity={blurIntensity}
        tint="light"
        style={StyleSheet.absoluteFillObject}
      />
      {/* Content sits on top of gradient + blur */}
      <View style={styles.contentPadded}>{children}</View>
    </CardWrapper>
  );
};

/* ═══════════════════════════════════════════════════════════════════════════════
   StatCard
   ═══════════════════════════════════════════════════════════════════════════════ */
export const StatCard = ({ children, style, onPress }) => {
  const [isHovered, setIsHovered] = useState(false);
  const { isDark } = useTheme();
  const CardWrapper = onPress ? Pressable : View;

  const cardProps = onPress
    ? {
        onPress,
        onHoverIn: () => setIsHovered(true),
        onHoverOut: () => setIsHovered(false),
      }
    : {
        onMouseEnter: () => setIsHovered(true),
        onMouseLeave: () => setIsHovered(false),
      };

  if (isDark) {
    /* ── DARK ───────────────────────────────────────────────────────────── */
    return (
      <CardWrapper
        {...cardProps}
        style={[
          styles.statDark,
          glassShadow(),
          style,
          isHovered && {
            backgroundColor: colors.glass.backgroundHover,
            borderColor: colors.glass.borderHover,
            transform: [{ scale: 1.03 }, { translateY: -4 }],
          },
        ]}
      >
        <View
          style={[
            styles.statPadded,
            { backgroundColor: colors.glass.background },
          ]}
        >
          {children}
        </View>
      </CardWrapper>
    );
  }

  /* ── LIGHT — gradient fills edge-to-edge, no border ──────────────────── */
  return (
    <CardWrapper
      {...cardProps}
      style={[
        styles.statLight,
        glassShadow(),
        style,
        isHovered && {
          transform: [{ scale: 1.03 }, { translateY: -4 }],
        },
      ]}
    >
      <LinearGradient
        colors={LIGHT_GRADIENT}
        start={{ x: 0.5, y: 0 }}
        end={{ x: 0.5, y: 1 }}
        style={StyleSheet.absoluteFillObject}
      />
      <View style={styles.statPadded}>{children}</View>
    </CardWrapper>
  );
};

/* ═══════════════════════════════════════════════════════════════════════════════
   GlassListItem
   ═══════════════════════════════════════════════════════════════════════════════ */
export const GlassListItem = ({
  children,
  title,
  subtitle,
  leftIcon,
  rightIcon,
  showBorder,
  style,
  onPress,
  disabled,
}) => {
  const [isHovered, setIsHovered] = useState(false);
  const { isDark } = useTheme();

  const defaultContent = (
    <View style={{ flexDirection: 'row', alignItems: 'center', flex: 1 }}>
      {leftIcon && (
        <View style={{ marginRight: 12 }}>{leftIcon}</View>
      )}
      <View style={{ flex: 1 }}>
        {title && (
          <Text
            style={{
              color: colors.text.primary,
              fontSize: 16,
              fontWeight: '500',
            }}
          >
            {title}
          </Text>
        )}
        {subtitle && (
          <Text
            style={{ color: colors.text.muted, fontSize: 13, marginTop: 2 }}
          >
            {subtitle}
          </Text>
        )}
      </View>
      {rightIcon && (
        <View style={{ marginLeft: 12 }}>{rightIcon}</View>
      )}
    </View>
  );

  if (isDark) {
    /* ── DARK — original with border ────────────────────────────────────── */
    return (
      <Pressable
        onPress={onPress}
        disabled={disabled}
        onHoverIn={() => setIsHovered(true)}
        onHoverOut={() => setIsHovered(false)}
        style={({ pressed }) => [
          styles.listItemDark,
          glassShadow(),
          isHovered && {
            backgroundColor: colors.glass.backgroundHover,
            borderColor: colors.glass.borderHover,
            transform: [{ scale: 1.01 }, { translateY: -2 }],
          },
          pressed && styles.listItemPressed,
          disabled && styles.listItemDisabled,
          showBorder && styles.listItemBorder,
          style,
        ]}
      >
        {children || defaultContent}
      </Pressable>
    );
  }

  /* ── LIGHT — gradient fill, no border ───────────────────────────────── */
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={({ pressed }) => [
        styles.listItemLight,
        glassShadow(),
        isHovered && {
          transform: [{ scale: 1.01 }, { translateY: -2 }],
        },
        pressed && styles.listItemPressed,
        disabled && styles.listItemDisabled,
        style,
      ]}
    >
      <LinearGradient
        colors={LIGHT_GRADIENT}
        start={{ x: 0.5, y: 0 }}
        end={{ x: 0.5, y: 1 }}
        style={StyleSheet.absoluteFillObject}
      />
      <View style={styles.listItemContent}>
        {children || defaultContent}
      </View>
    </Pressable>
  );
};

/* ═══════════════════════════════════════════════════════════════════════════════
   IconPod
   ═══════════════════════════════════════════════════════════════════════════════ */
export const IconPod = ({ children, size = 52, style }) => {
  const themedChildren = React.Children.map(children, (child) => {
    if (!React.isValidElement(child)) return child;
    if (child.props.preserveColor) return child;
    return React.cloneElement(child, {
      color: colors.iconPod.iconColor,
    });
  });

  return (
    <View
      style={[
        styles.iconPod,
        {
          width: size,
          height: size,
          backgroundColor: colors.iconPod.background,
          borderColor: colors.iconPod.border,
        },
        style,
      ]}
    >
      {themedChildren}
    </View>
  );
};

/* ═══════════════════════════════════════════════════════════════════════════════
   STYLES
   ═══════════════════════════════════════════════════════════════════════════════ */
const styles = StyleSheet.create({
  /* ── GlassCard — dark ───────────────────────────────────────────────────── */
  containerDark: {
    borderRadius: borderRadius.xxl,
    overflow: 'hidden',
    position: 'relative',
    transition: 'all 0.2s ease',
  },
  blurDark: {
    overflow: 'hidden',
    borderRadius: borderRadius.xxl,
  },
  borderOverlay: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: borderRadius.xxl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    pointerEvents: 'none',
    transition: 'all 0.2s ease',
  },

  /* ── GlassCard — light ──────────────────────────────────────────────────── */
  containerLight: {
    borderRadius: borderRadius.xxl,
    overflow: 'hidden',
    position: 'relative',
    transition: 'all 0.2s ease',
  },

  /* ── GlassCard — shared ─────────────────────────────────────────────────── */
  contentPadded: {
    padding: spacing.xl,
  },
  cardHovered: {
    transform: [{ scale: 1.01 }],
  },

  /* ── StatCard — dark ────────────────────────────────────────────────────── */
  statDark: {
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    overflow: 'hidden',
    transition: 'all 0.2s ease',
  },

  /* ── StatCard — light (NO border) ───────────────────────────────────────── */
  statLight: {
    borderRadius: borderRadius.xl,
    overflow: 'hidden',
    transition: 'all 0.2s ease',
  },

  /* ── StatCard — shared padding ──────────────────────────────────────────── */
  statPadded: {
    padding: spacing.lg,
  },

  /* ── IconPod ────────────────────────────────────────────────────────────── */
  iconPod: {
    borderRadius: borderRadius.full,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },

  /* ── GlassListItem — dark ───────────────────────────────────────────────── */
  listItemDark: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    transition: 'all 0.2s ease',
  },

  /* ── GlassListItem — light (NO border) ──────────────────────────────────── */
  listItemLight: {
    borderRadius: borderRadius.xl,
    borderWidth: 0,
    overflow: 'hidden',
    transition: 'all 0.2s ease',
  },
  listItemContent: {
    padding: spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },

  listItemPressed: {
    opacity: 0.85,
    transform: [{ scale: 0.99 }],
  },
  listItemDisabled: {
    opacity: 0.5,
  },
});

export default GlassCard;
