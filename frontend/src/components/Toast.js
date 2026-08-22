import React, { createContext, useContext, useState, useCallback } from 'react';
import { View, Text, StyleSheet, Animated, Pressable, Dimensions, Modal, Platform } from 'react-native';
import { BlurView } from 'expo-blur';
import { X, AlertCircle, CheckCircle, Info, AlertTriangle } from 'lucide-react-native';
import { colors, borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';
import { semantic, withAlpha } from '../styles/semanticColors';

const { width } = Dimensions.get('window');

// The LIVE toast list, exposed so a second renderer inside a Modal's window can
// paint the same stack. Deliberately separate from ToastContext, which carries
// the raise-a-toast API: a screen should never reach in and read the list.
const ToastStackContext = createContext(null);

// Near-opaque fills so toasts are fully readable even when rendered on top of a
// dimmed modal scrim. A ~10% ALPHA fill was tried before and rejected: it was
// see-through against dark backdrops. So these stay fully OPAQUE — what changes
// per theme is which opaque colour we land on.
//
// The fills used to be four hardcoded near-black hexes, which is fine on the
// dark theme and unreadable on the light one: the toast text follows the theme
// (colors.text.primary), so on light it became dark navy text on a near-black
// card. Now the light fills are the state colour mixed into white, so an error
// toast is a pale red card with dark text — still obviously an error, and
// legible. Derived from colors.state.*, so no parallel palette is introduced.
const _mixOpaque = (hex, baseHex, amount) => {
  const h = (v) => {
    let s = String(v).replace('#', '');
    if (s.length === 3) s = s.split('').map((c) => c + c).join('');
    return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
  };
  const [r1, g1, b1] = h(hex);
  const [r2, g2, b2] = h(baseHex);
  const m = (a, b) => Math.round(a * amount + b * (1 - amount));
  return `rgb(${m(r1, r2)}, ${m(g1, g2)}, ${m(b1, b2)})`;
};

// Built per render so the getters resolve against the ACTIVE theme. As a
// module-scope object these froze at import — the borders too, not just fills.
const buildToastConfig = (colors, isDark) => ({
  error: {
    icon: AlertCircle,
    borderColor: semantic.criticalBorder,
    bgColor: isDark ? '#2a1313' : _mixOpaque(colors.state.critical, '#ffffff', 0.14),
    iconColor: semantic.critical,
  },
  success: {
    icon: CheckCircle,
    borderColor: semantic.verifiedBorder,
    bgColor: isDark ? '#11261a' : _mixOpaque(colors.state.verified, '#ffffff', 0.14),
    iconColor: semantic.verified,
  },
  warning: {
    icon: AlertTriangle,
    borderColor: semantic.attentionBorder,
    bgColor: isDark ? '#271e0c' : _mixOpaque(colors.state.attention, '#ffffff', 0.14),
    iconColor: semantic.attention,
  },
  info: {
    icon: Info,
    borderColor: withAlpha('#94a3b8', 0.5),
    bgColor: isDark ? '#171e2c' : _mixOpaque('#94a3b8', '#ffffff', 0.18),
    iconColor: colors.text.secondary,
  },
});

const ToastContext = createContext(null);

const Toast = ({ id, type = 'info', title, message, onClose }) => {
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
  const toastConfig = buildToastConfig(colors, isDark);
  const config = toastConfig[type] || toastConfig.info;
  const Icon = config.icon;
  const opacity = React.useRef(new Animated.Value(0)).current;
  const translateX = React.useRef(new Animated.Value(50)).current;

  React.useEffect(() => {
    // Animate in
    Animated.parallel([
      Animated.timing(opacity, {
        toValue: 1,
        duration: 300,
        useNativeDriver: true,
      }),
      Animated.timing(translateX, {
        toValue: 0,
        duration: 300,
        useNativeDriver: true,
      }),
    ]).start();

    // Auto dismiss
    const timer = setTimeout(() => {
      Animated.parallel([
        Animated.timing(opacity, {
          toValue: 0,
          duration: 200,
          useNativeDriver: true,
        }),
        Animated.timing(translateX, {
          toValue: 50,
          duration: 200,
          useNativeDriver: true,
        }),
      ]).start(() => onClose(id));
    }, 4000);

    return () => clearTimeout(timer);
  }, []);

  return (
    <Animated.View
      style={[
        styles.toast,
        { backgroundColor: config.bgColor, borderColor: config.borderColor },
        { opacity, transform: [{ translateX }] },
      ]}
    >
      <Icon size={20} strokeWidth={1.5} color={config.iconColor} />
      <View style={styles.toastContent}>
        {title && <Text style={styles.toastTitle}>{title}</Text>}
        {message && <Text style={styles.toastMessage}>{message}</Text>}
      </View>
      <Pressable onPress={() => onClose(id)} hitSlop={10}>
        <X size={16} strokeWidth={1.5} color={colors.text.muted} />
      </Pressable>
    </Animated.View>
  );
};

export const ToastProvider = ({ children }) => {
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback((toast) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { ...toast, id }]);
    return id;
  }, []);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  const toast = {
    error: (title, message) => addToast({ type: 'error', title, message }),
    success: (title, message) => addToast({ type: 'success', title, message }),
    warning: (title, message) => addToast({ type: 'warning', title, message }),
    info: (title, message) => addToast({ type: 'info', title, message }),
  };

  // Previously wrapped in a transparent native Modal so toasts would
  // paint above app Modals. Problem: RN's Modal intercepts ALL touches
  // on its root view regardless of pointerEvents on children — so while
  // a toast was visible the user couldn't tap any button underneath.
  // Using a plain absolutely-positioned View instead. Trade-off: if a
  // toast fires while an app Modal is open, the toast sits below the
  // Modal — acceptable, because toasts are transient feedback, not
  // blocking alerts.
  const hasToasts = toasts.length > 0;

  return (
    <ToastStackContext.Provider value={{ toasts, removeToast, styles }}>
    <ToastContext.Provider value={toast}>
      {children}
      {hasToasts && (
        <View
          pointerEvents="box-none"
          style={styles.toastContainer}
        >
          {toasts.map((t) => (
            <Toast key={t.id} {...t} onClose={removeToast} />
          ))}
        </View>
      )}
    </ToastContext.Provider>
    </ToastStackContext.Provider>
  );
};


/**
 * THE SAME TOASTS, PAINTED INSIDE A MODAL'S OWN WINDOW.
 *
 * A native Modal is a separate OS window — a Dialog on Android, a presented
 * view controller on iOS. `zIndex` and `elevation` are scoped to one view
 * hierarchy and React tree position is scoped to the same one, so NOTHING in
 * the app's tree can paint above a Modal. That is why the provider's stack
 * carries zIndex 99999 and still renders behind every sheet, and why moving
 * ToastProvider around _layout.jsx changes nothing: it is already the
 * innermost provider.
 *
 * Wrapping the provider's stack in its own Modal was tried and reverted in
 * efea5c9 ("toast blocking UI"): RN's Modal root intercepts every touch
 * regardless of pointerEvents on its children, so for the four seconds a toast
 * was up the user could not tap anything.
 *
 * So the fix is not a different layer — it is a SECOND MOUNT POINT. Drop
 * <ToastHost /> inside a Modal's own tree and toasts raised while that sheet
 * is open render in that sheet's window, in front of it.
 *
 * ONE MECHANISM, ONE TREATMENT. Same ToastProvider, same useToast(), same
 * Toast component, same styles object — the only thing that differs is which
 * window it paints into. It is not a per-screen banner and must not become
 * one; a modal that needs to report an error still calls toast.error().
 *
 * Renders nothing when no toast is up, so an idle sheet is unaffected.
 */
export const ToastHost = () => {
  const stack = useContext(ToastStackContext);
  if (!stack || stack.toasts.length === 0) return null;
  return (
    <View pointerEvents="box-none" style={stack.styles.toastContainer}>
      {stack.toasts.map((t) => (
        <Toast key={t.id} {...t} onClose={stack.removeToast} />
      ))}
    </View>
  );
};

export const useToast = () => {
  // Phase C1.1 — never throw. The previous implementation threw
  // when ToastContext was null, which forced every consumer to
  // wrap the call in try/catch (see RouteGuard pre-C1). React's
  // rules-of-hooks consider useXxx() inside a try/catch a
  // conditional-hook pattern — the throwing branch creates a
  // hook-order discrepancy that surfaces in production as
  // React error #310. By returning null here, consumers can call
  // useToast() unconditionally and just guard the result before
  // touching toast.error / toast.success.
  return useContext(ToastContext) || null;
};

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  toastContainer: {
    position: 'absolute',
    top: 60,
    right: 16,
    left: 16,
    alignItems: 'flex-end',
    zIndex: 99999,
    elevation: 99999,
    gap: spacing.sm,
    // Modal content fills the OS window; box-none on the wrapper
    // lets underlying touches pass through while this stays tappable.
  },
  toast: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    width: Math.min(320, width - 32),
    padding: spacing.md,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    gap: spacing.sm,
  },
  toastContent: {
    flex: 1,
  },
  toastTitle: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: 2,
  },
  toastMessage: {
    fontSize: 13,
    color: colors.text.secondary,
    lineHeight: 18,
  },
  });
}
export default ToastProvider;
