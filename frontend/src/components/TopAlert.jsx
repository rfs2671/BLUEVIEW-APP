import React from 'react';
import { View, Text, StyleSheet, Animated } from 'react-native';

let alertInstance = null;

export const showTopAlert = (message, type = 'success') => {
  if (alertInstance) {
    alertInstance(message, type);
  }
};

export default function TopAlert() {
  const [visible, setVisible] = React.useState(false);
  const [message, setMessage] = React.useState('');
  const [type, setType] = React.useState('success');
  const fadeAnim = React.useRef(new Animated.Value(0)).current;

  React.useEffect(() => {
    alertInstance = (msg, alertType) => {
      setMessage(msg);
      setType(alertType);
      setVisible(true);

      Animated.sequence([
        Animated.timing(fadeAnim, {
          toValue: 1,
          duration: 300,
          useNativeDriver: true,
        }),
        Animated.delay(3000),
        Animated.timing(fadeAnim, {
          toValue: 0,
          duration: 300,
          useNativeDriver: true,
        }),
      ]).start(() => setVisible(false));
    };

    return () => {
      alertInstance = null;
    };
  }, []);

  if (!visible) return null;

  return (
    <Animated.View
      style={[
        styles.container,
        type === 'success' && styles.success,
        type === 'error' && styles.error,
        type === 'info' && styles.info,
        { opacity: fadeAnim },
      ]}
    >
      <Text style={styles.message}>{message}</Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    top: 60,
    left: 20,
    right: 20,
    padding: 16,
    borderRadius: 12,
    zIndex: 9999,
    elevation: 999,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
  },
  success: {
    backgroundColor: '#10B981',
  },
  error: {
    backgroundColor: '#EF4444',
  },
  info: {
    backgroundColor: '#3B82F6',
  },
  message: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
    textAlign: 'center',
  },
});
