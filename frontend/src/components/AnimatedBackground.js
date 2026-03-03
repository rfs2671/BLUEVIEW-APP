import React, { useEffect, useRef } from 'react';
import { View, StyleSheet, Animated, Dimensions } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { colors } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';

const { height } = Dimensions.get('window');

const AnimatedBackground = ({ children }) => {
  const { isDark } = useTheme(); // triggers re-render on toggle
  const scanlineAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.loop(
      Animated.timing(scanlineAnim, {
        toValue: 1,
        duration: 8000,
        useNativeDriver: true,
      })
    ).start();
  }, []);

  const scanlineTranslateY = scanlineAnim.interpolate({
    inputRange:  [0, 1],
    outputRange: [-100, height + 100],
  });

  // In dark mode: subtle white scanline. In light mode: subtle blue scanline.
  const scanlineColor = isDark
    ? 'rgba(255, 255, 255, 0.02)'
    : 'rgba(0, 120, 255, 0.03)';

  return (
    <View style={[styles.container, { backgroundColor: colors.background.start }]}>
      <LinearGradient
        colors={[colors.background.start, colors.background.middle, colors.background.end]}
        style={styles.gradient}
        start={{ x: 0.5, y: 0 }}
        end={{ x: 0.5, y: 1 }}
      />
      <View style={styles.gridOverlay} />
      <Animated.View
        style={[styles.scanline, { transform: [{ translateY: scanlineTranslateY }] }]}
      >
        <LinearGradient
          colors={['transparent', scanlineColor, 'transparent']}
          style={styles.scanlineGradient}
        />
      </Animated.View>
      <View style={styles.content}>{children}</View>
    </View>
  );
};

const styles = StyleSheet.create({
  container:        { flex: 1 },
  gradient:         { ...StyleSheet.absoluteFillObject },
  gridOverlay:      { ...StyleSheet.absoluteFillObject, opacity: 0.02 },
  scanline:         { position: 'absolute', left: 0, right: 0, height: 100 },
  scanlineGradient: { flex: 1 },
  content:          { flex: 1 },
});

export default AnimatedBackground;
