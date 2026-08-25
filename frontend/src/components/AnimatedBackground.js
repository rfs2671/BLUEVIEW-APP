import React, { useEffect, useRef } from 'react';
import { View, StyleSheet, Animated, Dimensions } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { colors, outdoor } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';
import { withAlpha } from '../styles/semanticColors';

const { height } = Dimensions.get('window');

/**
 * `pinned` PAINTS THE OUTDOOR CANVAS INSTEAD OF THE LIVE THEME.
 *
 * The logbook editors are deliberately pinned to the app's light look (see the
 * `outdoor` block in styles/theme.js): a CP fills a compliance log standing
 * outdoors, often in direct sun, and a dark card is unreadable there whatever
 * theme he has set. That pin was applied to the CONTENT and never to the
 * CANVAS, so every one of those screens drew #0A1929 ink on AnimatedBackground's
 * live #050a12 gradient. The cards survived (they carry their own fill); the
 * step title, "STEP 1 OF 5", the section headers and "Saved automatically" did
 * not, because their containers have no backgroundColor and sit straight on the
 * canvas. `outdoor.backgroundStart/Middle/End` were defined FOR this, commented
 * "the three stops AnimatedBackground paints", and consumed by nothing.
 *
 * PINNING MEANS ALL THREE THINGS `isDark` DRIVES, not just the stops: the
 * gradient, the scanline tint, AND the two light-only radial overlays. Pinning
 * the stops alone would leave a light canvas with a dark-mode scanline and no
 * tint - a third look, matching neither theme. So `pinned` forces the whole
 * component to behave exactly as it does in light mode, which is what makes a
 * pinned screen pixel-equivalent to its light-mode self.
 *
 * DEFAULT IS UNCHANGED. `pinned` is false everywhere it is not passed, so every
 * correctly-themed screen renders byte-identically to before.
 */
const AnimatedBackground = ({ children, pinned = false }) => {
  // The hook still runs when pinned: it is what re-renders this subtree on a
  // theme toggle, and a pinned screen must keep re-rendering with the rest of
  // the app even though its own colours do not move.
  const { isDark: themeIsDark } = useTheme();
  const isDark = pinned ? false : themeIsDark;
  const stops = pinned
    ? [outdoor.backgroundStart, outdoor.backgroundMiddle, outdoor.backgroundEnd]
    : [colors.background.start, colors.background.middle, colors.background.end];
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
    ? withAlpha('#ffffff', 0.02)
    : 'rgba(21, 101, 192, 0.04)';

  return (
    <View style={[styles.container, { backgroundColor: stops[0] }]}>
      {/* Main gradient: linear-gradient(180deg, #d0dcf0 0%, #D6E4F7 50%, #ccd8ee 100%) */}
      <LinearGradient
        colors={stops}
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
