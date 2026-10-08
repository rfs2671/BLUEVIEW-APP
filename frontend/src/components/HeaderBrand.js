import React, { useEffect } from 'react';
import { Text, Platform, useWindowDimensions } from 'react-native';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import { brandLabel, brandSizing } from '../utils/brandLabel';

/* Load Montserrat once from Google Fonts on web */
let fontInjected = false;
function injectMontserrat() {
  if (fontInjected || Platform.OS !== 'web' || typeof document === 'undefined') return;
  fontInjected = true;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href =
    'https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500&display=swap';
  document.head.appendChild(link);
}

/**
 * The logged-in user's company (GC) name as the header wordmark, in a clean
 * geometric sans-serif; "Levelog" only when the company has no name.
 *
 * One line, never wrapped. A long name starts smaller and shrinks to fit
 * (not below 14pt); only a name too long even then ends in "…"
 * (utils/brandLabel.js).
 */
const BRAND_SIDE_ROOM = 150;

export default function HeaderBrand({ style }) {
  useEffect(() => { injectMontserrat(); }, []);
  const { user } = useAuth();
  const { colors } = useTheme();
  const { width } = useWindowDimensions();
  const label = brandLabel(user);
  const { fontSize, letterSpacing, minimumFontScale } = brandSizing(label);

  return (
    <Text
      numberOfLines={1}
      ellipsizeMode="tail"
      adjustsFontSizeToFit
      minimumFontScale={minimumFontScale}
      accessibilityRole="header"
      style={[
        {
          fontSize,
          fontWeight: '300',
          letterSpacing,
          color: colors.text.primary,
          fontFamily: Platform.select({
            web: 'Montserrat, "Gotham", "Futura", "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif',
            ios: 'Avenir Next',
            android: 'sans-serif-light',
            default: 'sans-serif',
          }),
          textTransform: 'uppercase',
          // The headers' rows do not shrink, so the room is set here: the
          // screen less the back button, padding and a right-side control.
          maxWidth: Math.max(160, width - BRAND_SIDE_ROOM),
        },
        style,
      ]}
    >
      {label}
    </Text>
  );
}
