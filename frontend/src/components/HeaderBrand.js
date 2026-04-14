import React from 'react';
import { Text, Platform } from 'react-native';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';

/**
 * Displays the logged-in user's company (GC) name as a classy serif wordmark
 * in the app header, replacing the static product logo.
 */
export default function HeaderBrand({ style }) {
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
          fontSize: 20,
          fontWeight: '400',
          letterSpacing: 3,
          color: colors.text.primary,
          fontFamily: Platform.select({
            web: '"Playfair Display", "Cormorant Garamond", Georgia, "Times New Roman", serif',
            ios: 'Georgia',
            android: 'serif',
            default: 'serif',
          }),
          maxWidth: 260,
        },
        style,
      ]}
    >
      {label}
    </Text>
  );
}
