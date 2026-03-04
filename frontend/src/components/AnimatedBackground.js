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

  // Dark: subtle white scanline.
  // Light: subtle primary-blue scanline mimicking the CSS radial-gradient accents
  //   radial-gradient(ellipse at top, rgba(21,101,192,0.08) …)
  const scanlineColor = isDark
    ? 'rgba(255, 255, 255, 0.02)'
    : 'rgba(21, 101, 192, 0.04)';

  return (
    <View style={[styles.container, { backgroundColor: colors.background.start }]}>
      {/* Main gradient: linear-gradient(180deg, #d0dcf0 0%, #D6E4F7 50%, #ccd8ee 100%) */}
      <LinearGradient
        colors={[colors.background.start, colors.background.middle, colors.background.end]}
        style={styles.gradient}
        start={{ x: 0.5, y: 0 }}
        end={{ x: 0.5, y: 1 }}
      />

      {/* Light mode: extra radial-like overlay for the blue tint at top */}
      {!isDark && (
        <LinearGradient
          colors={['rgba(21, 101, 192, 0.08)', 'transparent']}
          style={styles.radialTop}
          start={{ x: 0.5, y: 0 }}
          end={{ x: 0.5, y: 0.5 }}
        />
      )}

      {/* Light mode: extra radial-like overlay for the blue tint at bottom */}
      {!isDark && (
        <LinearGradient
          colors={['transparent', 'rgba(2, 119, 189, 0.06)']}
          style={styles.radialBottom}
          start={{ x: 0.5, y: 0.5 }}
          end={{ x: 0.5, y: 1 }}
        />
      )}

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
  radialTop:        { ...StyleSheet.absoluteFillObject },
  radialBottom:     { ...StyleSheet.absoluteFillObject },
  gridOverlay:      { ...StyleSheet.absoluteFillObject, opacity: 0.02 },
  scanline:         { position: 'absolute', left: 0, right: 0, height: 100 },
  scanlineGradient: { flex: 1 },
  content:          { flex: 1 },
});

export default AnimatedBackground;
