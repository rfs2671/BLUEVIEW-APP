import React, { createContext, useContext, useState, useCallback } from 'react';
import { View, Text, StyleSheet, Animated, Pressable, Dimensions, Modal, Platform } from 'react-native';
import { BlurView } from 'expo-blur';
import { X, AlertCircle, CheckCircle, Info, AlertTriangle } from 'lucide-react-native';
import { colors, borderRadius, spacing } from '../styles/theme';

const { width } = Dimensions.get('window');

// Near-opaque fills so toasts are fully readable even when rendered
// on top of a dimmed modal scrim. The previous ~10% alpha fills
// were see-through against dark backdrops.
const toastConfig = {
  error: {
    icon: AlertCircle,
    borderColor: 'rgba(248, 113, 113, 0.5)',
    bgColor: '#2a1313',
    iconColor: '#f87171',
  },
  success: {
    icon: CheckCircle,
    borderColor: 'rgba(74, 222, 128, 0.5)',
    bgColor: '#11261a',
    iconColor: '#4ade80',
  },
  warning: {
    icon: AlertTriangle,
    borderColor: 'rgba(251, 191, 36, 0.5)',
    bgColor: '#271e0c',
    iconColor: '#fbbf24',
  },
  info: {
    icon: Info,
    borderColor: 'rgba(148, 163, 184, 0.5)',
    bgColor: '#171e2c',
    iconColor: colors.text.secondary,
  },
};

const ToastContext = createContext(null);

const Toast = ({ id, type = 'info', title, message, onClose }) => {
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
  );
};

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
};

const styles = StyleSheet.create({
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

export default ToastProvider;
