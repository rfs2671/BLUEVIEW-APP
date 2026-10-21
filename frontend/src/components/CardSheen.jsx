import React from 'react';
import { View, StyleSheet } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useTheme } from '../context/ThemeContext';
import { withAlpha } from '../styles/semanticColors';

/**
 * The card SHEEN: the one accent every card shares. A faint wash falling from the top edge and a hairline highlight
 * that fades out at both of its ends, so the card reads as a material catching light rather than a box with a stripe.
 * Each theme takes the other theme's tone (theme.js `sheen`): dark cards the light theme's beige, light cards the dark
 * theme's blue.
 *
 * It is purely decorative. It paints over the card's own fill, takes no touches (`pointerEvents: 'none'`) and is hidden
 * from assistive tech, so a card behaves exactly as it did without it.
 *
 * `radius` is the card's corner radius: the overlay rounds its own top corners so it never needs the card to clip, and
 * a card that casts an iOS shadow cannot clip.
 * `depth` is how far the wash falls. A tall card takes the default; a short one (a 40px button) passes a smaller depth
 * so the wash does not cover it.
 */
export default function CardSheen({ radius = 14, depth = 46 }) {
  const { colors } = useTheme();
  const sheen = colors.sheen;
  if (!sheen) return null;
  const wash = [withAlpha(sheen.color, sheen.wash), withAlpha(sheen.color, 0)];
  const line = [withAlpha(sheen.color, 0), sheen.color, sheen.color, withAlpha(sheen.color, 0)];
  return (
    <View
      pointerEvents="none"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[styles.layer, { height: depth, borderTopLeftRadius: radius, borderTopRightRadius: radius }]}
    >
      <LinearGradient colors={wash} start={{ x: 0.5, y: 0 }} end={{ x: 0.5, y: 1 }} style={StyleSheet.absoluteFill} />
      <LinearGradient
        colors={line}
        locations={[0, 0.25, 0.75, 1]}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 0 }}
        style={styles.hairline}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  layer: { position: 'absolute', top: 0, left: 0, right: 0, overflow: 'hidden' },
  hairline: { position: 'absolute', top: 0, left: '10%', right: '10%', height: 1 },
});
