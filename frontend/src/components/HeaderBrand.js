import React, { useEffect } from 'react';
import { Text, Platform } from 'react-native';
import { useTheme } from '../context/ThemeContext';

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

export const BRAND_LABEL = 'Levelog';

/**
 * The app header wordmark: "Levelog", in a clean geometric sans-serif.
 *
 * It used to show the company's name, which on a phone was cut to
 * "BLUEVIE…" (a 280px cap with an ellipsis). The product name is short
 * enough to fit every header, so nothing is cut: one line, and on a very
 * narrow screen the text shrinks instead of being truncated.
 */
export default function HeaderBrand({ style }) {
  useEffect(() => { injectMontserrat(); }, []);
  const { colors } = useTheme();

  return (
    <Text
      numberOfLines={1}
      adjustsFontSizeToFit
      minimumFontScale={0.6}
      accessibilityRole="header"
      style={[
        {
          fontSize: 27,
          fontWeight: '300',
          letterSpacing: 6,
          color: colors.text.primary,
          fontFamily: Platform.select({
            web: 'Montserrat, "Gotham", "Futura", "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif',
            ios: 'Avenir Next',
            android: 'sans-serif-light',
            default: 'sans-serif',
          }),
          textTransform: 'uppercase',
          flexShrink: 0,
        },
        style,
      ]}
    >
      {BRAND_LABEL}
    </Text>
  );
}
