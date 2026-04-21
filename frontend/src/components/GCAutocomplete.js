import React, { useState, useRef, useCallback } from 'react';
import {
  View,
  Text,
  TextInput,
  Pressable,
  FlatList,
  ActivityIndicator,
  StyleSheet,
  Platform,
} from 'react-native';
import { Building2 } from 'lucide-react-native';
import apiClient from '../utils/api';
import { spacing, borderRadius, typography } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';

const DEBOUNCE_MS = 350;

/**
 * GCAutocomplete — autocomplete for GC license lookup.
 * Cloned from AddressAutocomplete, hits /api/gc/autocomplete.
 *
 * Props:
 *   value        - controlled text value
 *   onChangeText - fires on every keystroke
 *   onSelect     - fires when user taps a suggestion: { license_number, business_name, licensee_name, license_expiration, license_status }
 *   placeholder  - input placeholder
 *   style        - container style override
 */
export default function GCAutocomplete({
  value = '',
  onChangeText,
  onSelect,
  placeholder = 'Search GC by company name...',
  style,
}) {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const debounceRef = useRef(null);

  const fetchSuggestions = useCallback(async (query) => {
    if (!query || query.length < 2) {
      setSuggestions([]);
      setShowDropdown(false);
      return;
    }

    setLoading(true);
    try {
      const response = await apiClient.get('/api/gc/autocomplete', {
        params: { q: query },
      });
      const results = response.data || [];
      setSuggestions(results);
      setShowDropdown(results.length > 0);
    } catch (error) {
      console.error('GC autocomplete failed:', error);
      setSuggestions([]);
      setShowDropdown(false);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleChangeText = (text) => {
    onChangeText?.(text);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchSuggestions(text), DEBOUNCE_MS);
  };

  const handleSelect = (item) => {
    onChangeText?.(item.business_name || '');
    onSelect?.({
      license_number: item.license_number,
      business_name: item.business_name,
      licensee_name: item.licensee_name,
      license_expiration: item.license_expiration,
      license_status: item.license_status,
    });
    setShowDropdown(false);
    setSuggestions([]);
  };

  const formatExpiration = (dateStr) => {
    if (!dateStr) return '';
    // Handle MM/DD/YYYY or ISO formats
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric' });
  };

  return (
    <View style={[s.container, style]}>
      <View style={s.inputRow}>
        <Building2 size={16} strokeWidth={1.5} color={colors.text.muted} style={s.icon} />
        <TextInput
          style={s.input}
          value={value}
          onChangeText={handleChangeText}
          placeholder={placeholder}
          placeholderTextColor={colors.text.subtle}
          autoCapitalize="words"
          autoCorrect={false}
          onFocus={() => {
            if (suggestions.length > 0) setShowDropdown(true);
          }}
          onBlur={() => {
            setTimeout(() => setShowDropdown(false), 200);
          }}
        />
        {loading && <ActivityIndicator size="small" color={colors.text.muted} style={s.spinner} />}
      </View>

      {showDropdown && suggestions.length > 0 && (
        <View style={s.dropdown}>
          <FlatList
            data={suggestions}
            keyExtractor={(item, index) => item.license_number || `gc-${index}`}
            keyboardShouldPersistTaps="handled"
            nestedScrollEnabled
            renderItem={({ item }) => {
              const expStr = item.license_expiration ? ` \u00b7 Exp ${formatExpiration(item.license_expiration)}` : '';
              return (
                <Pressable
                  style={s.suggestionRow}
                  // Web: TextInput onBlur fires on mousedown before
                  // onPress, closing the dropdown — the user has to
                  // click twice. Select on pressIn to beat the blur.
                  // Mobile onPress is unchanged (touch-start would
                  // fire too eagerly).
                  onPress={Platform.OS !== 'web' ? () => handleSelect(item) : undefined}
                  onPressIn={Platform.OS === 'web' ? () => handleSelect(item) : undefined}
                >
                  <Building2 size={14} strokeWidth={1.5} color={colors.text.muted} />
                  <View style={s.suggestionTextWrap}>
                    <Text style={s.suggestionMain} numberOfLines={1}>
                      {item.business_name || 'Unknown'}
                    </Text>
                    <Text style={s.suggestionSecondary} numberOfLines={1}>
                      GC-{item.license_number}{expStr}
                    </Text>
                  </View>
                </Pressable>
              );
            }}
          />
        </View>
      )}
    </View>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: {
      position: 'relative',
      zIndex: 100,
    },
    inputRow: {
      flexDirection: 'row',
      alignItems: 'center',
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      paddingHorizontal: spacing.md,
      height: 48,
    },
    icon: {
      marginRight: spacing.sm,
    },
    input: {
      flex: 1,
      fontSize: 15,
      color: colors.text.primary,
    },
    spinner: {
      marginLeft: spacing.sm,
    },
    dropdown: {
      position: 'absolute',
      top: 52,
      left: 0,
      right: 0,
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      maxHeight: 220,
      overflow: 'hidden',
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 4 },
      shadowOpacity: 0.3,
      shadowRadius: 8,
      elevation: 8,
      zIndex: 999,
    },
    suggestionRow: {
      flexDirection: 'row',
      alignItems: 'center',
      paddingVertical: spacing.sm + 2,
      paddingHorizontal: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: colors.border.subtle,
      gap: spacing.sm,
    },
    suggestionTextWrap: {
      flex: 1,
    },
    suggestionMain: {
      fontSize: 14,
      fontWeight: '500',
      color: colors.text.primary,
    },
    suggestionSecondary: {
      fontSize: 12,
      color: colors.text.muted,
      marginTop: 1,
    },
  });
}
