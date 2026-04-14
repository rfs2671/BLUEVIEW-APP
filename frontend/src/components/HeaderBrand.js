import React, { useEffect } from 'react';
import { Text, Platform } from 'react-native';
import { useAuth } from '../context/AuthContext';
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

/**
 * Displays the logged-in user's company (GC) name as a clean, modern
 * geometric sans-serif wordmark in the app header, replacing the
 * static product logo.
 */
export default function HeaderBrand({ style }) {
  useEffect(() => { injectMontserrat(); }, []);
  const { user } = useAuth();
  const { colors } = useTheme();

  const raw =
    user?.gc_business_name ||
    user?.company_name ||
    'LeveLog';

  // Keep it clean: uppercased, letter-spaced serif wordmark.
  const label = String(raw).toUpperCase();

  return (
    <Text
      numberOfLines={1}
      ellipsizeMode="tail"
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
          maxWidth: 280,
        },
        style,
      ]}
    >
      {label}
    </Text>
  );
}
